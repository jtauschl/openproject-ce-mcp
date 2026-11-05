"""A bulk write item that succeeded in a confirmed call is lean when the caller gave no `select`.

The lean item keeps what a caller needs to correlate and audit a large run: the wrapper, the work package
reference, the write state, the ticket each reference resolved to, and the display id and status of the written
work package. A failed item, an item OpenProject rejected, and a preview keep their full write result, and a
caller `select` is applied as given.
"""

from __future__ import annotations

import json

import pytest

from openproject_ce_mcp import models as m
from openproject_ce_mcp.app.form_result import ValidationFailure
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolInputError
from openproject_ce_mcp.tools_validation import BULK_ITEM_WRAPPER_FIELDS, _validate_select


def _detail(**overrides) -> m.WorkPackageDetail:
    defaults = {
        "id": 9,
        "display_id": "DEMO-9",
        "subject": "Subject of the work package",
        "type": "Task",
        "status": "In progress",
        "priority": "Normal",
        "project_phase": None,
        "assignee": "Ada",
        "responsible": None,
        "project": "Demo",
        "version": None,
        "target_versions": [],
        "observed_in_versions": [],
        "sprint": None,
        "parent_id": None,
        "parent_display_id": None,
        "start_date": None,
        "due_date": None,
        "lock_version": 3,
        "description": "desc",
        "created_at": "2026-11-02T20:22:38.520Z",
        "updated_at": "2026-11-02T20:23:02.918Z",
        "author": "Ada",
    }
    defaults.update(overrides)
    return m.WorkPackageDetail(**defaults)


def _target(**overrides) -> m.ResolvedWorkPackage:
    defaults = {"id": 9, "display_id": "DEMO-9", "project": "Demo", "subject": "Subject", "status": "New"}
    return m.ResolvedWorkPackage(**{**defaults, **overrides})


def _write(*, state: str = "confirmed", ready: bool = True, **overrides) -> m.WorkPackageWriteResult:
    fields = {
        "action": "update",
        "state": state,
        "ready": ready,
        "message": "Work package updated successfully.",
        "work_package_id": 9,
        "project": "Demo",
        "payload": {"status": "In progress"},
        "validation_errors": {},
        "result": _detail(),
        "target": _target(),
    }
    return m.WorkPackageWriteResult(**{**fields, **overrides})


def _item(write: m.WorkPackageWriteResult | None, *, index: int = 0, success: bool = True, error: str | None = None):
    return m.BulkWorkPackageItemResult(index=index, success=success, error=error, result=write)


def _bulk(items: list[m.BulkWorkPackageItemResult], *, confirmed: bool = True) -> m.BulkWorkPackageWriteResult:
    return m.BulkWorkPackageWriteResult(
        action="bulk_update",
        confirmed=confirmed,
        requires_confirmation=not confirmed,
        total=len(items),
        succeeded=sum(1 for item in items if item.success),
        failed=sum(1 for item in items if not item.success),
        message="done",
        items=items,
    )


def _first_item(items: list[m.BulkWorkPackageItemResult], **kwargs) -> dict:
    return _to_payload(_bulk(items), **kwargs)["items"][0]


LEAN_KEYS = {"index", "success", "result"}
LEAN_WRITE_KEYS = {"work_package_id", "state", "target", "result"}


def test_a_succeeded_confirmed_update_item_is_lean() -> None:
    item = _first_item([_item(_write())])

    assert set(item) == LEAN_KEYS
    assert set(item["result"]) == LEAN_WRITE_KEYS
    assert item["result"]["work_package_id"] == 9
    assert item["result"]["state"] == "confirmed"
    assert item["result"]["target"] == {
        "id": 9,
        "display_id": "DEMO-9",
        "project": "Demo",
        "subject": "Subject",
        "status": "New",
    }
    assert item["result"]["result"] == {"display_id": "DEMO-9", "status": "In progress"}


def test_a_succeeded_confirmed_create_item_has_no_placeholder_for_the_absent_target() -> None:
    item = _first_item([_item(_write(action="create", target=None))])

    assert set(item["result"]) == {"work_package_id", "state", "result"}


def test_a_succeeded_item_keeps_the_parent_target() -> None:
    item = _first_item([_item(_write(parent_target=_target(id=4, display_id="DEMO-4")))])

    assert item["result"]["parent_target"]["display_id"] == "DEMO-4"


