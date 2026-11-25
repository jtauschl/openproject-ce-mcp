"""The semgrep gate bounds every rule on every file with a timeout of its own, never with the default of the tool.

`--strict` makes every warning-level scan failure fatal, and a rule timeout is one: a scan that left a rule unrun on
a file is refused. The default bound of 5 seconds per rule and file is a wall-clock bound, so a loaded machine turns
a correct commit into a refusal of the pre-push gate. The command line therefore carries an explicit `--timeout`
inside the bounds written here: the floor is three times the slowest rule and file measured under an artificial load
of 56 busy processes on 14 cores (9.5 s), the cap keeps one hanging file at three timeouts (`--timeout-threshold`
stays at its default of 3) of two minutes each.

Stated boundary: the test reads the text of `dev` and of the `*.yml` workflow files and composite actions (a `.yaml`
file is not seen); a semgrep call written in another file, or composed from variables, is not seen. `SEMGREP_TIMEOUT` of a developer's environment is
overridden by the explicit flag and needs no check.
"""

from __future__ import annotations

import re

from test_build_pins import DEV, _code_lines, _function, _uv_pin_files

TIMEOUT_FLOOR = 30
TIMEOUT_CAP = 120


def _semgrep_command() -> str:
    commands = [line for line in _function("semgrep").splitlines() if re.search(r"\bsemgrep scan\b", line)]
    assert len(commands) == 1, commands
    return commands[0]


def test_the_semgrep_command_line_carries_an_explicit_timeout_inside_the_bounds() -> None:
    command = _semgrep_command()
    matches = re.findall(r"--timeout\s+(\d+)\b", command)

    assert len(matches) == 1 and len(re.findall(r"--timeout\b(?!-)", command)) == 1, command
    assert TIMEOUT_FLOOR <= int(matches[0]) <= TIMEOUT_CAP


def test_the_semgrep_command_line_keeps_the_coverage_guarantee_and_the_default_threshold() -> None:
    command = _semgrep_command()

    assert "--strict" in command and "--error" in command
    assert "--timeout-threshold" not in command


def test_the_workflows_run_the_gate_through_dev_and_nowhere_else() -> None:
    runs: list[tuple[str, str]] = []
    for path in _uv_pin_files():
        for line in _code_lines(path):
            if "semgrep" not in line or re.match(r"\s*-?\s*name:", line):
                continue
            runs.append((path.name, line.strip()))

    assert runs == [("test.yml", "run: ./dev semgrep")]


def test_dev_invokes_semgrep_in_one_place_only() -> None:
    scans = [
        line
        for line in _code_lines(DEV)
        if re.search(r"\b(lint_tool|uvx)\s+semgrep\b|\buv run\b[^|;]*\bsemgrep\b", line)
    ]

    assert len(scans) == 1, scans
