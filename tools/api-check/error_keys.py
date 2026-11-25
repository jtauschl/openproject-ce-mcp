#!/usr/bin/env python3
"""The attributes a rejected write can name, read from the pinned OpenProject sources.

OpenProject answers a rejected write with errors that carry the API attribute they are about
(`_embedded.details.attribute`). The server builds that name from the model's error attribute with
`PropertyNameConverter.from_ar_name`. The client judges an error by it (`app/policies/error_fields.py`), so the
set of attributes per entity has to be known per pinned version: this tool lists, per entity and version, every
attribute a contract, model or service of the entity can add (`errors.add :x`, `validates :x`, `attribute :x`),
converted the way the server converts it, and the message templates that interpolate a value (`%{...}`), and
compares them with a committed snapshot (`error_keys.json`).

    python tools/api-check/error_keys.py --check   # exit 1 when the snapshot is stale
    python tools/api-check/error_keys.py --write   # rewrite the snapshot after fetch-sources.sh

Stated boundary: the keys come from the Ruby sources by pattern, not by running them. `errors.add` with a computed
name (a variable) is listed under `unparsed` with its file and line, and each entity's count is waived in the test
that reads this snapshot, with a reason; a model column that needs `db/schema` to know is not found here. The
message templates read are the `activerecord.errors.models` ones; a generic message that gets its value at the call
site (`errors.add :x, :taken, date: ...`) is not found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import op_sources  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parent / "error_keys.json"

# entity -> the source locations (globs under a checkout) whose errors reach that entity's write forms.
ENTITY_SOURCES: dict[str, tuple[str, ...]] = {
    "work_package": (
        "app/contracts/work_packages/**/*.rb",
        "app/models/work_package.rb",
        "app/models/work_packages/**/*.rb",
        "app/services/work_packages/**/*.rb",
    ),
    "project": (
        "app/contracts/projects/**/*.rb",
        "app/models/project.rb",
        "app/services/projects/**/*.rb",
    ),
    "user": ("app/contracts/users/**/*.rb", "app/models/user.rb", "app/services/users/**/*.rb"),
    "version": ("app/contracts/versions/**/*.rb", "app/models/version.rb", "app/services/versions/**/*.rb"),
    "membership": ("app/contracts/members/**/*.rb", "app/models/member.rb", "app/services/members/**/*.rb"),
    "time_entry": (
        "modules/costs/app/contracts/time_entries/**/*.rb",
        "app/contracts/time_entries/**/*.rb",
        "app/models/time_entry.rb",
    ),
    "meeting": ("modules/meeting/app/contracts/meetings/**/*.rb", "modules/meeting/app/models/meeting.rb"),
    "grid": ("modules/grids/app/contracts/grids/**/*.rb", "modules/grids/app/models/grid.rb"),
    "board": ("app/contracts/queries/**/*.rb", "app/models/query.rb"),
    "relation": ("app/contracts/relations/**/*.rb", "app/models/relation.rb"),
}

_ADD = re.compile(r"errors\.add\(?\s*(?::(\w+)|\"(\w+)\"|(\w[\w.@]*))")
_ATTRIBUTE = re.compile(r"^\s*attribute\s+:(\w+)")
_VALIDATES = re.compile(r"^\s*validates(?:_\w+)?\s+((?::\w+\s*,\s*)*:\w+)")
_SYMBOL = re.compile(r":(\w+)")
_FOREIGN_KEY = re.compile(r"(.+)_id\Z")
_CUSTOM_FIELD = re.compile(r"\A(?:cf|custom_field)_(\d+)\Z")
_CONVERSIONS_BLOCK = re.compile(r"WELL_KNOWN_CONVERSIONS\s*=\s*\{(.*?)\}\.freeze", re.S)
_CONVERSION = re.compile(r"(\w+):\s*\"(\w+)\"")
_ACRONYM = re.compile(r"inflect\.acronym\s+\"(\w+)\"")
_TEMPLATE_VALUE = re.compile(r"%\{(\w+)\}")


def read_conversions(checkout: Path) -> dict[str, str]:
    path = checkout / "config/constants/ar_to_api_conversions.rb"
    block = _CONVERSIONS_BLOCK.search(path.read_text()) if path.is_file() else None
    return dict(_CONVERSION.findall(block.group(1))) if block else {}


def read_acronyms(checkout: Path) -> dict[str, str]:
    path = checkout / "config/initializers/inflections.rb"
    return {word.lower(): word for word in _ACRONYM.findall(path.read_text())} if path.is_file() else {}


def from_ar_name(attribute: str, *, conversions: dict[str, str], acronyms: dict[str, str]) -> str:
    """The API name of a model attribute: the Python port of `PropertyNameConverter.from_ar_name`."""
    name = _FOREIGN_KEY.sub(r"\1", attribute)
    name = _CUSTOM_FIELD.sub(r"customField\1", name)
    if name in conversions:
        return conversions[name]
    first, *rest = name.split("_")
    return first + "".join(acronyms.get(part, part.capitalize()) for part in rest)


def extract(text: str) -> tuple[set[str], list[int]]:
    """(attribute names a file adds errors for or declares, the lines of `errors.add` with a computed name)."""
    found: set[str] = set()
    computed: list[int] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for match in _ADD.finditer(line):
            symbol, string, other = match.groups()
            if symbol or string:
                found.add(symbol or string)
            else:
                computed.append(number)
        attribute = _ATTRIBUTE.match(line)
        if attribute:
            found.add(attribute.group(1))
        validates = _VALIDATES.match(line)
        if validates:
            found.update(_SYMBOL.findall(validates.group(1)))
    return found, computed


def locale_templates(checkout: Path) -> dict[str, list[str]]:
    """Message templates of `activerecord.errors.models.<model>.attributes.<attribute>.<key>` that interpolate a
    value other than a count, as `model.attribute.key` -> the placeholders. A small indent-based reader of the
    one YAML shape the file uses; it needs no YAML library."""
    path = checkout / "config/locales/en.yml"
    if not path.is_file():
        return {}
    found: dict[str, list[str]] = {}
    stack: list[tuple[int, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
        route = [name for _, name in stack]
        if route[:4] == ["en", "activerecord", "errors", "models"] and value.strip():
            placeholders = sorted(set(_TEMPLATE_VALUE.findall(value)) - {"count"})
            if placeholders:
                found[".".join(route[4:])] = placeholders
    return found


def read_tags(versions: list[str], sources: Path = op_sources.SOURCES) -> dict[str, str]:
    """The tag each checkout sits on: the snapshot records what it read, so a line whose pins differ from the
    checkouts' (the umbrella holds one `op-sources`) still compares like with like."""
    tags = {}
    for version in versions:
        tag = op_sources.checked_out_tag(sources / version)
        if tag is None:
            raise op_sources.MissingCheckoutError(f"{version}: no checkout at a tag under {sources}")
        tags[version] = tag
    return tags