def test_a_hidden_display_id_is_absent_without_a_null() -> None:
    detail = _detail()
    object.__setattr__(detail, "_hidden_keys", frozenset({"display_id"}))

    item = _first_item([_item(_write(result=detail))])

    assert item["result"]["result"] == {"status": "In progress"}


@pytest.mark.parametrize("field", ["status", "display_id"])
def test_a_none_status_or_display_id_leaves_no_null_placeholder(field: str) -> None:
    item = _first_item([_item(_write(result=_detail(**{field: None})))])

    assert field not in item["result"]["result"]
    assert "null" not in json.dumps(item)


def test_a_confirmed_item_without_a_written_work_package_has_no_result_key() -> None:
    item = _first_item([_item(_write(result=None))])

    assert set(item["result"]) == {"work_package_id", "state", "target"}


def test_an_item_that_failed_keeps_its_error_and_has_no_write_result() -> None:
    item = _first_item([_item(None, success=False, error="boom")])

    assert item == {"index": 0, "success": False, "error": "boom"}


def test_an_item_openproject_rejected_keeps_its_validation_errors_and_payload() -> None:
    rejected = _write(
        state="invalid",
        ready=False,
        validation_errors={"subject": ValidationFailure("is too long")},
        result=None,
        message="rejected",
    )

    item = _first_item([_item(rejected, success=False, error="OpenProject rejected the proposed changes.")])

    assert item["result"]["validation_errors"] == {"subject": {"message": "is too long", "error_codes": []}}
    assert item["result"]["payload"] == {"status": "In progress"}
    assert item["result"]["message"] == "rejected"
    assert item["error"] == "OpenProject rejected the proposed changes."


def test_a_preview_item_keeps_its_full_write_result() -> None:
    preview = _write(state="preview", work_package_id="DEMO-9", result=None)

    item = _first_item([_item(preview)])

    assert item["result"]["payload"] == {"status": "In progress"}
    assert item["result"]["message"] == "Work package updated successfully."
    assert "result" not in item["result"]


def test_the_lean_rule_applies_per_item_in_a_mixed_confirmed_run() -> None:
    items = [
        _item(_write(), index=0),
        _item(
            _write(state="invalid", ready=False, validation_errors={"a": ValidationFailure("b")}, result=None),
            index=1,
            success=False,
        ),
    ]

    payload = _to_payload(_bulk(items))["items"]

    assert set(payload[0]["result"]) == LEAN_WRITE_KEYS
    assert payload[1]["result"]["validation_errors"] == {"a": {"message": "b", "error_codes": []}}


def test_a_caller_select_replaces_the_lean_rule() -> None:
    item = _first_item([_item(_write())], select=frozenset({"message", "result.lock_version"}))

    assert item["result"] == {"message": "Work package updated successfully.", "result": {"lock_version": 3}}


def test_the_full_written_work_package_is_one_select_away() -> None:
    item = _first_item([_item(_write())], select=frozenset({"work_package_id", "state", "result"}))

    assert set(item["result"]) == {"work_package_id", "state", "result"}
    assert item["result"]["result"] == _to_payload(_detail())


def test_a_wrapper_only_select_keeps_the_full_nested_result() -> None:
    item = _first_item([_item(_write())], select=frozenset({"index"}))

    assert item["result"] == _to_payload(_write())


def test_the_lean_item_of_a_forty_item_run_stays_small() -> None:
    items = [_item(_write(work_package_id=n, result=_detail(id=n, display_id=f"DEMO-{n}")), index=n) for n in range(40)]

    payload = _to_payload(_bulk(items))

    per_item = [len(json.dumps(item, separators=(",", ":"))) for item in payload["items"]]
    assert max(per_item) < 300


def test_the_id_guess_is_rejected_naming_the_work_package_reference_field() -> None:
    with pytest.raises((ValueError, ToolInputError)) as caught:
        _validate_select(
            ["id", "status"],
            row_type=m.WorkPackageWriteResult,
            wrapper_fields=BULK_ITEM_WRAPPER_FIELDS,
            nested={"result": m.WorkPackageDetail},
        )

    message = str(caught.value)
    assert "select it as 'result.id'" in message
    assert "'work_package_id'" in message


def test_another_unknown_name_keeps_its_message() -> None:
    with pytest.raises((ValueError, ToolInputError)) as caught:
        _validate_select(
            ["nonsense"],
            row_type=m.WorkPackageWriteResult,
            wrapper_fields=BULK_ITEM_WRAPPER_FIELDS,
            nested={"result": m.WorkPackageDetail},
        )

    assert "work_package_id'" not in str(caught.value).split("Allowed:")[0]
