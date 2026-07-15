from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CHECK_COVERAGE_PATH = Path(__file__).resolve().parents[1] / "tools" / "api-check" / "check_coverage.py"
_spec = importlib.util.spec_from_file_location("check_coverage", _CHECK_COVERAGE_PATH)
check_coverage = importlib.util.module_from_spec(_spec)
sys.modules["check_coverage"] = check_coverage
_spec.loader.exec_module(check_coverage)


def test_resource_alias_is_recognized_as_covered(monkeypatch):
    # The client calls "my_preferences", not "user_preferences" (the source
    # directory name) -- without RESOURCE_ALIASES this under-reports the
    # resource as an unclassified/unused gap instead of "covered".
    monkeypatch.setattr(check_coverage, "_source_resources", lambda: ["user_preferences"])
    monkeypatch.setattr(check_coverage, "_client_resources", lambda: {"my_preferences"})
    monkeypatch.setattr(check_coverage, "_live_probe", lambda resources: {})

    rows, tally = check_coverage.build_matrix()

    assert rows == [("user_preferences", True, "—", "covered")]
    assert tally == {"covered": 1}


def test_unaliased_unused_resource_is_review_without_live_probe(monkeypatch):
    monkeypatch.setattr(check_coverage, "_source_resources", lambda: ["mystery_resource"])
    monkeypatch.setattr(check_coverage, "_client_resources", lambda: set())
    monkeypatch.setattr(check_coverage, "_live_probe", lambda resources: {})

    rows, _tally = check_coverage.build_matrix()

    assert rows == [("mystery_resource", False, "—", "review")]


def test_confirmed_gap_is_reported_without_needing_a_live_probe(monkeypatch):
    # CONFIRMED_GAPS encodes resources already verified (via a one-time live
    # probe) as real top-level CE endpoints the client doesn't cover yet --
    # this must hold on every subsequent deterministic, no-live-probe run.
    confirmed = next(iter(check_coverage.CONFIRMED_GAPS))
    monkeypatch.setattr(check_coverage, "_source_resources", lambda: [confirmed])
    monkeypatch.setattr(check_coverage, "_client_resources", lambda: set())
    monkeypatch.setattr(check_coverage, "_live_probe", lambda resources: {})

    rows, _tally = check_coverage.build_matrix()

    assert rows == [(confirmed, False, "—", "GAP (CE)")]


def test_gaps_section_warns_and_withholds_all_clear_when_resources_unclassified():
    rows = [
        ("widget", False, "—", "review"),
        ("gizmo", True, "—", "covered"),
    ]

    section = check_coverage.render_gaps_section(rows)

    assert "Coverage is not fully verified" in section
    assert "widget" in section
    assert "None — every plain top-level CE resource is covered." not in section


def test_gaps_section_gives_clean_all_clear_when_nothing_unclassified():
    rows = [
        ("gizmo", True, "—", "covered"),
        ("thingamajig", False, "—", "subresource"),
    ]

    section = check_coverage.render_gaps_section(rows)

    assert "Coverage is not fully verified" not in section
    assert "None — every plain top-level CE resource is covered." in section


def test_gaps_section_lists_real_gaps_even_when_nothing_unclassified():
    rows = [
        ("gizmo", True, "—", "covered"),
        ("widget", False, "—", "GAP (CE)"),
    ]

    section = check_coverage.render_gaps_section(rows)

    assert "Coverage is not fully verified" not in section
    assert "`widget`" in section
    assert "None — every plain top-level CE resource is covered." not in section


def test_gaps_section_lists_confirmed_gaps_alongside_unclassified_resources():
    # Both a confirmed gap and an unclassified resource can coexist: the
    # confirmed-gaps list must not silently drop into the "unclassified"
    # bucket, and vice versa.
    rows = [
        ("widget", False, "—", "GAP (CE)"),
        ("mystery", False, "—", "review"),
    ]

    section = check_coverage.render_gaps_section(rows)

    assert "Coverage is not fully verified" in section
    assert "`widget`" in section
    assert "`mystery`" in section


def test_coverage_body_includes_matrix_and_gaps_section():
    rows = [("gizmo", True, "—", "covered")]
    tally = {"covered": 1}

    body = check_coverage.render_coverage_body(rows, tally, live_enabled=False)

    assert "# OpenProject CE API coverage" in body
    assert "gizmo" in body
    assert "## Genuine CE gaps" in body
    assert "no live probe" in body
