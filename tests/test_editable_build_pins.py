"""The project's own editable install is built with the locked, hashed backend, never with one resolved from PyPI."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
WORKFLOWS = ROOT / ".github" / "workflows"
FLAG = "--no-build-isolation-package openproject-ce-mcp"
SCANNED_DIRECTORIES = (".github", "docker", "docs", "scripts", "tools")
SCANNED_FILES = ("dev", "README.md", "CONTRIBUTING.md", "configure_mcp.py")
SCANNED_SUFFIXES = {".md", ".py", ".sh", ".yml", ".yaml"}
SKIPPED = ("tools/semgrep/",)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _scanned_files() -> list[Path]:
    files = [ROOT / name for name in SCANNED_FILES]
    for directory in SCANNED_DIRECTORIES:
        base = ROOT / directory
        if base.is_dir():
            files += [path for path in sorted(base.rglob("*")) if path.is_file() and path.suffix in SCANNED_SUFFIXES]
    return [
        path
        for path in files
        if not {"__pycache__", ".venv"} & set(path.parts)
        and not any(path.relative_to(ROOT).as_posix().startswith(s) for s in SKIPPED)
    ]


def _commands_of(text: str) -> list[str]:
    """The lines of a text that are not shell or YAML comments, continuation lines joined."""
    joined = re.sub(r"\\\n\s*", " ", text)
    return [line.strip() for line in joined.splitlines() if not line.lstrip().startswith("#")]


def _commands(path: Path) -> list[str]:
    return _commands_of(_text(path))


def _function(name: str) -> str:
    body = _text(DEV).split(f"\n{name}() {{\n", 1)[1].split("\n}\n", 1)[0]
    return "\n".join(_commands_of(body))


def _job(name: str) -> str:
    """A job of test.yml: from its key to the next blank line followed by a two-space-indented key or comment."""
    text = _text(WORKFLOWS / "test.yml")
    return re.split(r"\n\n  (?=[#a-z])", text.split(f"\n  {name}:\n", 1)[1], maxsplit=1)[0]


def _hatchling_version(lock: Path) -> str:
    packages = tomllib.loads(_text(lock))["package"]
    (version,) = [package["version"] for package in packages if package["name"] == "hatchling"]
    return version


def test_the_build_group_mirrors_the_build_requirement_and_is_not_a_default_group() -> None:
    pyproject = tomllib.loads(_text(ROOT / "pyproject.toml"))

    assert pyproject["dependency-groups"]["build"] == pyproject["build-system"]["requires"]
    assert "build" not in pyproject.get("tool", {}).get("uv", {}).get("default-groups", [])


def test_the_main_lock_pins_and_hashes_the_backend_of_the_build_group() -> None:
    lock = tomllib.loads(_text(ROOT / "uv.lock"))
    (root,) = [package for package in lock["package"] if package["source"] == {"editable": "."}]
    (hatchling,) = [package for package in lock["package"] if package["name"] == "hatchling"]

    assert root["dev-dependencies"]["build"] == [{"name": "hatchling"}]
    assert hatchling["source"] == {"registry": "https://pypi.org/simple"}
    assert hatchling["wheels"] and all(entry["hash"].startswith("sha256:") for entry in hatchling["wheels"])
    assert hatchling["sdist"]["hash"].startswith("sha256:")


def test_both_locks_name_the_same_backend_version() -> None:
    assert _hatchling_version(ROOT / "uv.lock") == _hatchling_version(ROOT / "tools" / "build" / "uv.lock"), (
        "bump hatchling in both locks: `uv lock --upgrade-package hatchling` and "
        "`uv lock --upgrade-package hatchling --project tools/build`"
    )


def test_every_uv_sync_builds_the_project_without_isolation_and_only_dev_and_the_workflows_run_it() -> None:
    for path in _scanned_files():
        syncs = [line for line in _commands(path) if re.search(r"\buv sync\b", line)]
        if path == DEV or path.parent == WORKFLOWS:
            assert all(FLAG in line for line in syncs), (path.name, syncs)
        else:
            assert syncs == [], f"{path.relative_to(ROOT)} names a bare `uv sync`; it says `./dev bootstrap` instead"


def test_sync_project_locks_installs_the_build_group_and_passes_its_arguments_on() -> None:
    syncs = [line for line in _function("sync_project").splitlines() if "uv sync" in line]

    assert len(syncs) == 1
    for part in ("--locked", "--dev", "--group build", FLAG, '"$@"'):
        assert part in syncs[0], part
    assert 'bootstrap() {\n    sync_project "$@"\n}' in _text(DEV)


@pytest.mark.parametrize("name", ["lint", "test_", "sbom"])
def test_every_gate_command_that_runs_the_project_syncs_it_first(name: str) -> None:
    assert _function(name).startswith("sync_project --quiet")


def test_the_license_gate_syncs_through_the_helper() -> None:
    assert "sync_project --all-extras --all-groups" in _function("licenses")


def test_editable_check_demands_that_the_isolation_flag_without_the_group_fails() -> None:
    check = _function("editable_check")
    syncs = [line for line in check.splitlines() if "uv sync" in line]

    assert len(syncs) == 1
    assert FLAG in syncs[0] and "--group build" not in syncs[0]
    assert "--reinstall-package openproject-ce-mcp" in syncs[0]
    assert "if uv sync" in check
    assert "ModuleNotFoundError: No module named 'hatchling'" in check
    assert re.search(r"build\(\) \{[^}]*\n    editable_check\n", _text(DEV))
    assert "editable-check) editable_check ;;" in _text(DEV)


def test_every_uv_run_of_the_project_skips_the_sync_that_would_build_it_isolated() -> None:
    for path in _scanned_files():
        runs = [line for line in _commands(path) if re.search(r"\buv run\b", line)]
        for line in runs:
            assert "--no-sync" in line or "--project tools/lint" in line, f"{path.relative_to(ROOT)}: {line}"


def test_isolation_is_never_switched_off_for_every_package() -> None:
    for path in _scanned_files():
        for line in _commands(path):
            assert "UV_NO_BUILD_ISOLATION" not in line, f"{path.relative_to(ROOT)}: {line}"
            assert not re.search(r"--no-build-isolation(?!-package)", line), f"{path.relative_to(ROOT)}: {line}"


def test_the_newest_deps_job_re_resolves_but_still_builds_with_the_group() -> None:
    syncs = [line for line in _commands(WORKFLOWS / "test.yml") if "uv sync" in line]

    assert len(syncs) == 1
    assert "--upgrade" in syncs[0] and "--group build" in syncs[0] and FLAG in syncs[0]
    assert "--locked" not in syncs[0]


def test_the_lowest_deps_job_installs_the_hashed_backend_before_the_editable_install() -> None:
    commands = _commands_of(_job("test-lowest-deps"))
    export = next(i for i, line in enumerate(commands) if "uv export" in line)
    backend = next(i for i, line in enumerate(commands) if "--require-hashes" in line)
    editable = next(i for i, line in enumerate(commands) if "--editable" in line)

    assert "--only-group build" in commands[export] and "--frozen" in commands[export]
    assert "-r " in commands[backend]
    assert export < backend < editable
    assert FLAG in commands[editable]


def test_the_contributor_documentation_has_no_pip_editable_install() -> None:
    for path in [ROOT / "CONTRIBUTING.md", ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        assert not re.search(r"pip install (-e|--editable)", _text(path)), path.name
