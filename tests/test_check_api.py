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
    # not the real op-sources checkout — _resource_present/_filter_present are
    # monkeypatched per test instead of hitting the filesystem.
    monkeypatch.setattr(check_api, "VERSIONS", ["16.0", "17.0", "17.6"])


def test_run_full_coverage_fails_when_resource_missing_at_latest_version(monkeypatch, capsys):
    # Present at 16.0/17.0, absent only at the latest version (17.6): this
    # case never triggers the (unrelated) introduced_late reporting, so the
    # FAIL result must not be accompanied by the misleading "All
    # source-verifiable accesses exist back to 16.0." success line.
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


def test_versions_are_exactly_the_pinned_ones():
    # Discovering versions from the directories present would let a missing or
    # stray checkout silently change what gets audited.
    import op_sources

    assert check_api.PINS == op_sources.pinned_versions()


def test_main_fails_when_a_pinned_checkout_is_unusable(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_api.py"])

    def unusable(pins, sources):
        raise check_api.MissingCheckoutError("17.9: missing checkout")

    monkeypatch.setattr(check_api, "require_checkouts", unusable)

    assert check_api.main() == 2
    assert "17.9: missing checkout" in capsys.readouterr().err


# --- client extraction against the real source --------------------------


def _literal_filter_keys_in_src() -> set[str]:
    """Every literal key of a `{"<key>": {"operator": ...}}` dict in the scanned client code."""
    import ast

    keys: set[str] = set()
    files = [check_api.CLIENT, *check_api.APP_ADAPTERS.glob("*.py"), *check_api.APP_SERVICES.glob("*.py")]
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=True):
                is_filter = isinstance(value, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == "operator" for k in value.keys
                )
                if is_filter and isinstance(key, ast.Constant):
                    keys.add(key.value)
    return keys


def test_filter_extraction_sees_every_literal_filter_key_the_client_sends():
    # --all audits only what this regex extraction finds; a filter built in a
    # shape it misses would silently drop out of the audit (readIAN once did).
    assert _literal_filter_keys_in_src() - check_api.FILTER_SKIP <= check_api._extract_client_filters()


def test_resource_extraction_finds_the_core_endpoints_the_client_calls():
    resources = check_api._extract_client_resources()
    assert {"work_packages", "projects", "versions", "time_entries", "notifications", "meetings"} <= resources


def test_camel_case_filter_key_resolves_to_the_snake_case_filter_file(tmp_path, monkeypatch):
    monkeypatch.setattr(check_api, "SOURCES", tmp_path)
    filters = tmp_path / "17.9" / "app" / "models" / "queries" / "notifications" / "filters"
    filters.mkdir(parents=True)
    (filters / "read_ian_filter.rb").write_text("")

    assert check_api._filter_present("17.9", "readIAN")


# --- curated mode -----------------------------------------------------------


def _curated_tree(tmp_path, *, present_in: tuple[str, ...]) -> None:
    for version in ("16.0", "17.0"):
        api = tmp_path / version / "lib" / "api" / "v3"
        api.mkdir(parents=True)
        (api / "representer.rb").write_text("property :displayId\n" if version in present_in else "property :id\n")


def _run_curated(monkeypatch, capsys, tmp_path) -> tuple[int, str]:
    monkeypatch.setattr(check_api, "SOURCES", tmp_path)
    monkeypatch.setattr(check_api, "VERSIONS", ["16.0", "17.0"])
    monkeypatch.setattr(check_api, "require_checkouts", lambda pins, sources: None)
    monkeypatch.setattr(
        check_api,
        "ASSUMPTIONS",
        [check_api.Assumption("displayId field", "field", ":displayId", present_from="17.0")],
    )
    monkeypatch.setattr(sys, "argv", ["check_api.py"])
    code = check_api.main()
    return code, capsys.readouterr().out


def test_curated_mode_passes_when_presence_matches_the_expected_version_range(tmp_path, monkeypatch, capsys):
    _curated_tree(tmp_path, present_in=("17.0",))
    code, out = _run_curated(monkeypatch, capsys, tmp_path)
    assert code == 0
    assert "OK: all 1 API assumptions match" in out


def test_curated_mode_fails_and_names_the_symbol_on_an_unexpected_difference(tmp_path, monkeypatch, capsys):
    _curated_tree(tmp_path, present_in=())
    code, out = _run_curated(monkeypatch, capsys, tmp_path)
    assert code == 1
    assert "displayId field: 17.0 expected present but was absent" in out


