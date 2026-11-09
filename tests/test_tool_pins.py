"""The lint and packaging tools run from a locked project and the semgrep rules from a pinned commit, never from a
run-time download without a pin."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
WORKFLOWS = ROOT / ".github" / "workflows"
LOCKED_TOOLS = ("bandit", "semgrep", "twine", "pip-licenses")
LINT_COMMAND = "uv run --project tools/lint --locked"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_lines(path: Path) -> list[str]:
    return [line for line in _text(path).splitlines() if not line.lstrip().startswith("#")]


@pytest.mark.parametrize("path", [DEV, WORKFLOWS / "test.yml", WORKFLOWS / "publish.yml"], ids=lambda p: p.name)
def test_no_tool_is_run_through_an_unpinned_uvx(path: Path) -> None:
    assert [line for line in _code_lines(path) if re.search(r"\buvx\b", line)] == []


def test_every_tool_runs_through_the_locked_tools_project() -> None:
    dev = _text(DEV)
    test_workflow = _text(WORKFLOWS / "test.yml")

    assert f'lint_tool() {{\n    {LINT_COMMAND} "$@"\n}}' in dev
    for call in ("lint_tool bandit ", "lint_tool semgrep scan ", "lint_tool twine check ", "lint_tool pip-licenses "):
        assert call in dev, call
    assert f"{LINT_COMMAND} bandit " in test_workflow
    assert f"{LINT_COMMAND} twine check " in test_workflow
    assert "twine" not in "\n".join(_code_lines(WORKFLOWS / "publish.yml"))
    assert "run: ./dev semgrep" in test_workflow


def test_every_call_into_the_tools_project_is_locked() -> None:
    for path in (DEV, WORKFLOWS / "test.yml", WORKFLOWS / "publish.yml"):
        for line in _code_lines(path):
            if "--project tools/lint" in line:
                assert "--locked" in line, f"{path.name}: {line.strip()}"


def test_the_tools_lock_names_every_tool_and_hashes_every_package() -> None:
    lock = tomllib.loads(_text(ROOT / "tools" / "lint" / "uv.lock"))
    packages = {package["name"]: package for package in lock["package"]}

    assert set(LOCKED_TOOLS) <= set(packages)
    for name, package in packages.items():
        if package["source"] == {"virtual": "."}:
            continue
        files = [*package.get("wheels", []), *([package["sdist"]] if "sdist" in package else [])]
        assert files, name
        assert all(file["hash"].startswith("sha256:") for file in files), name


def test_the_tools_project_is_never_built_or_published() -> None:
    project = tomllib.loads(_text(ROOT / "tools" / "lint" / "pyproject.toml"))

    assert project["tool"]["uv"]["package"] is False
    assert "build-system" not in project


def test_semgrep_runs_on_the_pinned_rules_with_metrics_off_and_never_on_auto() -> None:
    function = _text(DEV).split("\nsemgrep() {", 1)[1].split("\n}\n", 1)[0]

    assert 'tools/install-semgrep-rules.sh "$semgrep_rules_dir"' in function
    assert '--config "$semgrep_rules_dir"' in function
    assert "--metrics off" in function and "--error" in function and "--strict" in function
    for path in (DEV, WORKFLOWS / "test.yml", WORKFLOWS / "publish.yml"):
        assert "--config auto" not in "\n".join(_code_lines(path)), path.name


def test_the_rules_installer_pins_a_full_commit_and_is_linted() -> None:
    installer = _text(ROOT / "tools" / "install-semgrep-rules.sh")
    shell_scripts = _text(DEV).split("shell_scripts=(", 1)[1].split(")", 1)[0]

    assert re.search(r'^rules_sha="[0-9a-f]{40}"$', installer, re.MULTILINE)
    assert "tools/install-semgrep-rules.sh" in shell_scripts


def test_the_manifest_lists_only_sorted_unique_rule_files() -> None:
    lines = _text(ROOT / "tools" / "semgrep" / "rules.manifest").splitlines()

    assert lines and lines == sorted(set(lines))
    assert all(re.fullmatch(r"[A-Za-z0-9_./-]+\.ya?ml", line) for line in lines)
    assert not any(line.endswith((".test.yaml", ".test.yml", ".fixed.yaml", ".fixed.yml")) for line in lines)
    assert any(line.startswith("python/") for line in lines)
    assert any(line.startswith("generic/secrets/") for line in lines)


def test_dependabot_tracks_the_tools_project() -> None:
    blocks = _text(ROOT / ".github" / "dependabot.yml").split("\n  - package-ecosystem: ")[1:]

    assert any(block.startswith("uv\n") and "directory: /tools/lint" in block for block in blocks)


def test_the_dependency_snapshot_workflow_watches_the_tools_lock() -> None:
    assert "      - tools/lint/uv.lock\n" in _text(WORKFLOWS / "dependency-graph.yml")


def test_the_license_gate_still_inspects_the_environment_of_the_shipped_package() -> None:
    licenses = _text(DEV).split("\nlicenses() {", 1)[1].split("\n}\n", 1)[0]

    assert 'lint_tool pip-licenses --python "$licenses_dir/venv/bin/python3"' in licenses
