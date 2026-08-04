"""Tests for the context-reduction serialization seam.

The seam (``_to_payload`` + the trimming ``tool()`` wrapper) turns a result
dataclass into a trimmed plain dict: it drops ``payload`` on confirmed writes,
``count``/``truncated`` on list results, keys tagged ``_hidden_keys``, and
applies ``select`` to result rows. ``next_offset`` is never dropped. Whether
``None``-valued fields are elided (empty lists/dicts always survive) depends
on ``elide_none``, derived by the ``tool()`` wrapper from whether the tool's
own signature accepts ``select`` -- select-capable tools keep eliding None
when a field isn't requested, select-incapable tools keep None explicit as
``null`` since there's no way to ask for it back. Tools that return such
results are registered with ``structured_output=False`` so the trimmed dict
is emitted verbatim.
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
    list_actions,
    list_capabilities,
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
        "description": "desc",
        "has_description": True,
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
        "lock_version": 1,
        "description": "desc",
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


def _wp_write(*, state: m.WriteResultState) -> m.WorkPackageWriteResult:
    confirmed = state == "confirmed"
    return m.WorkPackageWriteResult(
        action="create",
        state=state,
        ready=True,
        message="ok" if confirmed else "preview",
        work_package_id=9 if confirmed else None,
        project="OPM",
        payload={"subject": "x", "description": {"format": "markdown", "raw": "long text"}},
        validation_errors={},
        # A confirmed write's committed detail is non-None in practice (the
        # server just returned it); preview writes have no detail yet.
        result=_wp_detail(id=9, display_id="OPM-9") if confirmed else None,
    )


# ── _returns_trimmable ────────────────────────────────────────────────────────


def test_returns_trimmable_detects_list_write_bulk() -> None:
    assert _returns_trimmable(list_work_packages) is True  # has results
    assert _returns_trimmable(create_work_package) is True  # has payload
    assert _returns_trimmable(bulk_create_work_packages) is True  # has items
    assert _returns_trimmable(update_relation) is True  # RelationUpdateResult carries payload


def test_returns_trimmable_false_for_single_entity_reads() -> None:
    # get_work_package is NOT here (OPM-373 Phase 4): it now has `select`,
    # so _returns_trimmable is True for it -- see
    # test_returns_trimmable_true_for_select_capable_single_entity_and_list_tools.
    assert _returns_trimmable(get_status) is False


# ── count / truncated dropped from list results ───────────────────────────────


def test_list_result_drops_count_and_truncated() -> None:
    out = _to_payload(_wp_list())
    # next_offset is a pagination control field and is never elided, even when
    # None (no next page) -- callers page until it comes back null, not until
    # it's absent.
    assert set(out) == {"offset", "limit", "total", "results", "next_offset"}
    assert "count" not in out
    assert "truncated" not in out
    assert out["next_offset"] is None


# ── None-valued fields elided, empty collections kept (Phase 1) ────────────────


def test_none_valued_field_is_elided_when_elide_none_true() -> None:
    detail = _wp_detail(priority=None, category=None, children=[])
    out = _to_payload(detail)  # default elide_none=True
    assert "priority" not in out
    assert "category" not in out
    # Empty list/dict fields are semantically "present but empty", distinct
    # from None ("not applicable") — they must survive regardless.
    assert out["children"] == []

    write_result = _wp_write(state="confirmed")  # validation_errors={} on success
    write_out = _to_payload(write_result)
    assert write_out["validation_errors"] == {}


def test_none_valued_field_kept_explicit_when_not_elide_none() -> None:
    # Tools with no `select` parameter (most single-entity reads, most write
    # results) are registered with elide_none=False, since there is no way
    # for a caller to ask for an elided field back. Simulate that policy
    # directly by passing elide_none=False explicitly -- WorkPackageDetail
    # itself is select-capable now (via get_work_package, OPM-373 Phase 4),
    # but this test exercises the _to_payload mechanism in isolation, not
    # get_work_package's actual registered elide_none policy.
    detail = _wp_detail(priority=None, category=None, children=[])
    out = _to_payload(detail, elide_none=False)
    assert out["priority"] is None
    assert out["category"] is None
    assert out["children"] == []


def test_select_field_with_none_value_stays_explicit_null() -> None:
    # Requesting a field via select guarantees its presence, even when its
    # value is None -- this is how a caller distinguishes "unset" from "not
    # requested". select trims either the top-level row list, or (since
    # OPM-373 Phase 4) a bare top-level entity directly -- see
    # _to_payload's docstring. This test exercises the row-list case; a
    # list result is used to actually exercise _select_fields via the
    # per-row branch.
    row = _wp_summary(priority=None)
    out = _to_payload(_wp_list(results=[row]), select=frozenset({"id", "priority"}))
    selected_row = out["results"][0]
    assert selected_row["priority"] is None
    assert selected_row["id"] == row.id


def test_unselected_none_field_still_absent_alongside_selected_null() -> None:
    # Contrast case in the same row: a requested None field is explicit null,
    # an unrequested None field remains fully absent.
    row = _wp_summary(priority=None, assignee=None)
    out = _to_payload(_wp_list(results=[row]), select=frozenset({"id", "priority"}))
    selected_row = out["results"][0]
    assert selected_row["priority"] is None
    assert "assignee" not in selected_row


# ── payload dropped only on confirmed writes ──────────────────────────────────


def test_confirmed_write_drops_payload_keeps_result() -> None:
    out = _to_payload(_wp_write(state="confirmed"))
    assert "payload" not in out
    assert "result" in out


def test_preview_write_keeps_payload() -> None:
    out = _to_payload(_wp_write(state="preview"))
    assert "payload" in out


def test_rejected_and_invalid_writes_keep_payload() -> None:
    # Only "confirmed" drops payload -- the other two non-preview states
    # ("rejected"/"invalid", both validation-error outcomes) must keep it too,
    # same as "preview" above.
    assert "payload" in _to_payload(_wp_write(state="rejected"))
    assert "payload" in _to_payload(_wp_write(state="invalid"))


def test_bulk_drops_nested_item_payload_on_confirm() -> None:
    inner = _wp_write(state="confirmed")
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
    assert out["items"][0]["result"]["state"] == "confirmed"


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
    # wrapper fields always survive regardless of select, but None-valued ones
    # (error=None on this successful item) are still elided (Phase 1).
    assert sorted(row) == ["id", "success", "work_package"]


def test_batch_read_select_none_returns_full_detail() -> None:
    out = _to_payload(_batch_read())
    assert "description" in out["results"][0]["work_package"]


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


# ── select trims the nested result on bulk writes ────────────────────────────


def _bulk_write(*, items=None) -> m.BulkWorkPackageWriteResult:
    items = (
        items
        if items is not None
        else [m.BulkWorkPackageItemResult(index=0, success=True, error=None, result=_wp_write(state="preview"))]
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
    # work_package_id is None on this preview-write fixture, but selecting it
    # now guarantees its presence as an explicit null.
    assert sorted(row["result"]) == ["ready", "work_package_id"]
    assert row["result"]["work_package_id"] is None
    # wrapper fields always survive regardless of select, but None-valued ones
    # (error=None on this successful item) are still elided -- wrapper fields
    # are never select-targetable.
    assert sorted(row) == ["index", "result", "success"]


def test_bulk_select_skips_failed_items_without_crash() -> None:
    items = [
        m.BulkWorkPackageItemResult(index=0, success=True, error=None, result=_wp_write(state="preview")),
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
    object.__setattr__(row, "_hidden_keys", frozenset({"description"}))
    out = _to_payload(_wp_list(results=[row]))
    assert "description" not in out["results"][0]
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
        # OPM-373 Phase 4: now select-capable, hence trimmed.
        "get_work_package",
        "list_actions",
        "list_capabilities",
    ]:
        assert tools[name].output_schema is None, name


def test_untrimmed_tools_keep_output_schema() -> None:
    tools = _tools(create_app(_make_settings()))
    # get_work_package moved to test_trimmed_tools_have_no_output_schema above
    # (OPM-373 Phase 4: it now has `select`, so it's trimmed unconditionally).
    for name in ["get_status", "get_project"]:
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
        # OPM-373 Phase 4.
        "get_work_package",
        "list_actions",
        "list_capabilities",
    ]:
        assert "select" in json.dumps(tools[name].parameters), name


# ── select is actually threaded through the registered wrapper ───────────────
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
    # This is a confirm=False preview, so work_package_id is None (not yet
    # created), but selecting it now guarantees its presence as an explicit
    # null.
    assert sorted(row["result"]) == ["ready", "work_package_id"]
    assert row["result"]["work_package_id"] is None
    # wrapper fields always survive regardless of select, but None-valued ones
    # (error=None on this successful item) are still elided -- wrapper fields
    # are never select-targetable.
    assert sorted(k for k in row if k != "result") == ["index", "success"]

    await client.aclose()


# ── elide_none is derived from the tool's own signature, not its return type ─
#
# 14 list tools (e.g. list_statuses) return a `results`-bearing dataclass but
# have no `select` parameter at all -- a caller has no way to ask for an
# elided field back. If elide_none were derived from the return type's shape
# (row_field_name is not None) rather than the tool's real signature, these
# would be wrongly treated as select-driven and their None fields would be
# permanently unrecoverable. This must be proven end-to-end through the
# registered wrapper, not just by calling _to_payload with a manually-set
# flag, since only the wrapper actually inspects the tool's signature.


@pytest.mark.asyncio
async def test_select_less_list_tool_keeps_null_fields_through_registered_wrapper() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 1,
                                "name": "New",
                                "isDefault": True,
                                "isClosed": False,
                                # color omitted -> normalizes to None; there is
                                # no `select` param on list_statuses, so this
                                # None field must stay explicit, not elided.
                                "position": 1,
                            }
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _make_settings()
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    fn = _tools(create_app(settings))["list_statuses"].fn

    result = await fn(_FakeContext(client))

    assert isinstance(result, dict)  # proves _to_payload ran (has a results field)
    assert "select" not in json.dumps(_tools(create_app(settings))["list_statuses"].parameters)
    assert result["results"][0]["color"] is None
    await client.aclose()


@pytest.mark.asyncio
async def test_select_capable_list_tool_still_elides_none_without_select_through_registered_wrapper() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v3/work_packages":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "count": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 5,
                                "subject": "Subject",
                                # priority omitted -> normalizes to None; list_work_packages
                                # has a `select` param, so without `select` this must still
                                # be elided (unlike the select-less list_statuses above).
                                "_links": {
                                    "self": {"href": "/api/v3/work_packages/5", "title": "OPM-5"},
                                    "type": {"title": "Task"},
                                    "status": {"title": "New"},
                                    "project": {"href": "/api/v3/projects/1", "title": "OPM"},
                                },
                            }
                        ]
                    },
                    "_links": {},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _make_settings()
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    fn = _tools(create_app(settings))["list_work_packages"].fn

    result = await fn(_FakeContext(client))

    assert isinstance(result, dict)
    # Contrast: list_work_packages DOES expose select, so its baseline
    # (no select passed) elide_none policy is True -- next_offset is still
    # always present regardless.
    assert "next_offset" in result
    assert "priority" not in result["results"][0]
    await client.aclose()
    assert result["next_offset"] is None


# ── elide_none is threaded unchanged through recursion, not re-derived ───────


def test_select_capable_tool_without_select_still_elides_nested_row_none_fields() -> None:
    # list_work_packages is select-capable; called without select, its nested
    # WorkPackageSummary rows must keep eliding None fields (unchanged Rule 2
    # behavior) -- elide_none is not re-evaluated per recursion level based on
    # whether the nested type itself has a results/items field.
    row = _wp_summary(priority=None)
    out = _to_payload(_wp_list(results=[row]), elide_none=True)
    assert "priority" not in out["results"][0]


# ── next_offset survives on a type that does not inherit PageResult ──────────


def test_notification_list_keeps_null_next_offset() -> None:
    result = m.NotificationListResult(count=0, total=0, truncated=False, next_offset=None, results=[])
    assert _to_payload(result)["next_offset"] is None


# ── hidden fields take precedence over select ─────────────────────────────────


def test_hidden_field_stays_absent_even_when_selected() -> None:
    row = _wp_summary()
    object.__setattr__(row, "_hidden_keys", frozenset({"priority"}))
    out = _to_payload(_wp_list(results=[row]), select=frozenset({"id", "priority"}))
    assert "priority" not in out["results"][0]
    assert "id" in out["results"][0]


# ── select on a bare top-level entity (OPM-373 Phase 4) ───────────────────────


def test_top_level_select_trims_bare_dataclass_fields() -> None:
    # WorkPackageDetail has no results/items field -- this exercises the new
    # row_field_name-is-None branch in _to_payload directly, independent of
    # whether get_work_package itself is wired up (see the registered-wrapper
    # test below for that).
    detail = _wp_detail(priority=None)
    out = _to_payload(detail, select=frozenset({"id", "subject", "priority"}))
    assert sorted(out) == ["id", "priority", "subject"]
    assert out["priority"] is None  # selected None field stays an explicit null
    assert "description" not in out  # unselected field fully absent


def test_top_level_select_respects_hidden_keys() -> None:
    detail = _wp_detail()
    object.__setattr__(detail, "_hidden_keys", frozenset({"subject"}))
    out = _to_payload(detail, select=frozenset({"id", "subject"}))
    assert "subject" not in out
    assert "id" in out


def test_validate_select_rejects_unknown_field_for_action_summary() -> None:
    with pytest.raises(ValueError, match="not a valid ActionSummary field"):
        _validate_select(["bogus"], row_type=m.ActionSummary)


def test_validate_select_rejects_unknown_field_for_capability_summary() -> None:
    with pytest.raises(ValueError, match="not a valid CapabilitySummary field"):
        _validate_select(["bogus"], row_type=m.CapabilitySummary)


def test_returns_trimmable_true_for_select_capable_single_entity_and_list_tools() -> None:
    assert _returns_trimmable(get_work_package) is True  # select in signature, no results/items/payload
    assert _returns_trimmable(list_actions) is True
    assert _returns_trimmable(list_capabilities) is True


@pytest.mark.asyncio
async def test_get_work_package_select_is_threaded_through_the_registered_wrapper() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v3/work_packages/5":
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "_type": "WorkPackage",
                    "subject": "Subject",
                    "lockVersion": 1,
                    "description": {"raw": "desc"},
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                    "_links": {
                        "type": {"title": "Task"},
                        "status": {"title": "New"},
                        "project": {"href": "/api/v3/projects/1", "title": "Demo Project"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _make_settings()
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    fn = _tools(create_app(settings))["get_work_package"].fn

    result = await fn(_FakeContext(client), work_package_id=5, select=["id", "subject"])

    assert isinstance(result, dict)  # proves _to_payload ran, not a raw dataclass
    assert sorted(result) == ["id", "subject"]

    await client.aclose()


# ── single-entity reads are trimmed only when hide-fields are active ─────────


def test_single_entity_read_keeps_schema_without_hide_config() -> None:
    # get_work_package is no longer a valid example here (OPM-373 Phase 4:
    # it's now select-capable, hence trimmed unconditionally) -- get_status
    # remains genuinely select-less and untrimmed absent hide-config.
    tools = _tools(create_app(_make_settings()))
    assert tools["get_status"].output_schema is not None


def test_single_entity_read_trimmed_when_hide_config_active() -> None:
    tools = _tools(create_app(_make_settings(hidden_fields={"status": ("name",)})))
    # With hiding on, get_* results must be trimmable (dict output) to drop keys.
    assert tools["get_status"].output_schema is None


def test_single_entity_read_keeps_other_null_fields_when_hide_config_active() -> None:
    # A select-less single-entity read (e.g. get_status) is registered with
    # elide_none=False, so under hide_active it is routed through
    # _to_payload with elide_none=False (Rule 1 applies) purely to drop the
    # hidden key -- its other None fields must stay explicit, not newly
    # start being elided as a side effect of field-hiding being on.
    # WorkPackageDetail is just this test's fixture type here -- it exercises
    # _to_payload directly, independent of get_work_package's own
    # registration (which is now select-capable, elide_none=True, since
    # OPM-373 Phase 4; unrelated to what this test verifies).
    detail = _wp_detail(priority=None, category=None)
    object.__setattr__(detail, "_hidden_keys", frozenset({"lock_version"}))
    out = _to_payload(detail, elide_none=False)
    assert "lock_version" not in out
    assert out["priority"] is None
    assert out["category"] is None
