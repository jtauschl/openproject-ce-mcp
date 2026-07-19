"""Tests for the context-reduction serialization seam.

The seam (``_to_payload`` + the trimming ``tool()`` wrapper) turns a result
dataclass into a trimmed plain dict: it drops ``payload`` on confirmed writes,
``count``/``truncated`` on list results, keys tagged ``_hidden_keys``, and applies
``select`` to result rows. Tools that return such results are registered with
``structured_output=False`` so the trimmed dict is emitted verbatim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace

import httpx
import pytest

from openproject_ce_mcp import models as m
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.tools import (
    _normalize_select,
    _returns_trimmable,
    _to_payload,
    _validate_select,
    bulk_create_work_packages,
    bulk_update_work_packages,
    create_work_package,
    get_status,
    get_work_package,
    get_work_packages,
    list_work_packages,
    update_relation,
)


def _wp_summary(**overrides) -> m.WorkPackageSummary:
    defaults = {
        "id": 5,
        "display_id": "OPM-5",
        "subject": "Subject",
        "type": "Task",
        "status": "New",
        "priority": None,
        "project_phase": None,
        "assignee": None,
        "responsible": None,
        "project": "OPM",
        "version": None,
        "sprint": None,
        "start_date": None,
        "due_date": None,
        "percentage_complete": None,
        "description": "desc",
        "has_description": True,
        "url": "http://x/5",
        "description_truncated": False,
        "description_length": 4,
    }
    defaults.update(overrides)
    return m.WorkPackageSummary(**defaults)


def _wp_list(results=None) -> m.WorkPackageListResult:
    results = results if results is not None else [_wp_summary()]
    return m.WorkPackageListResult(
        offset=1,
        limit=20,
        total=len(results),
        count=len(results),
        next_offset=None,
        truncated=False,
        results=results,
    )


def _wp_detail(**overrides) -> m.WorkPackageDetail:
    defaults = {
        "id": 5,
        "display_id": "OPM-5",
        "subject": "Subject",
        "type": "Task",
        "status": "New",
        "priority": None,
        "project_phase": None,
        "assignee": None,
        "responsible": None,
        "project": "OPM",
        "version": None,
        "sprint": None,
        "parent_id": None,
        "parent_display_id": None,
        "start_date": None,
        "due_date": None,
        "percentage_complete": None,
        "lock_version": 1,
        "description": "desc",
        "url": "http://x/5",
        "activities_url": "http://x/5/activities",
        "relations_url": "http://x/5/relations",
    }
    defaults.update(overrides)
    return m.WorkPackageDetail(**defaults)


def _batch_read(items=None) -> m.BatchWorkPackageReadResult:
    items = (
        items
        if items is not None
        else [m.BatchWorkPackageReadItemResult(id=5, success=True, work_package=_wp_detail(), error=None)]
    )
    return m.BatchWorkPackageReadResult(
        action="batch_read",
        total=len(items),
        succeeded=sum(1 for item in items if item.success),
        failed=sum(1 for item in items if not item.success),
        message="ok",
        results=items,
    )


def _wp_write(*, confirmed: bool) -> m.WorkPackageWriteResult:
    return m.WorkPackageWriteResult(
        action="create",
        confirmed=confirmed,
        requires_confirmation=not confirmed,
        ready=True,
        message="ok" if confirmed else "preview",
        work_package_id=9 if confirmed else None,
        project="OPM",
        payload={"subject": "x", "description": {"format": "markdown", "raw": "long text"}},
        validation_errors={},
        result=None,
    )


# ── _returns_trimmable ────────────────────────────────────────────────────────


def test_returns_trimmable_detects_list_write_bulk() -> None:
    assert _returns_trimmable(list_work_packages) is True  # has results
    assert _returns_trimmable(create_work_package) is True  # has payload
    assert _returns_trimmable(bulk_create_work_packages) is True  # has items
    assert _returns_trimmable(update_relation) is True  # RelationUpdateResult carries payload


def test_returns_trimmable_false_for_single_entity_reads() -> None:
    assert _returns_trimmable(get_work_package) is False
    assert _returns_trimmable(get_status) is False


# ── count / truncated dropped from list results ───────────────────────────────


def test_list_result_drops_count_and_truncated() -> None:
    out = _to_payload(_wp_list())
    assert set(out) == {"offset", "limit", "total", "next_offset", "results"}
    assert "count" not in out
    assert "truncated" not in out


# ── payload dropped only on confirmed writes ──────────────────────────────────


def test_confirmed_write_drops_payload_keeps_result() -> None:
    out = _to_payload(_wp_write(confirmed=True))
    assert "payload" not in out
    assert "result" in out


def test_preview_write_keeps_payload() -> None:
    out = _to_payload(_wp_write(confirmed=False))
    assert "payload" in out


def test_bulk_drops_nested_item_payload_on_confirm() -> None:
    inner = _wp_write(confirmed=True)
    bulk = m.BulkWorkPackageWriteResult(
        action="bulk_create",
        confirmed=True,
        requires_confirmation=False,
        total=1,
        succeeded=1,
        failed=0,
        message="ok",
        items=[m.BulkWorkPackageItemResult(index=0, success=True, error=None, result=inner)],
    )
    out = _to_payload(bulk)
    assert "payload" not in out["items"][0]["result"]
    assert out["items"][0]["result"]["confirmed"] is True


# ── select trims result rows ──────────────────────────────────────────────────


def test_select_keeps_only_requested_row_fields() -> None:
    out = _to_payload(_wp_list(), select=frozenset({"id", "subject"}))
    assert sorted(out["results"][0]) == ["id", "subject"]
    # non-row (wrapper) fields are untouched
    assert "offset" in out and "total" in out


def test_validate_select_rejects_unknown_field() -> None:
    with pytest.raises(ValueError, match="not a valid WorkPackageSummary field"):
        _validate_select(["id", "bogus"], row_type=m.WorkPackageSummary)


def test_validate_select_rejects_empty() -> None:
    with pytest.raises(ValueError, match="at least one field"):
        _validate_select([], row_type=m.WorkPackageSummary)


def test_validate_select_none_passes() -> None:
    assert _validate_select(None, row_type=m.WorkPackageSummary) is None


def test_normalize_select_shapes_kwarg() -> None:
    assert _normalize_select(None) is None
    assert _normalize_select([]) is None
    assert _normalize_select(["id", " subject "]) == frozenset({"id", "subject"})


# ── select trims the nested work_package on batch reads ──────────────────────


def test_batch_read_select_trims_nested_work_package_fields() -> None:
    out = _to_payload(_batch_read(), select=frozenset({"id", "subject"}))
    row = out["results"][0]
    assert sorted(row["work_package"]) == ["id", "subject"]
    # wrapper fields always survive, regardless of select
    assert sorted(row) == ["error", "id", "success", "work_package"]


def test_batch_read_select_none_returns_full_detail() -> None:
    out = _to_payload(_batch_read())
    assert "activities_url" in out["results"][0]["work_package"]


def test_batch_read_select_skips_failed_items_without_crash() -> None:
    items = [
        m.BatchWorkPackageReadItemResult(id=5, success=True, work_package=_wp_detail(), error=None),
        m.BatchWorkPackageReadItemResult(id=6, success=False, work_package=None, error="not found"),
    ]
    out = _to_payload(_batch_read(items=items), select=frozenset({"id", "subject"}))
    assert out["results"][1]["work_package"] is None
    assert out["results"][1]["error"] == "not found"


def test_validate_select_rejects_unknown_field_for_work_package_detail() -> None:
    with pytest.raises(ValueError, match="not a valid WorkPackageDetail field"):
        _validate_select(["bogus"], row_type=m.WorkPackageDetail)


def test_returns_trimmable_true_for_batch_read() -> None:
    assert _returns_trimmable(get_work_packages) is True


# ── select trims the nested result on bulk writes (OPM-155) ──────────────────


def _bulk_write(*, items=None) -> m.BulkWorkPackageWriteResult:
    items = (
        items
        if items is not None
        else [m.BulkWorkPackageItemResult(index=0, success=True, error=None, result=_wp_write(confirmed=False))]
    )
    return m.BulkWorkPackageWriteResult(
        action="bulk_create",
        confirmed=False,
        requires_confirmation=True,
        total=len(items),
        succeeded=sum(1 for item in items if item.success),
        failed=sum(1 for item in items if not item.success),
        message="ok",
        items=items,
    )


def test_bulk_select_none_keeps_full_preview_payload() -> None:
    out = _to_payload(_bulk_write())
    assert "payload" in out["items"][0]["result"]


def test_bulk_select_trims_nested_result_fields() -> None:
    out = _to_payload(_bulk_write(), select=frozenset({"ready", "work_package_id"}))
    row = out["items"][0]
    assert sorted(row["result"]) == ["ready", "work_package_id"]
    # wrapper fields always survive, regardless of select
    assert sorted(row) == ["error", "index", "result", "success"]


def test_bulk_select_skips_failed_items_without_crash() -> None:
    items = [
        m.BulkWorkPackageItemResult(index=0, success=True, error=None, result=_wp_write(confirmed=False)),
        m.BulkWorkPackageItemResult(index=1, success=False, error="boom", result=None),
    ]
    out = _to_payload(_bulk_write(items=items), select=frozenset({"ready", "work_package_id"}))
    assert out["items"][1]["result"] is None
    assert out["items"][1]["error"] == "boom"


def test_validate_select_rejects_unknown_field_for_work_package_write_result() -> None:
    with pytest.raises(ValueError, match="not a valid WorkPackageWriteResult field"):
        _validate_select(["bogus"], row_type=m.WorkPackageWriteResult)


def test_returns_trimmable_true_for_bulk_update() -> None:
    assert _returns_trimmable(bulk_update_work_packages) is True


# ── forward-compat: _hidden_keys removed entirely ─────────────────────────────


def test_hidden_keys_attribute_removes_keys() -> None:
    row = _wp_summary()
    object.__setattr__(row, "_hidden_keys", frozenset({"description", "url"}))
    out = _to_payload(_wp_list(results=[row]))
    assert "description" not in out["results"][0]
    assert "url" not in out["results"][0]
    assert "_hidden_keys" not in out["results"][0]


# ── passthrough: non-dataclass results are untouched ──────────────────────────


def test_non_dataclass_passthrough() -> None:
    assert _to_payload({"a": 1, "payload": {"x": 1}}) == {"a": 1, "payload": {"x": 1}}
    assert _to_payload([1, 2, 3]) == [1, 2, 3]
    assert _to_payload("text") == "text"


# ── registration: trimmed tools drop their output schema ──────────────────────


def _make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "enable_work_package_write": True,
        "enable_admin_read": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_trimmed_tools_have_no_output_schema() -> None:
    tools = _tools(create_app(_make_settings()))
    for name in [
        "list_work_packages",
        "search_work_packages",
        "list_projects",
        "list_users",
        "create_work_package",
        "update_work_package",
        "bulk_create_work_packages",
        "update_relation",
        "get_work_packages",
    ]:
        assert tools[name].output_schema is None, name


def test_untrimmed_tools_keep_output_schema() -> None:
    tools = _tools(create_app(_make_settings()))
    for name in ["get_work_package", "get_status", "get_project"]:
        assert tools[name].output_schema is not None, name


def test_list_tools_expose_select_param() -> None:
    tools = _tools(create_app(_make_settings()))
    for name in [
        "list_work_packages",
        "search_work_packages",
        "list_projects",
        "list_users",
        "get_work_packages",
        "bulk_create_work_packages",
        "bulk_update_work_packages",
    ]:
        assert "select" in json.dumps(tools[name].parameters), name


# ── select is actually threaded through the registered wrapper (OPM-155) ──────
#
# The test above only proves `select` is *published* in a tool's schema. It
# does NOT prove tools.py:459-460 (the register_tools() trimming wrapper)
# actually *reads* the kwarg and applies it via _to_payload -- and the
# _to_payload unit tests further up only prove the mechanism works in
# isolation, not that it's really wired up for these two tools. This test
# calls the real registered callable (`Tool.fn`, confirmed by inspection to be
# the `trimming` wrapper from register_tools, not the raw tool function -- it
# returns a plain dict, not a dataclass) through a real OpenProjectClient, so
# it's the one assertion that proves the full path end-to-end. One bulk tool
# is enough: both share the same return type and the same generic wrapper
# mechanism: their own signatures/validators are already covered separately
# above.


@dataclass
class _FakeAppContext:
    client: OpenProjectClient


class _FakeContext:
    def __init__(self, client: OpenProjectClient) -> None:
        self.request_context = SimpleNamespace(lifespan_context=_FakeAppContext(client=client))


@pytest.mark.asyncio
async def test_bulk_create_work_packages_select_is_threaded_through_the_registered_wrapper() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.method == "GET" and request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.method == "POST" and request.url.path == "/api/v3/projects/1/work_packages/form":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _make_settings()
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    fn = _tools(create_app(settings))["bulk_create_work_packages"].fn

    result = await fn(
        _FakeContext(client),
        items=[{"project": "demo", "type": "Task", "subject": "WP 1"}],
        select=["ready", "work_package_id"],
        confirm=False,
    )

    assert isinstance(result, dict)  # proves _to_payload ran, not a raw dataclass
    row = result["items"][0]
    assert sorted(row["result"]) == ["ready", "work_package_id"]
    # wrapper fields always survive, regardless of select
    assert sorted(k for k in row if k != "result") == ["error", "index", "success"]

    await client.aclose()


# ── single-entity reads are trimmed only when hide-fields are active ─────────


def test_single_entity_read_keeps_schema_without_hide_config() -> None:
    tools = _tools(create_app(_make_settings()))
    assert tools["get_work_package"].output_schema is not None


def test_single_entity_read_trimmed_when_hide_config_active() -> None:
    tools = _tools(create_app(_make_settings(hidden_fields={"work_package": ("percentage_complete",)})))
    # With hiding on, get_* results must be trimmable (dict output) to drop keys.
    assert tools["get_work_package"].output_schema is None
