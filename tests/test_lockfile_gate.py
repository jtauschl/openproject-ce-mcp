from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
BASH = shutil.which("bash")


@pytest.fixture
def recorded_uv(tmp_path: Path) -> Path:
    """A `uv` that records its arguments and the UV_LOCKED it was started with, then succeeds."""
    log = tmp_path / "uv.log"
    stub = tmp_path / "bin" / "uv"
    stub.parent.mkdir()
    stub.write_text(f'#!/bin/sh\necho "UV_LOCKED=${{UV_LOCKED:-unset}} $*" >> "{log}"\n', encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return log


def _run_dev(recorded_uv: Path, *args: str) -> list[str]:
    assert BASH is not None
    env = {**os.environ, "PATH": f"{recorded_uv.parent / 'bin'}{os.pathsep}{os.environ['PATH']}"}
    env.pop("UV_LOCKED", None)
    subprocess.run([BASH, str(ROOT / "dev"), *args], cwd=ROOT, env=env, check=True, capture_output=True)
    return recorded_uv.read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_bootstrap_installs_from_the_lockfile(recorded_uv: Path) -> None:
    assert _run_dev(recorded_uv, "bootstrap") == [
        "UV_LOCKED=1 sync --locked --dev --group build --no-build-isolation-package openproject-ce-mcp"
    ]


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_every_uv_command_of_the_gate_fails_on_a_stale_lockfile(recorded_uv: Path) -> None:
    calls = _run_dev(recorded_uv, "test")

    assert calls
    assert all(call.startswith("UV_LOCKED=1 ") for call in calls), calls


def test_a_workflow_install_of_the_project_uses_the_lockfile_unless_it_re_resolves_on_purpose() -> None:
    lines = [line.strip() for line in WORKFLOW.read_text(encoding="utf-8").splitlines()]
    syncs = [line for line in lines if re.search(r"\buv sync\b", line) and not line.startswith("#")]
    through_dev = [line for line in lines if line == "run: ./dev bootstrap"]

    # The one install that does not use the lock re-resolves on purpose; every other job goes through ./dev, which locks.
    assert len(syncs) == 1
    assert "--upgrade" in syncs[0]
    assert len(through_dev) == 3
