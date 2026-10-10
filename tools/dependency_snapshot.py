"""Turn uv.lock into a snapshot for GitHub's dependency submission API.

Dependabot alerts are computed from the dependency graph, and GitHub's own graph
job for uv.lock is not reliably triggered by pushes, so CI submits the lock itself.

Only what `pip install openproject-ce-mcp` installs is runtime. The extras and
dependency groups in DEVELOPMENT_EXTRAS and DEVELOPMENT_GROUPS are development;
any other one stops the script, so a new extra gets classified on purpose.
Markers are ignored: the lock is cross-platform, and a dependency installed only
on Windows or an older Python still ships to those users.

Reads uv.lock from the working directory and the standard GitHub Actions
variables; prints the snapshot as one line of JSON.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomllib

LOCK_FILE = "uv.lock"
LOCK_FORMAT_VERSION = 1
PYPI = {"registry": "https://pypi.org/simple"}
CORRELATOR = "openproject-ce-mcp uv.lock"
DETECTOR_NAME = "openproject-ce-mcp dependency_snapshot"
DETECTOR_VERSION = "1"
DEVELOPMENT_EXTRAS = frozenset({"dev", "measure"})
DEVELOPMENT_GROUPS = frozenset({"dev"})
ENVIRONMENT = ("GITHUB_SHA", "GITHUB_REF", "GITHUB_RUN_ID", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY")

Node = tuple[str, str]


class SnapshotError(Exception):
    pass


class _Lock:
    def __init__(self, text: str) -> None:
        data = tomllib.loads(text)
        if data.get("version") != LOCK_FORMAT_VERSION:
            raise SnapshotError(f"unsupported uv.lock format version {data.get('version')!r}")
        packages: list[dict[str, Any]] = data["package"]
        roots = [package for package in packages if package["source"] == {"editable": "."}]
        if len(roots) != 1:
            raise SnapshotError(f"expected one editable root package, found {len(roots)}")
        self.root = roots[0]
        self.packages: dict[Node, dict[str, Any]] = {}
        for package in packages:
            if package is self.root:
                continue
            if package["source"] != PYPI:
                raise SnapshotError(f"{package['name']} {package['version']}: unsupported source {package['source']}")
            self.packages[(package["name"], package["version"])] = package

    def resolve(self, entry: Mapping[str, Any]) -> Node:
        name = entry["name"]
        candidates = [node for node in self.packages if node[0] == name]
        if "version" in entry:
            candidates = [node for node in candidates if node[1] == entry["version"]]
        if len(candidates) != 1:
            label = f"{name} {entry['version']}" if "version" in entry else name
            raise SnapshotError(f"dependency {label} matches {len(candidates)} packages")
        return candidates[0]

    def dependencies(self, node: Node) -> list[dict[str, Any]]:
        return list(self.packages[node].get("dependencies", []))

    def extra_dependencies(self, node: Node, extra: str) -> list[dict[str, Any]]:
        optional = self.packages[node].get("optional-dependencies", {})
        if extra not in optional:
            raise SnapshotError(f"{node[0]} {node[1]} has no extra {extra!r}")
        return list(optional[extra])


def _walk(lock: _Lock, entries: Iterable[Mapping[str, Any]]) -> dict[Node, set[str]]:
    """Every node reachable from `entries`, with the extras requested of it.

    Extras belong to the edge, not the node: a node first reached plain and
    later as `node[extra]` must still be expanded for that extra.
    """
    reached: dict[Node, set[str]] = {}
    pending = [(lock.resolve(entry), set(entry.get("extra", []))) for entry in entries]
    while pending:
        node, extras = pending.pop()
        expand: list[dict[str, Any]] = []
        if node not in reached:
            reached[node] = set()
            expand.extend(lock.dependencies(node))
        for extra in sorted(extras - reached[node]):
            expand.extend(lock.extra_dependencies(node, extra))
        reached[node] |= extras
        pending.extend((lock.resolve(entry), set(entry.get("extra", []))) for entry in expand)
    return reached


def _purl(node: Node) -> str:
    return f"pkg:pypi/{node[0]}@{node[1]}"


def resolved_dependencies(lock_text: str) -> dict[str, dict[str, Any]]:
    lock = _Lock(lock_text)
    root = lock.root
    unknown_extras = set(root.get("optional-dependencies", {})) - DEVELOPMENT_EXTRAS
    if unknown_extras:
        raise SnapshotError(f"unclassified extra(s) {sorted(unknown_extras)}")
    unknown_groups = set(root.get("dev-dependencies", {})) - DEVELOPMENT_GROUPS
    if unknown_groups:
        raise SnapshotError(f"unclassified dependency group(s) {sorted(unknown_groups)}")

    runtime_entries = root.get("dependencies", [])
    development_entries = [
        entry
        for section in ("optional-dependencies", "dev-dependencies")
        for entries in root.get(section, {}).values()
        for entry in entries
    ]
    runtime = _walk(lock, runtime_entries)
    development = _walk(lock, development_entries)
    direct = {lock.resolve(entry) for entry in [*runtime_entries, *development_entries]}

    resolved: dict[str, dict[str, Any]] = {}
    for node in sorted(runtime.keys() | development.keys()):
        extras = runtime.get(node, set()) | development.get(node, set())
        entries = lock.dependencies(node) + [
            entry for extra in sorted(extras) for entry in lock.extra_dependencies(node, extra)
        ]
        children = {lock.resolve(entry) for entry in entries}
        resolved[_purl(node)] = {
            "package_url": _purl(node),
            "relationship": "direct" if node in direct else "indirect",
            "scope": "runtime" if node in runtime else "development",
            "dependencies": sorted(_purl(child) for child in children),
        }
    return resolved


def snapshot(lock_text: str, environ: Mapping[str, str], scanned: datetime) -> dict[str, Any]:
    missing = [name for name in ENVIRONMENT if not environ.get(name)]
    if missing:
        raise SnapshotError(f"missing environment variable(s) {', '.join(missing)}")
    repository_url = f"{environ['GITHUB_SERVER_URL']}/{environ['GITHUB_REPOSITORY']}"
    return {
        "version": 0,
        "job": {
            "correlator": CORRELATOR,
            "id": environ["GITHUB_RUN_ID"],
            "html_url": f"{repository_url}/actions/runs/{environ['GITHUB_RUN_ID']}",
        },
        "sha": environ["GITHUB_SHA"],
        "ref": environ["GITHUB_REF"],
        "detector": {
            "name": DETECTOR_NAME,
            "version": DETECTOR_VERSION,
            "url": f"{repository_url}/blob/{environ['GITHUB_SHA']}/tools/dependency_snapshot.py",
        },
        "scanned": scanned.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifests": {
            LOCK_FILE: {
                "name": LOCK_FILE,
                "file": {"source_location": LOCK_FILE},
                "resolved": resolved_dependencies(lock_text),
            }
        },
    }


def main() -> None:
    try:
        document = snapshot(Path(LOCK_FILE).read_text(encoding="utf-8"), os.environ, datetime.now(timezone.utc))
    except SnapshotError as error:
        sys.exit(f"dependency_snapshot: {error}")
    print(json.dumps(document, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
