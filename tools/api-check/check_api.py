#!/usr/bin/env python3
"""Check the API assumptions this MCP client makes against the OpenProject source.

The client hardcodes endpoint paths, response fields and query-filter keys. When
OpenProject renames or removes one across versions, the client breaks silently
(this is exactly how the first semantic-identifier resolver regressed: it relied
on the ``subject_or_id`` filter, which does not match the project-based
``displayId`` form). This tool verifies, offline, that every symbol the client
depends on still exists in the source of each target version.

Scope and limits
----------------
This is an *existence / symbol* check, not a semantic proof. It catches
"field/filter/path renamed or removed between versions"; it does NOT catch
"same symbol, subtly different behaviour" — that is what the Docker runtime
tests in ``docker/test/`` are for.

Sources come from ``tools/api-check/fetch-sources.sh`` (gitignored clones under
``.op-sources/<version>/``). Run that first.

Usage:
    python tools/api-check/check_api.py             # curated symbol presence
    python tools/api-check/check_api.py --all       # every resource + filter used
    python tools/api-check/check_api.py --constants # hardcoded enum/constant VALUES
    python tools/api-check/check_api.py --verbose   # also list every OK entry
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / ".op-sources"


def _version_key(v: str) -> tuple[int, ...]:
    """Sort/compare key for a version label like "16.6" (16.6 < 17.0 < 17.5)."""
    try:
        return tuple(int(part) for part in v.split("."))
    except ValueError:
        return (9999,)


def _discover_versions() -> list[str]:
    """All cloned versions under .op-sources/, sorted numerically (16.0 < 17.5)."""
    if not SOURCES.exists():
        return []
    versions = [p.name for p in SOURCES.iterdir() if p.is_dir()]
    return sorted(versions, key=_version_key)


VERSIONS = _discover_versions()


@dataclass(frozen=True)
class Assumption:
    """One API symbol the client depends on.

    ``pattern`` is a fixed string grepped (literally) under ``subtree``.

    Expected presence per version is the allowlist of known, intentional version
    differences, expressed two ways:
    - ``present_from``: the symbol was introduced in this version; expected
      absent in every earlier version, present from this one on (e.g. "17.4").
    - ``expect``: explicit per-version overrides (rarely needed).
    A version covered by neither defaults to present.
    """

    symbol: str
    kind: str  # "path" | "field" | "filter"
    pattern: str
    subtree: str = "lib/api/v3"
    present_from: str | None = None
    expect: dict[str, bool] = field(default_factory=dict)

    def expected_present(self, version: str) -> bool:
        if version in self.expect:
            return self.expect[version]
        if self.present_from is not None:
            return _version_key(version) >= _version_key(self.present_from)
        return True


# Curated assumptions. Extend this list as the client grows; it is deliberately
# manual — auto-extracting every path from client.py produces false positives
# (f-string fragments, dynamic segments) that are noisier than they are worth.
# Endpoint paths are all declared in the v3 path helper, which is the robust
# source of truth (individual *_api.rb layouts vary). Filters and fields live in
# their own files.
_PATH_HELPER = "lib/api/v3/utilities/path_helper.rb"
_WP_FILTERS = "app/models/queries/work_packages/filter"

ASSUMPTIONS: list[Assumption] = [
    # --- Endpoint paths the client builds (checked against the path helper) ---
    Assumption("work_packages endpoint", "path", "work_packages", subtree=_PATH_HELPER),
    Assumption("projects endpoint", "path", "projects", subtree=_PATH_HELPER),
    Assumption("relations endpoint", "path", "relations", subtree=_PATH_HELPER),
    Assumption("time_entries endpoint", "path", "time_entries", subtree=_PATH_HELPER),
    Assumption("memberships endpoint", "path", "memberships", subtree=_PATH_HELPER),
    Assumption("versions endpoint", "path", "versions", subtree=_PATH_HELPER),
    Assumption("statuses endpoint", "path", "status", subtree=_PATH_HELPER),
    # --- Work-package response fields the resolver / writes depend on ---
    Assumption(
        "displayId field", "field", "displayId", subtree="lib/api/v3/work_packages", present_from="17.4"
    ),  # introduced in 17.4
    # Source uses the Ruby property name (snake_case); the representer renders it
    # as "lockVersion" in JSON.
    Assumption("lockVersion field", "field", "lock_version", subtree="lib/api/v3/work_packages"),
    Assumption(
        "semantic identifier model", "field", "semantic_id?", subtree="app/models/work_package", present_from="17.4"
    ),  # model lands in 17.4; setting activates it in 17.5
    # --- Query filters the client builds ---
    # Present in both lines. Note: this filter matches subject text and the
    # numeric id, NOT the project-based displayId — which is why resolving a
    # semantic reference via this filter fails (see _resolve_work_package_id).
    Assumption("subject_or_id filter", "filter", "subject_or_id_filter.rb", subtree=_WP_FILTERS),
    Assumption("status_id filter", "filter", "status_filter.rb", subtree=_WP_FILTERS),
    Assumption(
        "involved (relations) filter", "filter", "involved_filter.rb", subtree="app/models/queries/relations/filters"
    ),
    # --- Endpoints/operators behind the CE coverage-expansion tools. Each has a
    # different minimum version, recorded so the matrix flags a tool used on too
    # old an instance. (time-entry start/end lives in the costs module, which is
    # not in the sparse checkout, so it is verified at runtime instead.)
    Assumption("emoji_reactions endpoint", "path", "emoji_reactions", subtree="lib/api/v3", present_from="16.1"),
    Assumption("reminders endpoint", "path", "reminders", subtree="lib/api/v3"),  # present since 16.0
    Assumption("favorites endpoint", "path", "favorites", subtree="lib/api/v3", present_from="16.5"),
    Assumption(
        "version open status operator",
        "filter",
        "open_status.rb",
        subtree="app/models/queries/operators/versions",
        present_from="16.4",
    ),
]


def _present(version: str, asm: Assumption) -> bool:
    """True if the symbol's pattern is found anywhere under its subtree."""
    base = SOURCES / version / asm.subtree
    if not base.exists():
        # Subtree missing entirely also counts as "not present".
        return False
    # Literal, recursive, filename+content search. -r covers content; the
    # filename-style patterns (``*_api.rb``) are matched by also grepping the
    # file list, so we use a combined approach: ripgrep-free, plain grep.
    try:
        # Content match.
        content = (
            subprocess.run(
                ["grep", "-rqF", "--", asm.pattern, str(base)],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        if content:
            return True
        # Filename match (for *_api.rb / directory-name patterns).
        names = subprocess.run(
            ["find", str(base), "-name", f"*{asm.pattern}*"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        return bool(names)
    except FileNotFoundError as exc:  # grep/find missing
        print(f"error: required tool not found: {exc}", file=sys.stderr)
        raise


# --- Constant / enum checks (values, not just symbol presence) ---
#
# The assumptions above verify a symbol EXISTS. These verify that a hardcoded set
# of VALUES in the client still matches the source — an enum value or payload key
# that OpenProject renames would pass the existence check yet break at runtime.
# Each constant names the client's expected set and a regex that extracts the
# source's set from one file; the client set must be a subset of the source set.
# Only versions whose source file exists are checked (these models arrived at
# different releases), so missing files are reported as "n/a", not a failure.

CLIENT_PY = ROOT / "src" / "openproject_ce_mcp" / "client.py"


@dataclass(frozen=True)
class Constant:
    name: str
    client_values: frozenset[str]
    source_file: str  # path under .op-sources/<version>/
    source_regex: str  # each match group(1) is one source value


CONSTANTS: list[Constant] = [
    Constant(
        "emoji reactions",
        frozenset(
            {
                "thumbs_up",
                "thumbs_down",
                "grinning_face_with_smiling_eyes",
                "confused_face",
                "heart",
                "party_popper",
                "rocket",
                "eyes",
            }
        ),
        "app/models/emoji_reaction.rb",
        # EMOJI_MAP entries: `    thumbs_up: "..."`
        r"^\s+([a-z_]+):\s*\"",
    ),
    Constant(
        "version statuses",
        frozenset({"open", "closed", "locked"}),
        "app/models/version.rb",
        # VERSION_STATUSES = %w(open locked closed)
        r"VERSION_STATUSES\s*=\s*%w\(([^)]*)\)",  # special-cased: split group on spaces
    ),
    Constant(
        "version status operators",
        frozenset({"o", "c", "l"}),
        "app/models/queries/operators/versions",  # directory
        r'set_symbol\s+"([a-z])"',
    ),
]


def _extract_source_values(version: str, const: Constant) -> set[str] | None:
    """Return the set of values found in the source, or None if the file is absent."""
    target = SOURCES / version / const.source_file
    if not target.exists():
        return None
    texts: list[str] = []
    if target.is_dir():
        for f in sorted(target.rglob("*.rb")):
            texts.append(f.read_text(encoding="utf-8", errors="replace"))
    else:
        texts.append(target.read_text(encoding="utf-8", errors="replace"))
    values: set[str] = set()
    rx = re.compile(const.source_regex, re.MULTILINE)
    for text in texts:
        for m in rx.finditer(text):
            captured = m.group(1)
            # %w(...) style: one match holds a space-separated list.
            if " " in captured:
                values.update(captured.split())
            else:
                values.add(captured)
    return values


def run_constants(verbose: bool = False) -> int:
    header = f"{'constant':<28} " + " ".join(f"{v:<8}" for v in VERSIONS) + " verdict"
    print(header)
    print("-" * len(header))
    failures: list[str] = []
    for const in CONSTANTS:
        cells = []
        verdict = "ok"
        for v in VERSIONS:
            source_values = _extract_source_values(v, const)
            if source_values is None:
                cells.append(f"{'(n/a)':<8}")
                continue
            missing = const.client_values - source_values
            if not missing:
                cells.append(f"{'match':<8}")
            else:
                cells.append(f"{'DRIFT!':<8}")
                verdict = "DRIFT"
                failures.append(f"{const.name}: {v} — client values not in source: {sorted(missing)}")
        if verdict != "ok" or verbose:
            print(f"{const.name:<28} " + " ".join(cells) + f" {verdict}")

    print()
    if failures:
        print(f"FAIL: {len(failures)} constant drift(s):")
        for fmsg in failures:
            print(f"  - {fmsg}")
        return 1
    print(
        f"OK: all {len(CONSTANTS)} hardcoded constant sets are a subset of the "
        f"source across the versions that define them."
    )
    return 0


# --- Full auto-extracted coverage (every resource + filter the client uses) ---

CLIENT = ROOT / "src" / "openproject_ce_mcp" / "client.py"

# Resources whose v3 API lives in a separate module engine (modules/<x>/), which
# the sparse source checkout does not include. They exist in CE but cannot be
# source-verified here, so they are reported as "module" rather than missing.
MODULE_RESOURCES = {
    "grids": "my_page",
    "documents": "documents",
    "file_links": "storages",
    "job_statuses": "job_statuses",
    "sprints": "backlogs",
    "time_entries": "costs",
}
# Path-helper / directory names that differ from the client's path segment.
RESOURCE_ALIASES = {"statuses": "status", "my_preferences": "user_preferences"}
# Client path segments that are not standalone API resources (skip them).
RESOURCE_SKIP = {"api", "v3"}

# Client filter keys whose source filter file is named differently, and keys
# that are query parameters rather than registered filters (skip those).
FILTER_ALIASES = {
    "status_id": "status",
    "project_id": "project",
    "assignee": "assigned_to",
    "assigned_to_id": "assigned_to",
    "priority_id": "priority",
    "type_id": "type",
    "version_id": "version",
}
FILTER_SKIP = {"date", "scope", "context"}  # query params / matchers, not filter files


def _extract_client_resources() -> set[str]:
    text = CLIENT.read_text()
    used: set[str] = set()
    for m in re.findall(r'self\._(?:get|post|patch|delete)\(\s*f?"([^"]+)"', text):
        seg = re.sub(r"\{[^}]*\}", "", m.lstrip("/")).split("/")[0]
        if re.fullmatch(r"[a-z_]+", seg) and seg not in RESOURCE_SKIP:
            used.add(seg)
    for m in re.findall(r'_api_href\(f?"([a-z_]+)', text):
        used.add(m)
    return used


def _extract_client_filters() -> set[str]:
    text = CLIENT.read_text()
    keys = set(re.findall(r'\{"([a-z_]+)":\s*\{"operator"', text))
    return keys - FILTER_SKIP


def _resource_present(version: str, resource: str) -> bool:
    """Robust presence check: directory, path-helper entry, or *_api.rb file."""
    api = SOURCES / version / "lib" / "api" / "v3"
    if not api.exists():
        return False
    name = RESOURCE_ALIASES.get(resource, resource)
    if (api / name).is_dir():
        return True
    helper = api / "utilities" / "path_helper.rb"
    if helper.exists():
        hit = (
            subprocess.run(["grep", "-qE", rf"\b{name}\b", str(helper)], capture_output=True, check=False).returncode
            == 0
        )
        if hit:
            return True
    found = subprocess.run(
        ["find", str(api), "-name", f"*{name}*"], capture_output=True, text=True, check=False
    ).stdout.strip()
    return bool(found)


def _filter_present(version: str, filter_key: str) -> bool:
    qroot = SOURCES / version / "app" / "models" / "queries"
    if not qroot.exists():
        return False
    name = FILTER_ALIASES.get(filter_key, filter_key)
    # Filters are <name>_filter.rb files (allow plural dir layouts).
    found = subprocess.run(
        ["find", str(qroot), "-name", f"{name}_filter.rb"], capture_output=True, text=True, check=False
    ).stdout.strip()
    return bool(found)


def run_full_coverage() -> int:
    resources = sorted(_extract_client_resources())
    filters = sorted(_extract_client_filters())
    rows: list[tuple[str, str, list[str]]] = []
    introduced_late: list[str] = []

    for r in resources:
        if r in MODULE_RESOURCES:
            rows.append((r, "resource", ["module"] * len(VERSIONS)))
            continue
        cells = ["yes" if _resource_present(v, r) else "—" for v in VERSIONS]
        rows.append((r, "resource", cells))
        if cells[0] == "—" and "yes" in cells:
            introduced_late.append(f"{r} (from {VERSIONS[cells.index('yes')]})")
    for f in filters:
        cells = ["yes" if _filter_present(v, f) else "—" for v in VERSIONS]
        rows.append((f, "filter", cells))
        if cells[0] == "—" and "yes" in cells:
            introduced_late.append(f"{f} filter (from {VERSIONS[cells.index('yes')]})")

    header = f"{'access':<28} {'kind':<9} " + " ".join(f"{v:<6}" for v in VERSIONS)
    print(header)
    print("-" * len(header))
    for name, kind, cells in rows:
        print(f"{name:<28} {kind:<9} " + " ".join(f"{c:<6}" for c in cells))

    print()
    module_only = [n for n, k, c in rows if c and c[0] == "module"]
    print(f"{len(resources)} resources + {len(filters)} filters checked across {VERSIONS[0]}..{VERSIONS[-1]}.")
    if module_only:
        print(f"module-only (not source-verifiable, CE): {', '.join(module_only)}")
    if introduced_late:
        print("introduced after 16.0 (a tool using these needs a newer server):")
        for x in introduced_late:
            print(f"  - {x}")
    else:
        print("All source-verifiable accesses exist back to 16.0.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="list every checked symbol, not just mismatches")
    parser.add_argument(
        "--all", action="store_true", help="auto-extract and map EVERY resource + filter the client uses"
    )
    parser.add_argument(
        "--constants", action="store_true", help="verify hardcoded enum/constant VALUES against the source"
    )
    args = parser.parse_args()

    missing_sources = [v for v in VERSIONS if not (SOURCES / v).exists()]
    if missing_sources:
        print(f"error: missing source clones for {missing_sources}.", file=sys.stderr)
        print("Run: tools/api-check/fetch-sources.sh", file=sys.stderr)
        return 2

    if args.constants:
        return run_constants(verbose=args.verbose)
    if args.all:
        return run_full_coverage()

    header = f"{'symbol':<32} {'kind':<8} " + " ".join(f"{v:<8}" for v in VERSIONS) + " verdict"
    print(header)
    print("-" * len(header))

    unexpected: list[str] = []
    for asm in ASSUMPTIONS:
        cells = []
        verdict = "ok"
        for v in VERSIONS:
            present = _present(v, asm)
            expected = asm.expected_present(v)
            if present == expected:
                mark = "yes" if present else "(n/a)"
            else:
                mark = "PRESENT!" if present else "MISSING!"
                verdict = "UNEXPECTED"
                unexpected.append(
                    f"{asm.symbol}: {v} expected {'present' if expected else 'absent'} "
                    f"but was {'present' if present else 'absent'}"
                )
            cells.append(f"{mark:<8}")
        if verdict != "ok" or args.verbose:
            print(f"{asm.symbol:<32} {asm.kind:<8} " + " ".join(cells) + f" {verdict}")

    print()
    if unexpected:
        print(f"FAIL: {len(unexpected)} unexpected API difference(s):")
        for u in unexpected:
            print(f"  - {u}")
        print("\nIf a difference is intentional, update the `expect` field of the assumption in check_api.py.")
        return 1

    print(f"OK: all {len(ASSUMPTIONS)} API assumptions match the expected presence across {', '.join(VERSIONS)}.")
    print("Note: this is a symbol-existence check, not a behaviour proof — see docker/test/ for runtime verification.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
