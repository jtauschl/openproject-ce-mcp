"""`none` clears `start_date` and `due_date` on update and bulk update, and only there.

The update validator wraps the two dates like `duration`; the create tools keep the plain date validator, so
`"none"` stays a format error for them. A clear alone is a change (it satisfies "at least one field").
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from _tools_test_helpers import FakeContext

from openproject_ce_mcp import tools_work_packages as work_package_tools
from openproject_ce_mcp.client import CLEAR
from openproject_ce_mcp.tools import (
    bulk_create_work_packages,
    bulk_update_work_packages,
    create_subtask,
    create_work_package,
    update_work_package,
)

DATES = ("start_date", "due_date")


def _validated(**given: object) -> dict[str, Any]:
    parameters = inspect.signature(work_package_tools._validate_work_package_update_fields).parameters
    arguments: dict[str, object] = {
        name: None for name in parameters if name not in {"field_prefix", "parent_field_name"}
    }
    arguments.update(given)
    return work_package_tools._validate_work_package_update_fields(**arguments)


@pytest.mark.parametrize("field", DATES)
@pytest.mark.parametrize("spelling", ["none", "None", "NONE", "  nOnE  "])
def test_none_in_any_case_clears_a_date(field: str, spelling: str) -> None:
    assert _validated(**{field: spelling})[field] is CLEAR


@pytest.mark.parametrize("field", DATES)
def test_an_iso_date_stays_a_date_and_a_bad_value_names_the_format(field: str) -> None:
    assert _validated(**{field: " 2026-12-07 "})[field] == "2026-12-07"
    for bad in ("07.12.2026", "tomorrow", "", 5):
        with pytest.raises(ValueError, match=f"{field} must be YYYY-MM-DD format"):
            _validated(**{field: bad})


def test_one_date_can_be_cleared_while_the_other_is_set() -> None:
    validated = _validated(start_date="none", due_date="2026-12-11")

    assert validated["start_date"] is CLEAR
    assert validated["due_date"] == "2026-12-11"


def test_a_bulk_item_prefix_names_the_field_of_a_bad_date() -> None:
    with pytest.raises(ValueError, match=r"items\[2\]\.due_date must be YYYY-MM-DD format"):
        _validated(due_date="x", field_prefix="items[2].")


class _RecordingClient:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.bulk_items: list[dict[str, Any]] = []

    @property
    def work_package(self) -> _RecordingClient:
        return self

    async def update(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        return kwargs

    async def bulk_update(self, **kwargs: Any) -> dict[str, Any]:
        self.bulk_items.extend(kwargs["items"])
        return {
            "action": "bulk_update",
            "total": len(kwargs["items"]),
            "succeeded": len(kwargs["items"]),
            "failed": 0,
            "confirmed": kwargs["confirm"],
            "requires_confirmation": not kwargs["confirm"],
            "message": "ok",
            "items": [],
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("field", DATES)
async def test_update_work_package_hands_the_clear_sentinel_on_and_a_clear_alone_is_a_change(field: str) -> None:
    client = _RecordingClient()

    await update_work_package(FakeContext(client), "42", **{field: "none"}, confirm=False)  # type: ignore[arg-type]

    assert client.updates[0][field] is CLEAR


@pytest.mark.asyncio
async def test_bulk_update_items_clear_each_date_alone_and_mixed_with_a_date() -> None:
    client = _RecordingClient()

    await bulk_update_work_packages(
        FakeContext(client),  # type: ignore[arg-type]
        items=[
            {"work_package_id": 10, "start_date": "none"},
            {"work_package_id": 20, "due_date": " NoNe "},
            {"work_package_id": 30, "start_date": "none", "due_date": "2026-12-11"},
        ],
        confirm=False,
    )

    first, second, third = client.bulk_items
    assert (first["start_date"] is CLEAR, first["due_date"]) == (True, None)
    assert (second["start_date"], second["due_date"] is CLEAR) == (None, True)
    assert (third["start_date"] is CLEAR, third["due_date"]) == (True, "2026-12-11")


@pytest.mark.asyncio
async def test_a_bulk_update_item_with_a_non_text_date_is_refused_cleanly() -> None:
    with pytest.raises(ValueError, match=r"items\[0\]\.start_date must be YYYY-MM-DD format"):
        await bulk_update_work_packages(
            FakeContext(_RecordingClient()),  # type: ignore[arg-type]
            items=[{"work_package_id": 10, "start_date": 5}],
            confirm=False,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", DATES)
async def test_the_create_tools_still_refuse_none_for_the_dates(field: str) -> None:
    client = _RecordingClient()
    context = FakeContext(client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=f"{field} must be YYYY-MM-DD format"):
        await create_work_package(context, project="demo", type="Task", subject="S", **{field: "none"})
    with pytest.raises(ValueError, match=f"{field} must be YYYY-MM-DD format"):
        await create_subtask(context, parent_work_package_id=5, type="Task", subject="S", **{field: "none"})
    with pytest.raises(ValueError, match=f"{field} must be YYYY-MM-DD format"):
        await bulk_create_work_packages(
            context, items=[{"project": "demo", "type": "Task", "subject": "S", field: "none"}], confirm=False
        )
