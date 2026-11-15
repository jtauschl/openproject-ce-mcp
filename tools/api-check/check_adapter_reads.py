#!/usr/bin/env python3
"""The snapshot of what the pinned OpenProject representers render, and its regeneration check.

`representer_fields.json` records, per representer path, every (location, wire name) the representer renders and the
pinned versions that render it. The location is `property`, `link`, `embedded`, `link-member:<link>` or
`value-member:<property>`. The adapter reads guard compares what the adapters read with this snapshot in CI, where
the 4.7 GB of sources are not available; this tool is what keeps the snapshot true:

    python tools/api-check/check_adapter_reads.py --write   # regenerate from op-sources/<version>/
    python tools/api-check/check_adapter_reads.py --check   # regenerate and diff against the committed file

A path is a real file under the checkout (`lib/api/...`, `modules/*/lib/api/...`, `modules/*/app/representers/...`) or
a pseudo path `<engine.rb>#extend_api_response:<representer path>` for the fields an engine adds to a core
representer, inline or through a patch module. Exit status: 0 clean, 1 snapshot differs or a source cannot be
parsed, 2 sources missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath

from op_sources import SOURCES, MissingCheckoutError, pinned_versions, require_checkouts
from representer_locations import (
    FORMATTABLE_MEMBERS,
    LINK_OBJECT_MEMBERS,
    Entry,
    entries,
    extract_declarations,
    extract_extensions,
    patch_file,
    read_acronyms,
    unparsed,
)

SNAPSHOT = Path(__file__).resolve().parent / "representer_fields.json"
FORMAT = 1


def version_ranges(present: list[str], pins: list[str]) -> str:
    """`["16.0", "16.1", "17.0"]` over the pinned order -> `"16.0-16.1,17.0"`: a run of consecutive pinned versions."""
    runs: list[list[str]] = []
    previous = -2
    for label in present:
        index = pins.index(label)
        if index == previous + 1 and runs:
            runs[-1][1] = label
        else:
            runs.append([label, label])
        previous = index
    return ",".join(first if first == last else f"{first}-{last}" for first, last in runs)


def expand_ranges(ranges: str, pins: list[str]) -> list[str]:
    out: list[str] = []
    for part in ranges.split(","):
        first, _, last = part.partition("-")
        out += pins[pins.index(first) : pins.index(last or first) + 1]
    return out


_NOT_REPRESENTER_FILES = ("_api.rb", "path_helper.rb")
# The BCF API (v2.1) is not API v3: its representers render snake_case names without the camel-casing strategy.
_NOT_API_V3 = ("modules/bim/app/representers/bim/bcf/",)
_API_SUBTREES = ("lib/api", "app/representers")


def _is_source_file(checkout: Path, file: Path, declared: bool) -> bool:
    """A representer by name, or a base class under an API subtree that declares fields (collection, form, single)."""
    if "representer" in file.name:
        return True
    relative = file.relative_to(checkout).as_posix()
    in_api = relative.startswith(_API_SUBTREES) or ("/lib/api/" in relative or "/app/representers/" in relative)
    return in_api and declared and not file.name.endswith(_NOT_REPRESENTER_FILES)


def _path_entries(checkout: Path) -> dict[str, tuple[list[Entry], list[str]]]:
    """Every representer path of one checkout with the entries it renders and the macro lines it could not read."""
    found: dict[str, tuple[list[Entry], list[str]]] = {}
    inflections = checkout / "config/initializers/inflections.rb"
    acronyms = read_acronyms(inflections.read_text()) if inflections.is_file() else {}
    for file in sorted(checkout.rglob("*.rb")):
        relative = file.relative_to(checkout).as_posix()
        if not relative.startswith(("lib/", "app/", "modules/")) or relative.startswith(_NOT_API_V3):
            continue
        if "representer" not in file.name and ("/api/" not in f"/{relative}" and "/representers/" not in relative):
            continue
        text = file.read_text()
        declarations = extract_declarations(text, acronyms)
        if _is_source_file(checkout, file, bool(declarations)):
            found[relative] = (entries(declarations), unparsed(text))
    for engine in sorted((checkout / "modules").glob("*/lib/**/engine.rb")):
        text = engine.read_text()
        if "extend_api_response" not in text:
            continue
        relative = engine.relative_to(checkout).as_posix()
        for extension in extract_extensions(text):
            if not (checkout / extension.target).is_file():
                raise ValueError(f"{relative}: extends {extension.target}, which does not exist in this version")
            if extension.inline_body is not None:
                body = extension.inline_body
            else:
                assert extension.patch_class is not None
                source = checkout / patch_file(relative, extension.patch_class)
                if not source.is_file():
                    raise ValueError(
                        f"{relative}: patch {extension.patch_class} is not at {source.relative_to(checkout)}"
                    )
                body = source.read_text()
            key = f"{relative}#extend_api_response:{extension.target}"
            previous_entries, previous_unparsed = found.get(key, ([], []))
            found[key] = (
                [*previous_entries, *entries(extract_declarations(body, acronyms))],
                [*previous_unparsed, *unparsed(body)],
            )
    return found


def build(sources: Path | None = None) -> dict:
    sources = sources or SOURCES
    pins = pinned_versions()
    labels = list(pins)
    versions: dict[str, dict[str, dict[tuple[str, str], bool]]] = {}
    unreadable: dict[str, list[str]] = {}
    for label in labels:
        for path, (path_entries, lines) in _path_entries(sources / label).items():
            slot = versions.setdefault(path, {}).setdefault(label, {})
            for entry in path_entries:
                slot[(entry.location, entry.wire_name)] = (
                    slot.get((entry.location, entry.wire_name), False) or entry.enterprise
                )
            if lines:
                unreadable[path] = list(dict.fromkeys([*unreadable.get(path, []), *lines]))
    paths: dict[str, dict] = {}
    for path in sorted(versions):
        per_version = versions[path]
        keys = sorted({key for slot in per_version.values() for key in slot})
        rendered: dict[str, dict] = {}
        for location, wire in keys:
            present = [label for label in labels if (location, wire) in per_version.get(label, {})]
            value: dict = {"versions": version_ranges(present, labels)}
            if any(per_version[label][(location, wire)] for label in present):
                value["enterprise"] = True
            rendered[f"{location}|{wire}"] = value
        paths[path] = {
            "versions": version_ranges([label for label in labels if label in per_version], labels),
            "fields": rendered,
        }
        if path in unreadable:
            paths[path]["unparsed"] = unreadable[path]
    return {
        "format": FORMAT,
        "pinned": pins,
        "link_object_members": list(LINK_OBJECT_MEMBERS),
        "value_members": list(FORMATTABLE_MEMBERS),
        "paths": paths,
    }


def dumps(snapshot: dict) -> str:
    """One path per line: a regenerated snapshot diffs by representer."""
    lines = [
        "{",
        f'"format": {snapshot["format"]},',
        f'"pinned": {json.dumps(snapshot["pinned"])},',
        f'"link_object_members": {json.dumps(snapshot["link_object_members"])},',
        f'"value_members": {json.dumps(snapshot["value_members"])},',
        '"paths": {',
    ]
    items = [f"{json.dumps(path)}: {json.dumps(value, sort_keys=True)}" for path, value in snapshot["paths"].items()]
    lines.append(",\n".join(items))
    lines += ["}", "}", ""]
    return "\n".join(lines)


def moves_and_disappearances(snapshot: dict) -> tuple[list[str], list[str]]:
    """A basename that continues at another path, and a representer that is gone in the newest pinned version."""
    pins = list(snapshot["pinned"])
    spans = {
        path: expand_ranges(value["versions"], pins) for path, value in snapshot["paths"].items() if "#" not in path
    }
    by_name: dict[str, list[str]] = {}
    for path in spans:
        by_name.setdefault(PurePosixPath(path).name, []).append(path)
    moved = [
        f"{old} -> {new}"
        for paths in by_name.values()
        for old in paths
        for new in paths
        if old != new
        and spans[old][-1] != pins[-1]
        and pins.index(spans[old][-1]) < pins.index(spans[new][0])
        and not set(spans[old]) & set(spans[new])
    ]
    gone = sorted(path for path, span in spans.items() if span[-1] != pins[-1])
    return moved, gone


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate representer_fields.json")
    mode.add_argument("--check", action="store_true", help="regenerate and diff against the committed file")
    args = parser.parse_args()

    pins = pinned_versions()
    try:
        require_checkouts(pins, SOURCES)
        snapshot = build()
    except MissingCheckoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    moved, gone = moves_and_disappearances(snapshot)
    for line in moved:
        print(f"moved: {line}")
    for path in gone:
        print(f"gone after {snapshot['paths'][path]['versions'].split(',')[-1].split('-')[-1]}: {path}")

    text = dumps(snapshot)
    if args.write:
        SNAPSHOT.write_text(text)
        print(f"wrote {SNAPSHOT.name}: {len(snapshot['paths'])} representer paths")
        return 0
    if not SNAPSHOT.is_file():
        print(f"error: {SNAPSHOT.name} does not exist; run --write", file=sys.stderr)
        return 1
    committed = json.loads(SNAPSHOT.read_text())
    if committed == snapshot:
        print(f"{SNAPSHOT.name} is current: {len(snapshot['paths'])} representer paths")
        return 0
    changed = sorted(
        path
        for path in set(committed["paths"]) | set(snapshot["paths"])
        if committed["paths"].get(path) != snapshot["paths"].get(path)
    )
    print(
        f"error: {SNAPSHOT.name} differs from the sources in {len(changed)} paths (first: {changed[:5]}); run --write",
        file=sys.stderr,
    )
    if committed.get("pinned") != snapshot["pinned"]:
        print("error: the pinned versions or tags differ from the snapshot header", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