# --- constants mode ---------------------------------------------------------


def _run_constants(tmp_path, monkeypatch, capsys, *, source: str | None) -> tuple[int, str]:
    monkeypatch.setattr(check_api, "SOURCES", tmp_path)
    monkeypatch.setattr(check_api, "VERSIONS", ["17.0"])
    if source is not None:
        model = tmp_path / "17.0" / "app" / "models"
        model.mkdir(parents=True)
        (model / "version.rb").write_text(source)
    monkeypatch.setattr(
        check_api,
        "CONSTANTS",
        [
            check_api.Constant(
                "version statuses",
                frozenset({"open", "closed", "locked"}),
                "app/models/version.rb",
                r"VERSION_STATUSES\s*=\s*%w\(([^)]*)\)",
            )
        ],
    )
    code = check_api.run_constants()
    return code, capsys.readouterr().out


def test_constants_pass_when_the_client_set_is_a_subset_of_the_source(tmp_path, monkeypatch, capsys):
    code, out = _run_constants(tmp_path, monkeypatch, capsys, source="VERSION_STATUSES = %w(open locked closed)\n")
    assert code == 0
    assert "OK: all 1 hardcoded constant sets" in out


def test_constants_fail_and_name_the_value_the_source_no_longer_has(tmp_path, monkeypatch, capsys):
    code, out = _run_constants(tmp_path, monkeypatch, capsys, source="VERSION_STATUSES = %w(open closed)\n")
    assert code == 1
    assert "version statuses: 17.0 — client values not in source: ['locked']" in out


def test_constants_skip_a_version_that_does_not_define_the_constant(tmp_path, monkeypatch, capsys):
    code, out = _run_constants(tmp_path, monkeypatch, capsys, source=None)
    assert code == 0


def test_full_coverage_reports_a_resource_introduced_after_the_first_version(monkeypatch, capsys):
    monkeypatch.setattr(check_api, "_extract_client_resources", lambda: {"meetings"})
    monkeypatch.setattr(check_api, "_extract_client_filters", lambda: set())
    monkeypatch.setattr(check_api, "_resource_present", lambda version, resource: version != "16.0")

    assert check_api.run_full_coverage() == 0
    assert "meetings (from 17.0)" in capsys.readouterr().out


# --- resource presence ------------------------------------------------------


def test_resource_present_finds_module_resources_and_path_helper_entries(tmp_path, monkeypatch):
    # Module resources live under modules/<name>/lib/api/v3; missing them once
    # produced a false 12-resource regression report.
    monkeypatch.setattr(check_api, "SOURCES", tmp_path)
    core = tmp_path / "17.9" / "lib" / "api" / "v3"
    (core / "work_packages").mkdir(parents=True)
    (core / "utilities").mkdir()
    (core / "utilities" / "path_helper.rb").write_text("index :render_markdown\nindex :user_preferences\n")
    (tmp_path / "17.9" / "modules" / "meeting" / "lib" / "api" / "v3" / "meetings").mkdir(parents=True)

    assert check_api._resource_present("17.9", "work_packages")
    assert check_api._resource_present("17.9", "meetings")
    assert check_api._resource_present("17.9", "my_preferences")
    assert not check_api._resource_present("17.9", "portfolios")
    assert not check_api._resource_present("16.0", "work_packages")


def test_explicit_version_override_wins_over_the_introduction_version():
    assumption = check_api.Assumption("x", "field", "x", present_from="17.0", expect={"17.2": False})

    assert [assumption.expected_present(v) for v in ("16.6", "17.0", "17.2", "17.3")] == [False, True, False, True]
    assert check_api.Assumption("y", "field", "y").expected_present("16.0")


def test_filename_search_matches_names_never_paths(tmp_path):
    # Like find -name: a "/" or a leading ":" in a symbol is part of a name, not path syntax.
    (tmp_path / "work_packages").mkdir()
    (tmp_path / "work_packages" / "schema_api.rb").write_text("")

    assert check_api._find_any(tmp_path, "*schema_api*")
    assert check_api._find_any(tmp_path, "work_packages")
    assert not check_api._find_any(tmp_path, "*work_packages/schema*")
    assert not check_api._find_any(tmp_path, "*:displayId*")
