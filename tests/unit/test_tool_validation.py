from __future__ import annotations

import pytest
from _tools_test_helpers import FakeContext

from openproject_ce_mcp.tools import (
    _validate_optional_duration,
    _validate_optional_non_negative_int,
    _validate_optional_percentage_done,
    _validate_optional_text,
    _validate_optional_update_text,
    _validate_optional_user_ref,
    _validate_optional_work_package_ref,
    _validate_positive_int,
    _validate_required_text,
    _validate_work_package_ref,
    bulk_create_work_packages,
    bulk_update_work_packages,
    create_work_package_relation,
    create_work_package_reminder,
    toggle_activity_emoji_reaction,
)


def test_validate_optional_user_ref_reports_the_given_field_name() -> None:
    # An invalid value must name the field the caller actually passed, so the
    # error for a bad `responsible` does not mislead the caller to fix `assignee`.
    with pytest.raises(ValueError, match="assignee: 'me' or numeric user id"):
        _validate_optional_user_ref("bob")
    with pytest.raises(ValueError, match="responsible: 'me' or numeric user id"):
        _validate_optional_user_ref("bob", field_name="responsible")
    with pytest.raises(ValueError, match="responsible must be at least 1"):
        _validate_optional_user_ref("0", field_name="responsible")
    assert _validate_optional_user_ref("me", field_name="responsible") == "me"


@pytest.mark.asyncio
async def test_create_relation_tool_validates_relation_type() -> None:
    class StubClient:
        async def create_work_package_relation(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match="relation_type must be one of"):
        await create_work_package_relation(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            42,
            55,
            "invalid",
        )


@pytest.mark.asyncio
async def test_toggle_emoji_reaction_validates_inputs() -> None:
    class StubClient:
        async def toggle_activity_emoji_reaction(self, activity_id, reaction):
            return {"activity_id": activity_id, "reaction": reaction}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="activity_id must be at least 1"):
        await toggle_activity_emoji_reaction(ctx, 0, "thumbs_up")
    with pytest.raises(ValueError, match="reaction is required"):
        await toggle_activity_emoji_reaction(ctx, 1, "")


@pytest.mark.asyncio
async def test_reminder_tools_validate_inputs() -> None:
    class StubClient:
        async def create_work_package_reminder(self, **kwargs):
            return kwargs

        async def update_reminder(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="remind_at must be an ISO 8601 date-time"):
        await create_work_package_reminder(ctx, "5", "2026-12-01", confirm=True)
    with pytest.raises(ValueError, match="remind_at is required"):
        await create_work_package_reminder(ctx, "5", "", confirm=True)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bulk_create_work_packages_tool_validates_required_fields() -> None:
    class StubClient:
        async def bulk_create_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match="items must not be empty"):
        await bulk_create_work_packages(FakeContext(StubClient()), items=[])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=r"items\[0\].project is required"):
        await bulk_create_work_packages(FakeContext(StubClient()), items=[{"type": "Task", "subject": "X"}])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=r"items\[0\].type is required"):
        await bulk_create_work_packages(FakeContext(StubClient()), items=[{"project": "demo", "subject": "X"}])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=r"items\[0\].subject is required"):
        await bulk_create_work_packages(FakeContext(StubClient()), items=[{"project": "demo", "type": "Task"}])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=r"items\[0\].parent_work_package_id must be at least 1"):
        await bulk_create_work_packages(  # type: ignore[arg-type]
            FakeContext(StubClient()),
            items=[{"project": "demo", "type": "Task", "subject": "X", "parent_work_package_id": 0}],
        )


