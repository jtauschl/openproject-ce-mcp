from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("tomllib", reason="the script runs on the CI runner's Python 3.12; tomllib needs 3.11")
import tomllib  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_PATH = ROOT / "tools" / "dependency_snapshot.py"
_spec = importlib.util.spec_from_file_location("dependency_snapshot", _PATH)
assert _spec is not None and _spec.loader is not None
dependency_snapshot = importlib.util.module_from_spec(_spec)
sys.modules["dependency_snapshot"] = dependency_snapshot
_spec.loader.exec_module(dependency_snapshot)

ENVIRONMENT = {
    "GITHUB_SHA": "0123abc",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_RUN_ID": "42",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "owner/repo",
}
SCANNED = datetime(2026, 10, 10, 12, 30, 5, tzinfo=timezone.utc)
ROOT_PACKAGE = 'name = "app"\nversion = "1.0.0"\nsource = { editable = "." }\n'
PYPI = 'source = { registry = "https://pypi.org/simple" }\n'


def _lock(*packages: str, version: int = 1) -> str:
    return f"version = {version}\nrevision = 3\n" + "".join(f"\n[[package]]\n{package}" for package in packages)


def _package(name: str, version: str = "1.0.0", extra: str = "") -> str:
    return f'name = "{name}"\nversion = "{version}"\n{PYPI}{extra}'


def _names(purls: list[str]) -> set[str]:
    return {purl.removeprefix("pkg:pypi/").split("@")[0] for purl in purls}


@pytest.fixture(scope="module")
def real_lock() -> dict[str, Any]:
    return tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_resolved() -> dict[str, dict[str, Any]]:
    return dependency_snapshot.resolved_dependencies((ROOT / "uv.lock").read_text(encoding="utf-8"))


