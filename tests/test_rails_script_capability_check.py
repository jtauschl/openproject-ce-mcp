"""Unit coverage for `_run_rails_script`'s `capability_check` wrapping/sentinel
logic in `tests/integration/conftest.py`.

The Rails process itself is integration-only (requires a real Docker
instance), but the string-wrapping and sentinel-detection logic added to
support version-gated Rails-runner callers (see RailsCapabilityUnavailable)
is pure Python and can be verified with a mocked `subprocess.run`, without
any live instance -- this file is a plain unit test, not marked integration.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "integration_conftest", Path(__file__).parent / "integration" / "conftest.py"
)
assert _spec is not None and _spec.loader is not None
integration_conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(integration_conftest)


def _fake_run(returncode: int, stdout: str, stderr: str = ""):
    def _run(cmd, *, input, cwd, capture_output, text, timeout):  # noqa: A002
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    return _run


def test_capability_check_none_runs_script_unchanged(monkeypatch):
    monkeypatch.setenv("OPENPROJECT_DOCKER_SERVICE", "op-test")
    captured: dict[str, str] = {}

    def _run(cmd, *, input, cwd, capture_output, text, timeout):  # noqa: A002
        captured["input"] = input
        return subprocess.CompletedProcess(cmd, 0, stdout="VALUE=true\n", stderr="")

    monkeypatch.setattr(integration_conftest.subprocess, "run", _run)

    result = integration_conftest._run_rails_script('puts "VALUE=true"', result_key="VALUE")

    assert result == "true"
    assert captured["input"] == 'puts "VALUE=true"'


def test_capability_check_sentinel_raises_unavailable(monkeypatch):
    monkeypatch.setenv("OPENPROJECT_DOCKER_SERVICE", "op-test")
    monkeypatch.setattr(
        integration_conftest.subprocess,
        "run",
        _fake_run(0, f"{integration_conftest._RAILS_CAPABILITY_UNAVAILABLE_SENTINEL}\n"),
    )

    with pytest.raises(integration_conftest.RailsCapabilityUnavailable):
        integration_conftest._run_rails_script(
            'puts "VALUE=true"',
            result_key="VALUE",
            capability_check="Setting.respond_to?(:some_setting=)",
        )


def test_capability_check_present_returns_normally(monkeypatch):
    monkeypatch.setenv("OPENPROJECT_DOCKER_SERVICE", "op-test")
    monkeypatch.setattr(integration_conftest.subprocess, "run", _fake_run(0, "VALUE=true\n"))

    result = integration_conftest._run_rails_script(
        'puts "VALUE=true"',
        result_key="VALUE",
        capability_check="Setting.respond_to?(:some_setting=)",
    )

    assert result == "true"


def test_nonzero_returncode_fails_even_with_capability_check(monkeypatch):
    monkeypatch.setenv("OPENPROJECT_DOCKER_SERVICE", "op-test")
    monkeypatch.setattr(integration_conftest.subprocess, "run", _fake_run(1, "", stderr="boom"))

    with pytest.raises(pytest.fail.Exception, match="boom"):
        integration_conftest._run_rails_script(
            'puts "VALUE=true"',
            result_key="VALUE",
            capability_check="Setting.respond_to?(:some_setting=)",
        )
