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
    python tools/api-check/check_api.py            # report + exit code
    python tools/api-check/check_api.py --verbose  # also list every OK symbol
"""

from __future__ import annotations

import argparse
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
    Assumption("displayId field", "field", "displayId",
               subtree="lib/api/v3/work_packages",
               present_from="17.4"),  # introduced in 17.4
    # Source uses the Ruby property name (snake_case); the representer renders it
    # as "lockVersion" in JSON.
    Assumption("lockVersion field", "field", "lock_version",
               subtree="lib/api/v3/work_packages"),
    Assumption("semantic identifier model", "field", "semantic_id?",
               subtree="app/models/work_package",
               present_from="17.4"),  # model lands in 17.4; setting activates it in 17.5
    # --- Query filters the client builds ---
    # Present in both lines. Note: this filter matches subject text and the
    # numeric id, NOT the project-based displayId — which is why resolving a
    # semantic reference via this filter fails (see _resolve_work_package_id).
    Assumption("subject_or_id filter", "filter", "subject_or_id_filter.rb",
               subtree=_WP_FILTERS),
    Assumption("status_id filter", "filter", "status_filter.rb", subtree=_WP_FILTERS),
    Assumption("involved (relations) filter", "filter", "involved_filter.rb",
               subtree="app/models/queries/relations/filters"),
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
        content = subprocess.run(
            ["grep", "-rqF", "--", asm.pattern, str(base)],
            capture_output=True, check=False,
        ).returncode == 0
        if content:
            return True
        # Filename match (for *_api.rb / directory-name patterns).
        names = subprocess.run(
            ["find", str(base), "-name", f"*{asm.pattern}*"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        return bool(names)
    except FileNotFoundError as exc:  # grep/find missing
        print(f"error: required tool not found: {exc}", file=sys.stderr)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true",
                        help="list every checked symbol, not just mismatches")
    args = parser.parse_args()

    missing_sources = [v for v in VERSIONS if not (SOURCES / v).exists()]
    if missing_sources:
        print(f"error: missing source clones for {missing_sources}.", file=sys.stderr)
        print("Run: tools/api-check/fetch-sources.sh", file=sys.stderr)
        return 2

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
        print("\nIf a difference is intentional, update the `expect` field of the "
              "assumption in check_api.py.")
        return 1

    print(f"OK: all {len(ASSUMPTIONS)} API assumptions match the expected "
          f"presence across {', '.join(VERSIONS)}.")
    print("Note: this is a symbol-existence check, not a behaviour proof — see "
          "docker/test/ for runtime verification.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