@pytest.mark.asyncio
async def test_bulk_create_work_packages_tool_passes_validated_items() -> None:
    received: list = []

    class StubClient:
        async def bulk_create_work_packages(self, **kwargs):
            received.extend(kwargs["items"])
            return {
                "action": "bulk_create",
                "total": len(kwargs["items"]),
                "succeeded": len(kwargs["items"]),
                "failed": 0,
                "confirmed": kwargs["confirm"],
                "requires_confirmation": not kwargs["confirm"],
                "message": "ok",
                "items": [],
            }

    await bulk_create_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        items=[
            {
                "project": "demo",
                "type": "Task",
                "subject": "WP 1",
                "start_date": "2026-01-01",
                "parent_work_package_id": 7,
            },
            {"project": "demo", "type": "Feature", "subject": "WP 2"},
        ],
        confirm=False,
    )

    assert len(received) == 2
    assert received[0]["project"] == "demo"
    assert received[0]["subject"] == "WP 1"
    assert received[0]["start_date"] == "2026-01-01"
    # Normalized to a string ref by _validate_optional_work_package_ref.
    assert received[0]["parent_work_package_id"] == "7"
    assert received[1]["type"] == "Feature"


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_validates_required_fields() -> None:
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match="items must not be empty"):
        await bulk_update_work_packages(FakeContext(StubClient()), items=[])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=r"items\[0\].work_package_id is required"):
        await bulk_update_work_packages(FakeContext(StubClient()), items=[{"subject": "X"}])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=r"items\[0\]: at least one field to update is required"):
        await bulk_update_work_packages(FakeContext(StubClient()), items=[{"work_package_id": 1}])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="use internal id.*or display_id"):
        await bulk_update_work_packages(  # type: ignore[arg-type]
            FakeContext(StubClient()),
            items=[{"work_package_id": 1, "parent_work_package_id": -1}],
        )

    with pytest.raises(ValueError, match="must use a simple ISO 8601 duration"):
        await bulk_update_work_packages(  # type: ignore[arg-type]
            FakeContext(StubClient()),
            items=[{"work_package_id": 1, "estimated_time": "bogus"}],
        )


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_passes_validated_items() -> None:
    received: list = []

    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            received.extend(kwargs["items"])
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

    await bulk_update_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        items=[
            {
                "work_package_id": 10,
                "subject": "New title",
                "status": "In progress",
                "parent_work_package_id": 30,
                "estimated_time": "PT8H",
                "remaining_time": "PT3H",
                "duration": "PT10H",
                "percentage_done": 40,
            },
            {"work_package_id": 20, "due_date": "2026-12-31"},
        ],
        confirm=True,
    )

    assert len(received) == 2
    # Ids normalized to string refs by _validate_work_package_ref.
    assert received[0]["work_package_id"] == "10"
    assert received[0]["subject"] == "New title"
    assert received[0]["status"] == "In progress"
    assert received[0]["parent_work_package_id"] == "30"
    assert received[0]["estimated_time"] == "PT8H"
    assert received[0]["remaining_time"] == "PT3H"
    assert received[0]["duration"] == "PT10H"
    assert received[0]["percentage_done"] == 40
    assert received[1]["work_package_id"] == "20"
    assert received[1]["due_date"] == "2026-12-31"


def test_validate_optional_duration_accepts_date_part_units() -> None:
    # Live-verified 2026-07-17 against real OpenProject 16.6 (Docker harness):
    # day/week/month/year units and date+time combinations are accepted and
    # echoed back unchanged, contrary to the regex's former PT-only restriction.
    assert _validate_optional_duration("P1D", field_name="x") == "P1D"
    assert _validate_optional_duration("P2W", field_name="x") == "P2W"
    assert _validate_optional_duration("P1Y", field_name="x") == "P1Y"
    assert _validate_optional_duration("P1M", field_name="x") == "P1M"
    assert _validate_optional_duration("P1Y2M3D", field_name="x") == "P1Y2M3D"
    assert _validate_optional_duration("P1Y2M3DT4H5M6S", field_name="x") == "P1Y2M3DT4H5M6S"
    assert _validate_optional_duration("P1DT18H", field_name="x") == "P1DT18H"
    # Time-only forms (the original supported shape) still work.
    assert _validate_optional_duration("PT8H", field_name="x") == "PT8H"
    assert _validate_optional_duration("PT1H30M", field_name="x") == "PT1H30M"


def test_validate_optional_duration_rejects_week_combined_with_other_units() -> None:
    # Live-verified 2026-07-17 against real OpenProject 16.6: "P1W2D" and
    # "P2WT3H" are rejected by OpenProject itself ("Invalid format for
    # property... Expected format like 'ISO 8601 duration'") — the week
    # designator cannot combine with any other designator, per the ISO 8601
    # standard's own week-format rule. The regex must reject these locally
    # too, not silently accept something OpenProject itself refuses.
    for bad in ("P1W2D", "P2WT3H", "P1YW", "P1W1Y"):
        with pytest.raises(ValueError, match="must use a simple ISO 8601 duration"):
            _validate_optional_duration(bad, field_name="x")


def test_validate_optional_duration_rejects_malformed() -> None:
    for bad in ("P", "PT", "PY", "P1", "1D", "PD1", "P1X"):
        with pytest.raises(ValueError, match="must use a simple ISO 8601 duration"):
            _validate_optional_duration(bad, field_name="x")


def test_validate_work_package_ref_accepts_numeric_and_semantic() -> None:
    assert _validate_work_package_ref(42) == "42"
    assert _validate_work_package_ref("42") == "42"
    assert _validate_work_package_ref("PROJ-123") == "PROJ-123"
    # Surrounding whitespace is normalized.
    assert _validate_work_package_ref("  PROJ-7  ") == "PROJ-7"


def test_validate_work_package_ref_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="work_package_id is required"):
        _validate_work_package_ref("   ")
    with pytest.raises(ValueError, match="use internal id.*or display_id"):
        _validate_work_package_ref("PROJ/123")
    with pytest.raises(ValueError, match="use internal id.*or display_id"):
        _validate_work_package_ref("PROJ 123")
    with pytest.raises(ValueError, match="use internal id.*or display_id"):
        # A project identifier without a "-<number>" suffix is not a work package ref.
        _validate_work_package_ref("PROJ")