def build(pins: dict[str, str], sources: Path = op_sources.SOURCES) -> dict:
    keys: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    unparsed: dict[str, dict[str, int]] = defaultdict(dict)
    templates: dict[str, set[str]] = defaultdict(set)
    for version in pins:
        checkout = sources / version
        conversions, acronyms = read_conversions(checkout), read_acronyms(checkout)
        for entity, patterns in ENTITY_SOURCES.items():
            names: set[str] = set()
            computed = 0
            for pattern in patterns:
                for path in sorted(checkout.glob(pattern)):
                    found, lines = extract(path.read_text())
                    names |= found
                    computed += len(lines)
            for name in names:
                keys[entity][from_ar_name(name, conversions=conversions, acronyms=acronyms)].add(version)
            unparsed[entity][version] = computed
        for template in locale_templates(checkout):
            templates[template].add(version)
    return {
        "pins": pins,
        "keys": {
            entity: {key: sorted(v, key=op_sources.version_key) for key, v in sorted(keys[entity].items())}
            for entity in ENTITY_SOURCES
        },
        "unparsed": {entity: unparsed[entity] for entity in ENTITY_SOURCES},
        "quoting_templates": {name: sorted(v, key=op_sources.version_key) for name, v in sorted(templates.items())},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    pins = read_tags(list(op_sources.pinned_versions()))
    snapshot = json.dumps(build(pins), indent=1, sort_keys=False) + "\n"
    if args.write:
        SNAPSHOT.write_text(snapshot)
        return 0
    if not SNAPSHOT.is_file() or SNAPSHOT.read_text() != snapshot:
        print("error_keys.json is stale: run tools/api-check/error_keys.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
