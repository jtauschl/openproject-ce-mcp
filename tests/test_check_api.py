from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_CHECK_API_PATH = Path(__file__).resolve().parents[1] / "tools" / "api-check" / "check_api.py"
_spec = importlib.util.spec_from_file_location("check_api", _CHECK_API_PATH)
check_api = importlib.util.module_from_spec(_spec)
sys.modules["check_api"] = check_api
_spec.loader.exec_module(check_api)


@pytest.fixture(autouse=True)
def _stub_versions(monkeypatch):
    # These tests exercise run_full_coverage()'s pass/fail logic in isolation,
    # not the real .op-sources checkout — _resource_present/_filter_present are
    # monkeypatched per test instead of hitting the filesystem.
    monkeypatch.setattr(check_api, "VERSIONS", ["16.0", "17.0", "17.6"])


def test_run_full_coverage_fails_when_resource_missing_at_latest_version(monkeypatch, capsys):
    # Present at 16.0/17.0, absent only at the latest version (17.6) -- this is
    # the case that previously printed the misleading "All source-verifiable
    # accesses exist back to 16.0." success line right above a FAIL result,
    # since it never triggers the (unrelated) introduced_late reporting.
    monkeypatch.setattr(check_api, "_extract_client_resources", lambda: {"widgets"})
    monkeypatch.setattr(check_api, "_extract_client_filters", lambda: set())
    monkeypatch.setattr(check_api, "_resource_present", lambda version, resource: version != "17.6")

    exit_code = check_api.run_full_coverage()
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "widgets" in out
    assert "FAIL" in out
    assert "All source-verifiable accesses exist back to 16.0." not in out


def test_run_full_coverage_fails_when_filter_missing_at_latest_version(monkeypatch, capsys):
    monkeypatch.setattr(check_api, "_extract_client_resources", lambda: set())
    monkeypatch.setattr(check_api, "_extract_client_filters", lambda: {"gizmo_id"})
    monkeypatch.setattr(check_api, "_filter_present", lambda version, filter_key: version != "17.6")

    exit_code = check_api.run_full_coverage()
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "gizmo_id" in out
    assert "FAIL" in out
    assert "All source-verifiable accesses exist back to 16.0." not in out


def test_run_full_coverage_passes_when_absence_is_historical_only(monkeypatch):
    # Absent at 16.0, present from 17.0 on -> present at the latest version, so
    # this is the legitimate "introduced later" case, not a failure.
    monkeypatch.setattr(check_api, "_extract_client_resources", lambda: {"newish"})
    monkeypatch.setattr(check_api, "_extract_client_filters", lambda: set())
    monkeypatch.setattr(check_api, "_resource_present", lambda version, resource: version != "16.0")

    assert check_api.run_full_coverage() == 0


def test_run_full_coverage_never_probes_module_resources(monkeypatch):
    known_module_resource = next(iter(check_api.MODULE_RESOURCES))
    monkeypatch.setattr(check_api, "_extract_client_resources", lambda: {known_module_resource})
    monkeypatch.setattr(check_api, "_extract_client_filters", lambda: set())

    def _fail_if_called(version, resource):
        raise AssertionError("module resources must not be probed via _resource_present")

    monkeypatch.setattr(check_api, "_resource_present", _fail_if_called)

    assert check_api.run_full_coverage() == 0