def test_validate_positive_int_is_type_safe() -> None:
    # A wrong JSON type must raise a clean ValueError, not a raw TypeError.
    for bad in ("5", "abc", None, True, False, 1.5):
        with pytest.raises(ValueError, match="must be an integer"):
            _validate_positive_int(bad, field_name="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be at least 1"):
        _validate_positive_int(0, field_name="x")
    assert _validate_positive_int(5, field_name="x") == 5


def test_validate_optional_non_negative_int_is_type_safe() -> None:
    assert _validate_optional_non_negative_int(None, field_name="x") is None
    for bad in ("0", "abc", True, 1.5):
        with pytest.raises(ValueError, match="must be an integer"):
            _validate_optional_non_negative_int(bad, field_name="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be at least 0"):
        _validate_optional_non_negative_int(-1, field_name="x")
    assert _validate_optional_non_negative_int(0, field_name="x") == 0


def test_validate_optional_percentage_done_is_type_safe_and_range_checked() -> None:
    assert _validate_optional_percentage_done(None) is None
    for bad in (True, 1.5, "50"):
        with pytest.raises(ValueError, match="must be an integer"):
            _validate_optional_percentage_done(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be between 0 and 100"):
        _validate_optional_percentage_done(-1)
    with pytest.raises(ValueError, match="must be between 0 and 100"):
        _validate_optional_percentage_done(101)
    assert _validate_optional_percentage_done(0) == 0
    assert _validate_optional_percentage_done(100) == 100


def test_validate_optional_text_still_collapses_empty_string_to_none() -> None:
    # Regression guard: create-tool semantics are intentionally unchanged by the
    # update-only clearing fix — an explicit "" still means "not provided".
    assert _validate_optional_text("", field_name="description", max_length=10) is None
    assert _validate_optional_text("   ", field_name="description", max_length=10) is None
    assert _validate_optional_text(None, field_name="description", max_length=10) is None
    assert _validate_optional_text("hi", field_name="description", max_length=10) == "hi"


def test_validate_optional_update_text_preserves_empty_string() -> None:
    assert _validate_optional_update_text("", field_name="description", max_length=10) == ""
    assert _validate_optional_update_text("   ", field_name="description", max_length=10) == ""
    assert _validate_optional_update_text(None, field_name="description", max_length=10) is None
    assert _validate_optional_update_text("hi", field_name="description", max_length=10) == "hi"
    with pytest.raises(ValueError, match="must be at most 10 characters"):
        _validate_optional_update_text("way too long a value", field_name="description", max_length=10)


def test_validate_required_text_still_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="comment is required"):
        _validate_required_text("", field_name="comment", max_length=100)
    with pytest.raises(ValueError, match="comment is required"):
        _validate_required_text("   ", field_name="comment", max_length=100)


def test_validate_optional_work_package_ref_passes_through_none() -> None:
    assert _validate_optional_work_package_ref(None) is None
    assert _validate_optional_work_package_ref("PROJ-9") == "PROJ-9"


@pytest.mark.asyncio
async def test_run_tool_prefixes_client_error_categories() -> None:
    from openproject_ce_mcp.client import (
        AuthenticationError,
        InvalidInputError,
        NotFoundError,
        PermissionDeniedError,
        TransportError,
    )
    from openproject_ce_mcp.tools import _run_tool

    async def raiser(exc):
        raise exc

    # Validation failures stay ValueError with a [validation_error] prefix.
    with pytest.raises(ValueError, match=r"^\[validation_error\] bad"):
        await _run_tool(raiser(InvalidInputError("bad")))

    # Every other category is a RuntimeError with its own prefix.
    cases = {
        AuthenticationError("x"): "auth_error",
        PermissionDeniedError("x"): "permission_denied",
        NotFoundError("x"): "not_found",
        TransportError("x"): "transport_error",
    }
    for exc, category in cases.items():
        with pytest.raises(RuntimeError, match=rf"^\[{category}\] "):
            await _run_tool(raiser(exc))


@pytest.mark.asyncio
async def test_categorize_tool_errors_tags_validation_and_avoids_double_prefix() -> None:
    from openproject_ce_mcp.tools import _categorize_tool_errors

    @_categorize_tool_errors
    async def raw_validation(_ctx):
        raise ValueError("subject is required")

    with pytest.raises(ValueError, match=r"^\[validation_error\] subject is required$"):
        await raw_validation(None)

    # An already-categorized message must not be prefixed twice.
    @_categorize_tool_errors
    async def already_tagged(_ctx):
        raise ValueError("[not_found] gone")

    with pytest.raises(ValueError, match=r"^\[not_found\] gone$"):
        await already_tagged(None)