def _entry(resolved: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    (entry,) = [entry for purl, entry in resolved.items() if _names([purl]) == {name}]
    return entry


def test_every_locked_package_except_the_project_is_resolved(
    real_lock: dict[str, Any], real_resolved: dict[str, dict[str, Any]]
) -> None:
    locked = {
        f"pkg:pypi/{package['name']}@{package['version']}"
        for package in real_lock["package"]
        if package["source"] != {"editable": "."}
    }

    assert set(real_resolved) == locked


@pytest.mark.parametrize(
    ("name", "relationship", "scope"),
    [
        ("mcp", "direct", "runtime"),
        ("httpx", "direct", "runtime"),
        # Reachable only through the socks extra of httpx.
        ("socksio", "indirect", "runtime"),
        # trustme (development) needs it too; the runtime path wins.
        ("cryptography", "indirect", "runtime"),
        ("pytest", "direct", "development"),
        ("ruff", "direct", "development"),
        ("trustme", "direct", "development"),
        ("tiktoken", "direct", "development"),
        ("pluggy", "indirect", "development"),
    ],
)
def test_real_lock_classification(
    real_resolved: dict[str, dict[str, Any]], name: str, relationship: str, scope: str
) -> None:
    entry = _entry(real_resolved, name)

    assert (entry["relationship"], entry["scope"]) == (relationship, scope)


def test_real_lock_edges_list_every_child(real_lock: dict[str, Any], real_resolved: dict[str, dict[str, Any]]) -> None:
    versions: dict[str, list[str]] = {}
    for package in real_lock["package"]:
        versions.setdefault(package["name"], []).append(package["version"])

    def purls(entries: list[dict[str, Any]]) -> set[str]:
        return {f"pkg:pypi/{entry['name']}@{entry.get('version') or versions[entry['name']][0]}" for entry in entries}

    (mcp,) = [package for package in real_lock["package"] if package["name"] == "mcp"]
    (httpx,) = [package for package in real_lock["package"] if package["name"] == "httpx"]
    httpx_entries = httpx["dependencies"] + httpx["optional-dependencies"]["socks"]

    assert set(_entry(real_resolved, "mcp")["dependencies"]) == purls(mcp["dependencies"])
    assert set(_entry(real_resolved, "httpx")["dependencies"]) == purls(httpx_entries)
    assert "socksio" in _names(sorted(purls(httpx_entries)))


@pytest.mark.parametrize("root_order", [("plain", "extra"), ("extra", "plain")])
def test_extra_requested_after_a_plain_edge_is_still_expanded(root_order: tuple[str, str]) -> None:
    root_dependencies = ", ".join(f'{{ name = "{name}" }}' for name in root_order)
    lock = _lock(
        ROOT_PACKAGE + f"dependencies = [{root_dependencies}]\n",
        _package("plain", extra='dependencies = [{ name = "x" }]\n'),
        _package("extra", extra='dependencies = [{ name = "x", extra = ["e"] }]\n'),
        _package("x", extra='[package.optional-dependencies]\ne = [{ name = "y" }]\n'),
        _package("y"),
    )

    resolved = dependency_snapshot.resolved_dependencies(lock)

    assert "pkg:pypi/y@1.0.0" in resolved
    assert resolved["pkg:pypi/x@1.0.0"]["dependencies"] == ["pkg:pypi/y@1.0.0"]


def test_version_disambiguated_edges_and_directness_follow_the_resolved_package() -> None:
    lock = _lock(
        ROOT_PACKAGE + 'dependencies = [{ name = "p" }, { name = "t", version = "2.0.0" }]\n',
        _package("p", extra='dependencies = [{ name = "t", version = "1.0.0" }]\n'),
        _package("t", "1.0.0"),
        _package("t", "2.0.0"),
    )

    resolved = dependency_snapshot.resolved_dependencies(lock)

    assert resolved["pkg:pypi/p@1.0.0"]["dependencies"] == ["pkg:pypi/t@1.0.0"]
    assert resolved["pkg:pypi/t@2.0.0"]["relationship"] == "direct"
    assert resolved["pkg:pypi/t@1.0.0"]["relationship"] == "indirect"


def test_development_closure_excludes_runtime_packages() -> None:
    lock = _lock(
        ROOT_PACKAGE
        + 'dependencies = [{ name = "shared" }]\n\n[package.dev-dependencies]\ndev = [{ name = "tool" }]\n',
        _package("shared"),
        _package("tool", extra='dependencies = [{ name = "shared" }]\n'),
    )

    resolved = dependency_snapshot.resolved_dependencies(lock)

    assert resolved["pkg:pypi/shared@1.0.0"]["scope"] == "runtime"
    assert resolved["pkg:pypi/tool@1.0.0"]["scope"] == "development"


@pytest.mark.parametrize(
    ("lock", "message"),
    [
        (_lock(ROOT_PACKAGE, version=2), "unsupported uv.lock format version 2"),
        (_lock(_package("lonely")), "expected one editable root package, found 0"),
        (
            _lock(ROOT_PACKAGE, 'name = "g"\nversion = "1.0.0"\nsource = { git = "https://example.com/g" }\n'),
            "g 1.0.0: unsupported source",
        ),
        (_lock(ROOT_PACKAGE + 'dependencies = [{ name = "missing" }]\n'), "dependency missing matches 0 packages"),
        (
            _lock(ROOT_PACKAGE + 'dependencies = [{ name = "t" }]\n', _package("t", "1.0.0"), _package("t", "2.0.0")),
            "dependency t matches 2 packages",
        ),
        (
            _lock(ROOT_PACKAGE + 'dependencies = [{ name = "x", extra = ["nope"] }]\n', _package("x")),
            "x 1.0.0 has no extra 'nope'",
        ),
        (
            _lock(ROOT_PACKAGE + '\n[package.optional-dependencies]\nserver = [{ name = "x" }]\n', _package("x")),
            "unclassified extra(s) ['server']",
        ),
        (
            _lock(ROOT_PACKAGE + '\n[package.dev-dependencies]\nlint = [{ name = "x" }]\n', _package("x")),
            "unclassified dependency group(s) ['lint']",
        ),
    ],
)
def test_unsupported_locks_fail_with_the_reason(lock: str, message: str) -> None:
    with pytest.raises(dependency_snapshot.SnapshotError) as raised:
        dependency_snapshot.resolved_dependencies(lock)

    assert message in str(raised.value)


def test_snapshot_envelope() -> None:
    lock = _lock(ROOT_PACKAGE + 'dependencies = [{ name = "x" }]\n', _package("x"))

    document = dependency_snapshot.snapshot(lock, ENVIRONMENT, SCANNED)

    assert document == {
        "version": 0,
        "job": {
            "correlator": "openproject-ce-mcp uv.lock",
            "id": "42",
            "html_url": "https://github.com/owner/repo/actions/runs/42",
        },
        "sha": "0123abc",
        "ref": "refs/heads/main",
        "detector": {
            "name": "openproject-ce-mcp dependency_snapshot",
            "version": "1",
            "url": "https://github.com/owner/repo/blob/0123abc/tools/dependency_snapshot.py",
        },
        "scanned": "2026-10-10T12:30:05Z",
        "manifests": {
            "uv.lock": {
                "name": "uv.lock",
                "file": {"source_location": "uv.lock"},
                "resolved": {
                    "pkg:pypi/x@1.0.0": {
                        "package_url": "pkg:pypi/x@1.0.0",
                        "relationship": "direct",
                        "scope": "runtime",
                        "dependencies": [],
                    }
                },
            }
        },
    }


def test_snapshot_names_missing_environment_variables() -> None:
    environ = {key: value for key, value in ENVIRONMENT.items() if key not in {"GITHUB_SHA", "GITHUB_RUN_ID"}}

    with pytest.raises(dependency_snapshot.SnapshotError, match="GITHUB_SHA, GITHUB_RUN_ID"):
        dependency_snapshot.snapshot(_lock(ROOT_PACKAGE), environ, SCANNED)


def test_main_reads_the_lock_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "uv.lock").write_text(_lock(ROOT_PACKAGE + 'dependencies = [{ name = "x" }]\n', _package("x")))
    monkeypatch.chdir(tmp_path)
    for key, value in ENVIRONMENT.items():
        monkeypatch.setenv(key, value)

    dependency_snapshot.main()

    output = capsys.readouterr().out
    assert output.count("\n") == 1
    assert list(json.loads(output)["manifests"]["uv.lock"]["resolved"]) == ["pkg:pypi/x@1.0.0"]


def test_main_exits_with_the_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "uv.lock").write_text(_lock(ROOT_PACKAGE, version=2))
    monkeypatch.chdir(tmp_path)
    for key, value in ENVIRONMENT.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(SystemExit) as raised:
        dependency_snapshot.main()

    assert raised.value.code == "dependency_snapshot: unsupported uv.lock format version 2"
