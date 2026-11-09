"""The distribution is built with a pinned, hash-checked build backend, never with one resolved from PyPI at build time."""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
WORKFLOWS = ROOT / ".github" / "workflows"
BUILD_FLAGS = ("--build-constraints", "--require-hashes")
EXPORT = "uv export --project tools/build --locked --no-emit-project"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_lines(path: Path) -> list[str]:
    return [line for line in _text(path).splitlines() if not line.lstrip().startswith("#")]


def _function(name: str) -> str:
    """The code lines of a shell function of dev, comments dropped, continuation lines joined."""
    body = _text(DEV).split(f"\n{name}() {{\n", 1)[1].split("\n}\n", 1)[0]
    code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    return re.sub(r"\\\n\s*", " ", code)


def _build_job() -> str:
    return _text(WORKFLOWS / "test.yml").split("\n  build:\n", 1)[1].split("\n  install-smoke:\n", 1)[0]


def _uv_pin(block: str) -> str:
    match = re.search(
        r'astral-sh/setup-uv@[0-9a-f]{40}[^\n]*\n\s+with:\n(?:\s+#[^\n]*\n)*\s+version: "(\d+\.\d+\.\d+)"', block
    )
    assert match, "no pinned setup-uv version"
    return match.group(1)


def test_no_workflow_runs_uv_build_directly() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        assert [line for line in _code_lines(path) if re.search(r"\buv build\b", line)] == [], path.name


def test_every_uv_build_of_dev_sits_in_dist_or_dist_check_and_carries_the_hash_flags() -> None:
    dev_builds = [line for line in _code_lines(DEV) if re.search(r"\buv build\b", line)]
    assert len(dev_builds) == 2

    for name in ("dist", "dist_check"):
        function = _function(name)
        builds = [command for command in re.split(r"\n", function) if "uv build" in command]
        assert len(builds) == 1, name
        for flag in BUILD_FLAGS:
            assert flag in builds[0], f"{name}: {flag}"


@pytest.mark.parametrize("name", ["dist", "dist_check"])
def test_the_constraints_come_from_the_locked_build_project(name: str) -> None:
    function = _function(name)

    assert EXPORT in function
    assert "--format requirements-txt" in function


def test_the_constraints_file_is_generated_never_committed() -> None:
    assert not list(ROOT.glob("**/build-constraints*.txt"))
    assert "trap 'rm -f \"$constraints\"' EXIT" in _function("dist")


def test_dist_check_removes_exactly_one_pin_and_demands_the_hash_failure() -> None:
    function = _function("dist_check")

    assert "pluggy" in function and "without-pluggy.txt" in function
    assert "pinned upfront with" in function and "no trusted hash was provided for" in function
    assert "succeeded; hash checking of build requirements is not enforced" in function


def test_the_build_job_builds_twice_through_dev_with_the_digests_and_the_check_in_between() -> None:
    build = _build_job()
    first = build.index("run: ./dev dist\n")
    digests = build.index("id: digests")
    check = build.index("run: ./dev dist-check")
    second = build.index("run: ./dev dist --out-dir dist2")
    compare = build.index("- name: Verify the two builds are byte-identical")

    assert first < digests < second < check < compare
    assert build.count("./dev dist\n") == 1


def test_the_build_and_publish_jobs_pin_the_same_uv() -> None:
    publish = (
        _text(WORKFLOWS / "publish.yml").split("\n  publish:\n", 1)[1].split("\n  prepare-homebrew-formula:\n", 1)[0]
    )

    assert _uv_pin(_build_job()) == _uv_pin(publish)


def test_the_build_lock_names_the_backend_and_hashes_every_package() -> None:
    lock = tomllib.loads(_text(ROOT / "tools" / "build" / "uv.lock"))
    packages = {package["name"]: package for package in lock["package"]}

    assert "hatchling" in packages
    for name, package in packages.items():
        if package["source"] == {"virtual": "."}:
            continue
        assert package["source"] == {"registry": "https://pypi.org/simple"}, name
        files = [*package.get("wheels", []), *([package["sdist"]] if "sdist" in package else [])]
        assert files and all(file["hash"].startswith("sha256:") for file in files), name


def test_the_build_project_is_a_lock_source_only_and_mirrors_the_build_requirement() -> None:
    build = tomllib.loads(_text(ROOT / "tools" / "build" / "pyproject.toml"))
    root = tomllib.loads(_text(ROOT / "pyproject.toml"))

    assert build["tool"]["uv"]["package"] is False
    assert "build-system" not in build
    assert build["project"]["dependencies"] == root["build-system"]["requires"]


def test_dependabot_and_the_dependency_snapshot_cover_the_build_lock() -> None:
    blocks = _text(ROOT / ".github" / "dependabot.yml").split("\n  - package-ecosystem: ")[1:]

    assert any(block.startswith("uv\n") and "directory: /tools/build" in block for block in blocks)
    assert "      - tools/build/uv.lock\n" in _text(WORKFLOWS / "dependency-graph.yml")


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_the_build_project_is_not_hidden_by_the_ignore_rule_for_build_output() -> None:
    for path in ("tools/build/pyproject.toml", "tools/build/uv.lock"):
        result = subprocess.run(["git", "check-ignore", "--quiet", path], cwd=ROOT, check=False)

        # 0 means ignored, 1 means not ignored, anything else is git failing (for example 128), which proves nothing.
        assert result.returncode == 1, (
            f"{path}: git check-ignore returned {result.returncode}; the file must not be ignored"
        )
