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


def test_client_resources_detects_helper_keyword_path_arguments(tmp_path, monkeypatch):
    # list_views/get_view reach the "views" resource only via
    # path="views" / path=f"views/{id}" keyword arguments to the shared
    # bounded-fetch/detail helpers, never a direct self._get("views"...) call.
    # "views" has no other call site to fall back on, so it was the one
    # resource silently undercounted as unused until path=/write_path=/
    # delete_path= keyword arguments were also matched.
    synthetic_client = tmp_path / "client.py"
    synthetic_client.write_text(
        "async def list_views(self):\n"
        '    return await self._fetch_bounded_and_paginate(path="views")\n'
        "async def get_view(self, view_id):\n"
        '    return await self._fetch_and_normalize_detail(path=f"views/{view_id}")\n'
    )
    monkeypatch.setattr(check_coverage, "CLIENT", synthetic_client)

    assert "views" in check_coverage._client_resources()


def test_client_resources_scans_app_adapters_directory(tmp_path, monkeypatch):
    # On release/0.4.0 the real HTTP-calling code lives in
    # app/adapters/httpx_*.py, not client.py (a thin, mostly-delegating shim
    # since the layered app/ architecture migration) -- a resource reached
    # only through an adapter's self._transport.*_json(...) call, with no
    # matching call site in client.py itself, was silently undercounted as
    # unused (OPM-430).
    synthetic_client = tmp_path / "client.py"
    synthetic_client.write_text("")
    monkeypatch.setattr(check_coverage, "CLIENT", synthetic_client)

    adapters_dir = tmp_path / "app" / "adapters"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "httpx_meeting_api.py").write_text(
        "class HttpxMeetingApi:\n"
        "    async def list(self):\n"
        '        return await self._transport.get_json("meetings")\n'
        "    async def get(self, meeting_id):\n"
        '        return await self._transport.get_json(f"meetings/{meeting_id}")\n'
    )
    monkeypatch.setattr(check_coverage, "ADAPTERS_DIR", adapters_dir)

    assert "meetings" in check_coverage._client_resources()


def test_client_resources_detects_request_raw_verb_calls(tmp_path, monkeypatch):
    # "workspaces" (project favorite add/remove) is reached only via
    # self._transport.request_raw("POST"/"DELETE", path, ...) -- a third
    # call-site shape distinct from the *_json(...) helpers, which would
    # otherwise silently undercount it as unused (OPM-430).
    synthetic_client = tmp_path / "client.py"
    synthetic_client.write_text("")
    monkeypatch.setattr(check_coverage, "CLIENT", synthetic_client)

    adapters_dir = tmp_path / "app" / "adapters"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "httpx_project_api.py").write_text(
        "class HttpxProjectApi:\n"
        "    async def add_favorite(self, project_id):\n"
        '        await self._transport.request_raw("POST", f"workspaces/{project_id}/favorite", json_body={})\n'
    )
    monkeypatch.setattr(check_coverage, "ADAPTERS_DIR", adapters_dir)

    assert "workspaces" in check_coverage._client_resources()


def test_client_resources_detects_post_raw_json_calls(tmp_path, monkeypatch):
    # self._transport.post_raw_json(...) is a fourth Transport method
    # distinct from the *_json verbs, post_multipart, and request_raw.
    # The one real caller (HttpxExtendedMetadataApi.render_text) builds its
    # path in a local variable first, which this scan can't resolve (see
    # _client_resources's docstring) -- this test instead isolates the
    # regex itself against a literal path, so the post_raw_json match arm
    # added for OPM-430 has a direct regression test independent of
    # whether any real call site happens to use a literal.
    synthetic_client = tmp_path / "client.py"
    synthetic_client.write_text("")
    monkeypatch.setattr(check_coverage, "CLIENT", synthetic_client)

    adapters_dir = tmp_path / "app" / "adapters"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "httpx_extended_metadata_api.py").write_text(
        "class HttpxExtendedMetadataApi:\n"
        "    async def render_plain(self, text):\n"
        '        return await self._transport.post_raw_json(\n            "render/plain", content=text.encode(), headers={}\n        )\n'
    )
    monkeypatch.setattr(check_coverage, "ADAPTERS_DIR", adapters_dir)

    assert "render" in check_coverage._client_resources()


def test_client_resources_detects_post_multipart_calls(tmp_path, monkeypatch):
    # Attachment uploads use self._transport.post_multipart(...), a
    # Transport method distinct from the *_json verbs and request_raw --
    # missing it would silently undercount the resource as unused.
    synthetic_client = tmp_path / "client.py"
    synthetic_client.write_text("")
    monkeypatch.setattr(check_coverage, "CLIENT", synthetic_client)

    adapters_dir = tmp_path / "app" / "adapters"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "httpx_attachment_api.py").write_text(
        "class HttpxAttachmentApi:\n"
        "    async def upload(self, work_package_id, filename, content):\n"
        '        response = await self._transport.post_multipart(\n            f"work_packages/{work_package_id}/attachments", files={}\n        )\n'
    )
    monkeypatch.setattr(check_coverage, "ADAPTERS_DIR", adapters_dir)

    assert "work_packages" in check_coverage._client_resources()


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
