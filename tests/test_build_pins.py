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


def _setup_uv_versions(text: str) -> list[str | None]:
    """The `version:` input of every `astral-sh/setup-uv` step in a workflow or composite action, None where absent."""
    lines = text.splitlines()
    versions: list[str | None] = []
    for index, line in enumerate(lines):
        if "astral-sh/setup-uv@" not in line or line.lstrip().startswith("#"):
            continue
        dash = len(line) - len(line.lstrip())
        block = []
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= dash:
                break
            block.append(following)
        version = None
        in_with = False
        for entry in block:
            indent = len(entry) - len(entry.lstrip())
            if re.fullmatch(r"\s*with:\s*", entry) and indent == dash + 2:
                in_with = True
            elif entry.strip() and indent == dash + 2:
                in_with = False
            elif in_with and (m := re.fullmatch(rf"\s{{{dash + 4}}}version:\s*(.*)", entry)):
                version = m.group(1).strip()
        versions.append(version)
    return versions


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


def _uv_pin_files() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *(ROOT / ".github" / "actions").glob("**/*.yml")])


# The scope is the setup-uv steps of the workflows and composite actions: another uv installer (`pip install uv`,
# a download in a script) is not seen by this test.
def test_every_setup_uv_step_pins_the_same_exact_uv() -> None:
    found = {path.name: _setup_uv_versions(_text(path)) for path in _uv_pin_files()}
    versions = [version for steps in found.values() for version in steps]

    assert len(versions) >= 9, found
    assert all(version is not None and re.fullmatch(r'"\d+\.\d+\.\d+"', version) for version in versions), found
    assert len(set(versions)) == 1, found


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "      - uses: astral-sh/setup-uv@" + "0" * 40 + ' # v10\n        with:\n          version: "0.13.7"\n',
            ['"0.13.7"'],
        ),
        (
            "      - uses: astral-sh/setup-uv@"
            + "0" * 40
            + ' # v10\n        with:\n          python-version: "3.12"\n',
            [None],
        ),
        (
            "      - uses: astral-sh/setup-uv@"
            + "0" * 40
            + "\n        with:\n          # why\n          version: ${{ matrix.uv }}\n"
            "      - uses: actions/checkout@" + "1" * 40 + '\n        with:\n          version: "9.9.9"\n',
            ["${{ matrix.uv }}"],
        ),
        (
            "  - uses: astral-sh/setup-uv@" + "0" * 40 + '\n    with:\n      version: "0.13.7"\n',
            ['"0.13.7"'],
        ),
        ("      # - uses: astral-sh/setup-uv@" + "0" * 40 + "\n", []),
        (
            "      - uses: astral-sh/setup-uv@"
            + "0" * 40
            + '\n        env:\n          version: "0.13.7"\n        with:\n          python-version: "3.12"\n',
            [None],
        ),
    ],
)
def test_the_setup_uv_reader_finds_a_missing_a_matrix_valued_and_a_neighbouring_version(
    text: str, expected: list[str | None]
) -> None:
    assert _setup_uv_versions(text) == expected


def _test_linux_matrix(text: str) -> set[str]:
    job = text.split("\n  test-linux:\n", 1)[1].split("\n\n  ", 1)[0]
    match = re.search(r"python-version: \[([^\]]*)\]", job)
    assert match, "test-linux has no static python-version matrix"
    return {version.strip(" \"'") for version in match.group(1).split(",")}


def _python_classifiers(pyproject: str) -> set[str]:
    return set(re.findall(r'"Programming Language :: Python :: (3\.\d+)"', pyproject))


# Parity with the static test-linux matrix only: a Python test path outside it is not seen.
def test_the_python_classifiers_equal_the_test_linux_matrix() -> None:
    matrix = _test_linux_matrix(_text(WORKFLOWS / "test.yml"))

    assert matrix == _python_classifiers(_text(ROOT / "pyproject.toml"))
    assert {"3.11", "3.15"} <= matrix


def test_the_parity_test_sees_a_matrix_entry_without_a_classifier_and_the_reverse() -> None:
    workflow = _text(WORKFLOWS / "test.yml")
    pyproject = _text(ROOT / "pyproject.toml")

    assert _test_linux_matrix(workflow.replace('"3.15"]', '"3.15", "3.16"]', 1)) != _python_classifiers(pyproject)
    assert _test_linux_matrix(workflow) != _python_classifiers(
        pyproject.replace('  "Programming Language :: Python :: 3.15",\n', "")
    )


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


COOLDOWN_DAYS = 7


def _cooldowns(text: str) -> list[tuple[str, int | None, int | None]]:
    """Per Dependabot update block: the ecosystem, its default-days and its semver-major-days."""
    blocks = []
    for block in text.split("\n  - package-ecosystem: ")[1:]:
        default = re.search(r"\n      default-days: (\d+)\n", block)
        major = re.search(r"\n      semver-major-days: (\d+)\n", block)
        blocks.append(
            (
                block.split("\n", 1)[0],
                int(default.group(1)) if default else None,
                int(major.group(1)) if major else None,
            )
        )
    return blocks


def _cooldown_problems(text: str) -> list[str]:
    problems = []
    for ecosystem, default, major in _cooldowns(text):
        if default is None or default < COOLDOWN_DAYS:
            problems.append(f"{ecosystem}: default-days {default} is below {COOLDOWN_DAYS}")
        if ecosystem == "uv" and (major is None or default is None or major < default):
            problems.append(f"uv: semver-major-days {major} is missing or below default-days")
        if ecosystem != "uv" and major is not None:
            problems.append(f"{ecosystem}: no semver keys are supported")
    return problems


def test_every_dependabot_block_sets_a_cooldown_of_at_least_seven_days() -> None:
    text = _text(ROOT / ".github" / "dependabot.yml")

    assert len(_cooldowns(text)) >= 4
    assert _cooldown_problems(text) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("      default-days: 7\n", "      default-days: 3\n", "default-days 3 is below 7"),
        ("    cooldown:\n      default-days: 7\n", "", "default-days None is below 7"),
        ("      semver-major-days: 14\n", "", "semver-major-days None is missing"),
        ("      semver-major-days: 14\n", "      semver-major-days: 5\n", "semver-major-days 5 is missing or below"),
        (
            "    cooldown:\n      default-days: 7\n",
            "    cooldown:\n      default-days: 7\n      semver-major-days: 14\n",
            "no semver keys are supported",
        ),
    ],
)
def test_the_cooldown_check_sees_a_short_a_missing_and_a_misplaced_value(old: str, new: str, expected: str) -> None:
    text = _text(ROOT / ".github" / "dependabot.yml")
    assert old in text
    # The first match belongs to the github-actions block for the semver case and to the first block otherwise.
    mutated = text.replace(old, new, 1)

    assert any(expected in problem for problem in _cooldown_problems(mutated)), _cooldown_problems(mutated)


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_the_build_project_is_not_hidden_by_the_ignore_rule_for_build_output() -> None:
    for path in ("tools/build/pyproject.toml", "tools/build/uv.lock"):
        result = subprocess.run(["git", "check-ignore", "--quiet", path], cwd=ROOT, check=False)

        # 0 means ignored, 1 means not ignored, anything else is git failing (for example 128), which proves nothing.
        assert result.returncode == 1, (
            f"{path}: git check-ignore returned {result.returncode}; the file must not be ignored"
        )
