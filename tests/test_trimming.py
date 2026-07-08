"""Tests for the context-reduction serialization seam (OPM-65/66/71/72).

The seam (``_to_payload`` + the trimming ``tool()`` wrapper) turns a result
dataclass into a trimmed plain dict: it drops ``payload`` on confirmed writes,
``count``/``truncated`` on list results, keys tagged ``_hidden_keys``, and applies
``select`` to result rows. Tools that return such results are registered with
``structured_output=False`` so the trimmed dict is emitted verbatim.
"""

from __future__ import annotations

import json

import pytest

from openproject_ce_mcp import models as m
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.tools import (
    _normalize_select,
    _returns_trimmable,
    _to_payload,
    _validate_select,
    bulk_create_work_packages,
    create_work_package,
    get_status,
    get_work_package,
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


# ── OPM-71: count / truncated dropped from list results ───────────────────────


def test_list_result_drops_count_and_truncated() -> None:
    out = _to_payload(_wp_list())
    assert set(out) == {"offset", "limit", "total", "next_offset", "results"}
    assert "count" not in out
    assert "truncated" not in out


# ── OPM-66: payload dropped only on confirmed writes ──────────────────────────


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


# ── OPM-65: select trims result rows ──────────────────────────────────────────


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


# ── OPM-72 forward-compat: _hidden_keys removed entirely ──────────────────────


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
    ]:
        assert tools[name].output_schema is None, name


def test_untrimmed_tools_keep_output_schema() -> None:
    tools = _tools(create_app(_make_settings()))
    for name in ["get_work_package", "get_status", "get_project"]:
        assert tools[name].output_schema is not None, name


def test_list_tools_expose_select_param() -> None:
    tools = _tools(create_app(_make_settings()))
    for name in ["list_work_packages", "search_work_packages", "list_projects", "list_users"]:
        assert "select" in json.dumps(tools[name].parameters), name


# ── OPM-72: single-entity reads are trimmed only when hide-fields are active ──


def test_single_entity_read_keeps_schema_without_hide_config() -> None:
    tools = _tools(create_app(_make_settings()))
    assert tools["get_work_package"].output_schema is not None


def test_single_entity_read_trimmed_when_hide_config_active() -> None:
    tools = _tools(create_app(_make_settings(hidden_fields={"work_package": ("percentage_complete",)})))
    # With hiding on, get_* results must be trimmable (dict output) to drop keys.
    assert tools["get_work_package"].output_schema is None
