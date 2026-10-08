from __future__ import annotations

import pytest
from _tools_test_helpers import FakeContext

from openproject_ce_mcp.models import SortCriterion
from openproject_ce_mcp.tools import (
    _duration_between,
    _validate_positive_int,
    bulk_create_work_packages,
    bulk_update_work_packages,
    create_work_package_relation,
    create_work_package_reminder,
    toggle_activity_emoji_reaction,
)
from openproject_ce_mcp.tools_validation import (
    DATETIME_RE,
    ISO8601_DURATION_RE,
    _validate_custom_field_filters,
    _validate_group_by,
    _validate_optional_duration,
    _validate_optional_non_negative_int,
    _validate_optional_percentage_done,
    _validate_optional_target_versions,
    _validate_optional_text,
    _validate_optional_update_text,
    _validate_optional_user_ref,
    _validate_optional_work_package_ref,
    _validate_required_text,
    _validate_sort_by,
    _validate_work_package_ref,
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


def test_validate_optional_target_versions_none_passes_through() -> None:
    assert _validate_optional_target_versions(None) is None


def test_validate_optional_target_versions_valid_list() -> None:
    assert _validate_optional_target_versions(["1.0", "2.0"]) == ["1.0", "2.0"]


def test_validate_optional_target_versions_empty_list_passes_through() -> None:
    # [] is a meaningful, distinct signal (clear all), not an error.
    assert _validate_optional_target_versions([]) == []


def test_validate_optional_target_versions_rejects_non_list() -> None:
    with pytest.raises(ValueError, match="must be a list of strings"):
        _validate_optional_target_versions("1.0")  # type: ignore[arg-type]


def test_validate_optional_target_versions_rejects_empty_string_item() -> None:
    with pytest.raises(ValueError, match=r"target_versions\[1\] must not be empty"):
        _validate_optional_target_versions(["1.0", "  "])


def test_validate_optional_target_versions_rejects_over_length_cap() -> None:
    with pytest.raises(ValueError, match="must not exceed 20 entries"):
        _validate_optional_target_versions([str(i) for i in range(21)])


def test_validate_optional_target_versions_uses_given_field_name() -> None:
    with pytest.raises(ValueError, match="items\\[0\\].target_versions must be a list of strings"):
        _validate_optional_target_versions("1.0", field_name="items[0].target_versions")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_relation_tool_validates_relation_type() -> None:
    class StubClient:
        @property
        def relation(self):
            return self

        async def create(self, **kwargs):
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
        @property
        def emoji_reaction(self):
            return self

        async def toggle(self, activity_id, reaction):
            return {"activity_id": activity_id, "reaction": reaction}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="activity_id must be at least 1"):
        await toggle_activity_emoji_reaction(ctx, 0, "thumbs_up")
    with pytest.raises(ValueError, match="reaction is required"):
        await toggle_activity_emoji_reaction(ctx, 1, "")


@pytest.mark.asyncio
async def test_reminder_tools_validate_inputs() -> None:
    class StubClient:
        @property
        def reminder(self):
            return self

        async def create(self, **kwargs):
            return kwargs

        async def update(self, **kwargs):
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
        @property
        def work_package(self):
            return self

        async def bulk_create(self, **kwargs):
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
        @property
        def work_package(self):
            return self

        async def bulk_create(self, **kwargs):
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
async def test_bulk_create_work_packages_tool_rejects_unknown_item_field() -> None:
    # An unsupported item key must fail loudly (indexed error), not be
    # silently dropped.
    class StubClient:
        @property
        def work_package(self):
            return self

        async def bulk_create(self, **kwargs):
            raise AssertionError("must not reach the client when an item has an unknown field")

    with pytest.raises(ValueError, match=r"items\[0\] has unsupported field\(s\): totally_unknown_field"):
        await bulk_create_work_packages(  # type: ignore[arg-type]
            FakeContext(StubClient()),
            items=[{"project": "demo", "type": "Task", "subject": "X", "totally_unknown_field": "oops"}],
        )


@pytest.mark.asyncio
async def test_bulk_create_work_packages_tool_passes_duration_fields() -> None:
    # estimated_time/remaining_time/duration must survive validation and
    # reach the client, matching create_work_package's existing behavior.
    received: list = []

    class StubClient:
        @property
        def work_package(self):
            return self

        async def bulk_create(self, **kwargs):
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
                "estimated_time": "PT8H",
                "remaining_time": "PT4H",
                "duration": "P2D",
            },
        ],
        confirm=False,
    )

    assert received[0]["estimated_time"] == "PT8H"
    assert received[0]["remaining_time"] == "PT4H"
    assert received[0]["duration"] == "P2D"


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_validates_required_fields() -> None:
    class StubClient:
        @property
        def work_package(self):
            return self

        async def bulk_update(self, **kwargs):
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
async def test_bulk_update_work_packages_tool_rejects_unknown_item_field() -> None:
    # Same bug class as bulk_create's unknown-item-field validation, but for bulk_update: an unsupported
    # item key must fail loudly (indexed error), not be silently dropped.
    class StubClient:
        @property
        def work_package(self):
            return self

        async def bulk_update(self, **kwargs):
            raise AssertionError("must not reach the client when an item has an unknown field")

    with pytest.raises(ValueError, match=r"items\[0\] has unsupported field\(s\): totally_unknown_field"):
        await bulk_update_work_packages(  # type: ignore[arg-type]
            FakeContext(StubClient()),
            items=[{"work_package_id": 1, "totally_unknown_field": "oops"}],
        )


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_passes_validated_items() -> None:
    received: list = []

    class StubClient:
        @property
        def work_package(self):
            return self

        async def bulk_update(self, **kwargs):
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
    # OpenProject accepts day/week/month/year units and date+time combinations
    # and echoes them back unchanged.
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
    # "P1W2D" and "P2WT3H" are rejected by OpenProject itself ("Invalid format
    # for property... Expected format like 'ISO 8601 duration'") — the week
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


def test_validate_optional_duration_accepts_fractional_seconds() -> None:
    # Verified against the real `iso8601` Ruby gem OpenProject uses server-side
    # (ISO8601::Duration's grammar permits a decimal fraction on the seconds
    # atom) -- our own regex must accept what the server actually accepts,
    # not a narrower subset. Needed by create_time_entry_until/
    # update_time_entry_until's _duration_between, which can produce a
    # fractional-second remainder.
    assert _validate_optional_duration("PT7H30M15.5S", field_name="x") == "PT7H30M15.5S"
    assert _validate_optional_duration("PT10.4S", field_name="x") == "PT10.4S"
    assert _validate_optional_duration("PT0.5S", field_name="x") == "PT0.5S"


def test_validate_optional_duration_still_rejects_multiple_fractional_components() -> None:
    # The real gem's grammar (ISO8601::Duration#valid_fractions?) rejects more
    # than one fractional component -- our regex doesn't need to special-case
    # this (it only ever accepts a fraction on the seconds atom, H/M stay
    # integer-only), but this pins that the widened regex didn't accidentally
    # start accepting a second fractional component too.
    with pytest.raises(ValueError, match="must use a simple ISO 8601 duration"):
        _validate_optional_duration("PT1.5H30.5M", field_name="x")


class TestDurationBetween:
    def test_whole_hours(self) -> None:
        assert _duration_between("2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z") == "PT1H"

    def test_whole_minutes(self) -> None:
        assert _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:01:00Z") == "PT1M"

    def test_whole_seconds(self) -> None:
        assert _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:00:07Z") == "PT7S"

    def test_mixed_hours_minutes_seconds(self) -> None:
        assert _duration_between("2026-01-01T09:00:00Z", "2026-01-01T10:30:15Z") == "PT1H30M15S"

    def test_fractional_seconds(self) -> None:
        result = _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:00:07.5Z")
        assert result == "PT7.5S"
        assert bool(ISO8601_DURATION_RE.fullmatch(result))

    def test_sub_second_total_duration(self) -> None:
        result = _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:00:00.25Z")
        assert result == "PT0.25S"
        assert bool(ISO8601_DURATION_RE.fullmatch(result))

    def test_59_999999_seconds_carries_correctly_not_to_pt60s(self) -> None:
        # Regression: an earlier draft formatted the seconds remainder with
        # `%g`, which rounds to 6 significant digits and silently turned a
        # genuine 59.999999s remainder into "60" (PT60S) without carrying the
        # overflow into minutes. The fixed version must never emit "60" (or
        # higher) as the seconds component.
        result = _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:00:59.999999Z")
        assert result == "PT59.999999S"

    def test_result_always_matches_the_widened_duration_regex(self) -> None:
        cases = [
            ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00.000001Z"),  # 1 microsecond
            ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00.00001Z"),  # 10 microseconds
            ("2026-01-01T00:00:00Z", "2026-06-15T12:00:00Z"),  # multi-day
        ]
        for start, end in cases:
            result = _duration_between(start, end)
            assert bool(ISO8601_DURATION_RE.fullmatch(result)), f"{result!r} (from {start} -> {end}) failed the regex"

    def test_different_utc_offsets_including_dst_style_shift(self) -> None:
        # Different UTC offsets on start/end (e.g. a DST transition between
        # them) must be compared in absolute time, not rejected or misread.
        assert _duration_between("2026-01-01T10:00:00+01:00", "2026-01-01T10:00:00+00:00") == "PT1H"

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError, match="end_time must be after start_time"):
            _duration_between("2026-01-01T10:00:00Z", "2026-01-01T09:00:00Z")

    def test_end_equal_start_raises(self) -> None:
        with pytest.raises(ValueError, match="end_time must be after start_time"):
            _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:00:00Z")

    def test_datetime_re_rejects_more_than_microsecond_precision(self) -> None:
        # Regression: DATETIME_RE previously accepted an unlimited number of
        # fractional-second digits, but datetime.fromisoformat() (used by
        # _duration_between) silently truncates anything beyond 6 (microsecond
        # precision) -- e.g. two distinct 7-digit inputs a nanosecond apart
        # would parse to the identical microsecond value and _duration_between
        # would wrongly compute a zero (or otherwise inaccurate) duration
        # despite its "exact duration" contract. DATETIME_RE must reject what
        # fromisoformat can't represent exactly, rather than silently
        # accepting and mis-rounding it.
        assert DATETIME_RE.fullmatch("2026-01-01T09:00:00.123456Z")
        assert not DATETIME_RE.fullmatch("2026-01-01T09:00:00.1234567Z")

    def test_accepts_non_3_or_6_digit_fractional_seconds(self) -> None:
        # Regression: DATETIME_RE (and OpenProject itself) allow any count of
        # 1-6 fractional-second digits, not just 0/3/6 -- confirms
        # _duration_between's direct fromisoformat call (no pre-padding)
        # correctly handles a non-3/6-digit fraction like "07.5Z" or
        # "00.00001Z" rather than raising ValueError.
        assert _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:00:07.5Z") == "PT7.5S"
        assert _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:00:00.25Z") == "PT0.25S"
        assert _duration_between("2026-01-01T09:00:00Z", "2026-01-01T09:00:00.00001Z") == "PT0.00001S"


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
        CapabilityDisabledError,
        ConflictError,
        InvalidInputError,
        NotFoundError,
        OpenProjectPermissionDeniedError,
        OpenProjectServerError,
        ProjectScopeDeniedError,
        RateLimitedError,
        TransportError,
    )
    from openproject_ce_mcp.tools_runtime import _run_tool

    async def raiser(exc):
        raise exc

    # Validation failures stay ValueError with a [VALIDATION_FAILED] prefix.
    with pytest.raises(ValueError, match=r"^\[VALIDATION_FAILED\] bad"):
        await _run_tool(raiser(InvalidInputError("bad")))

    # Every other category is a RuntimeError with its own prefix.
    cases = {
        AuthenticationError("x"): "AUTHENTICATION_FAILED",
        ProjectScopeDeniedError("x"): "PROJECT_SCOPE_DENIED",
        CapabilityDisabledError("x"): "CAPABILITY_DISABLED",
        OpenProjectPermissionDeniedError("x"): "OPENPROJECT_PERMISSION_DENIED",
        NotFoundError("x"): "RESOURCE_NOT_FOUND",
        ConflictError("x"): "CONFLICT",
        RateLimitedError("x"): "RATE_LIMITED",
        TransportError("x"): "NETWORK_ERROR",
        OpenProjectServerError("x"): "OPENPROJECT_UNAVAILABLE",
    }
    for exc, category in cases.items():
        with pytest.raises(RuntimeError, match=rf"^\[{category}\] "):
            await _run_tool(raiser(exc))


@pytest.mark.asyncio
async def test_categorize_tool_errors_tags_validation_and_avoids_double_prefix() -> None:
    from openproject_ce_mcp.tools_runtime import _categorize_tool_errors

    @_categorize_tool_errors
    async def raw_validation(_ctx):
        raise ValueError("subject is required")

    with pytest.raises(ValueError, match=r"^\[VALIDATION_FAILED\] subject is required$"):
        await raw_validation(None)

    # A message already prefixed with THIS SAME category must not be
    # prefixed twice.
    @_categorize_tool_errors
    async def already_tagged(_ctx):
        raise ValueError("[VALIDATION_FAILED] subject already validated upstream")

    with pytest.raises(ValueError, match=r"^\[VALIDATION_FAILED\] subject already validated upstream$"):
        await already_tagged(None)


@pytest.mark.asyncio
async def test_categorize_tool_errors_does_not_treat_a_foreign_bracket_tag_as_already_categorized() -> None:
    """Regression: a tool-body validator's raw ValueError message can echo
    back caller-supplied text (a custom field key, a filter value). A prior,
    looser implementation of _prefix treated ANY leading
    `[UPPERCASE_WORD] ` bracket token as "already categorized" and skipped
    prefixing -- if that echoed-back text happened to look like a different
    category tag (e.g. "[RESOURCE_NOT_FOUND] ..."), the real
    VALIDATION_FAILED category was silently dropped from the message the
    agent actually sees, even though the separate structured log still
    correctly recorded VALIDATION_FAILED -- an inconsistency, and a
    misleading category, an agent could be steered into by crafting input
    that happens to look like a different error tag."""
    from openproject_ce_mcp.tools_runtime import _categorize_tool_errors

    @_categorize_tool_errors
    async def raw_validation_with_foreign_looking_tag(_ctx):
        raise ValueError("[RESOURCE_NOT_FOUND] the field you gave does not exist")

    with pytest.raises(
        ValueError, match=r"^\[VALIDATION_FAILED\] \[RESOURCE_NOT_FOUND\] the field you gave does not exist$"
    ):
        await raw_validation_with_foreign_looking_tag(None)


@pytest.mark.asyncio
async def test_categorize_tool_errors_sanitizes_unexpected_exceptions() -> None:
    """An unexpected bug (bare KeyError/AttributeError/etc, not a typed
    OpenProjectError) must never leak its own message to the client -- only
    a generic [INTERNAL_ERROR] text, with the real exception logged locally
    (via `from exc`, verified separately) but never serialized outward."""
    from openproject_ce_mcp.tools_runtime import _categorize_tool_errors

    @_categorize_tool_errors
    async def buggy(_ctx):
        raise KeyError("secret_internal_value_12345")

    with pytest.raises(RuntimeError, match=r"^\[INTERNAL_ERROR\] An internal error occurred\.$") as exc_info:
        await buggy(None)
    assert "secret_internal_value_12345" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, KeyError)


@pytest.mark.asyncio
async def test_categorize_tool_errors_does_not_swallow_cancelled_error() -> None:
    """asyncio.CancelledError (a BaseException, not an Exception) must
    propagate through the sanitization catch-all untouched -- `except
    Exception`, never bare `except:`."""
    import asyncio

    from openproject_ce_mcp.tools_runtime import _categorize_tool_errors

    @_categorize_tool_errors
    async def cancelled(_ctx):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await cancelled(None)


@pytest.mark.asyncio
async def test_categorize_tool_errors_reclassifies_uncoded_openproject_error() -> None:
    """An OpenProjectError reaching _categorize_tool_errors directly (a tool
    body calling a raising API without going through _run_tool) must still
    get its own real code, not fall through to the generic INTERNAL_ERROR
    sanitization path."""
    from openproject_ce_mcp.client import NotFoundError
    from openproject_ce_mcp.tools_runtime import _categorize_tool_errors

    @_categorize_tool_errors
    async def raw_not_found(_ctx):
        raise NotFoundError("gone")

    with pytest.raises(RuntimeError, match=r"^\[RESOURCE_NOT_FOUND\] gone$"):
        await raw_not_found(None)


@pytest.mark.asyncio
async def test_categorize_tool_errors_sanitizes_an_uncoded_runtime_error() -> None:
    """Regression: a plain RuntimeError NOT produced by
    _categorize_openproject_error (a real bug in tool/library code that
    happens to raise this built-in type, e.g. a bare `raise RuntimeError(...)`
    somewhere, or a third-party library's own RuntimeError) has no `.code`/
    `.layer` attributes and must be sanitized like any other unexpected
    exception -- not re-raised verbatim, which would leak its raw message
    (a real information-disclosure risk: the message could contain an
    internal path, host, or other implementation detail) to the MCP client."""
    from openproject_ce_mcp.tools_runtime import _categorize_tool_errors

    @_categorize_tool_errors
    async def uncoded_runtime_error(_ctx):
        raise RuntimeError("internal path /etc/secrets/config.yaml, host=10.0.0.5")

    with pytest.raises(RuntimeError, match=r"^\[INTERNAL_ERROR\] An internal error occurred\.$") as exc_info:
        await uncoded_runtime_error(None)
    assert "/etc/secrets" not in str(exc_info.value)
    assert "10.0.0.5" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_validate_sort_by_accepts_real_sortable_columns() -> None:
    # These column identifiers are what GET /work_packages?sortBy= actually
    # accepts (cross-checked against OpenProject's own query
    # property/project-phase select definitions), not a guess at plausible names.
    criteria = _validate_sort_by(["status:desc", "assigned_to", "assignee:asc", "cf_5:desc"])
    assert criteria == [
        SortCriterion(field="status", direction="desc"),
        SortCriterion(field="assigned_to", direction="asc"),
        SortCriterion(field="assignee", direction="asc"),
        SortCriterion(field="cf_5", direction="desc"),
    ]


def test_validate_sort_by_rejects_unknown_field_with_valid_list() -> None:
    # "spent_hours" and "due_date" both round-trip syntax
    # validation (alphanumeric+underscore) but OpenProject itself rejects
    # spent_hours for sorting ("Can't sort by column: spent_hours") -- catching
    # this locally with the real allowed set beats a guessed plausible name
    # only failing after a round trip to the server. "assignedto" (no
    # underscore) is a plausible-but-wrong guess that should also be rejected.
    with pytest.raises(ValueError, match=r"unknown field 'spent_hours'.*Valid fields are: "):
        _validate_sort_by(["spent_hours"])
    with pytest.raises(ValueError, match="unknown field 'assignedto'"):
        _validate_sort_by(["assignedto:asc"])


def test_validate_group_by_accepts_real_groupable_columns() -> None:
    assert _validate_group_by("status") == "status"
    assert _validate_group_by("assigned_to") == "assigned_to"
    assert _validate_group_by("cf_5") == "cf_5"
    assert _validate_group_by(None) is None


def test_validate_group_by_rejects_sortable_but_not_groupable_field() -> None:
    # due_date/estimated_hours/estimated_time/created_at/
    # updated_at/duration/start_date all sort fine but OpenProject rejects
    # them for groupBy ("Can't group by: due_date") -- property_select.rb
    # confirms none of them declare a `groupable:` column. This is exactly
    # the class of error the ticket wants caught locally instead of only
    # surfacing via OpenProject's own remote error.
    with pytest.raises(ValueError, match=r"unknown field 'due_date'.*Valid fields are: "):
        _validate_group_by("due_date")
    with pytest.raises(ValueError, match="unknown field 'estimated_time'"):
        _validate_group_by("estimated_time")


# --- _validate_custom_field_filters -------------------------------


def test_validate_custom_field_filters_none_passes_through() -> None:
    assert _validate_custom_field_filters(None) is None


def test_validate_custom_field_filters_accepts_cf_key_unchanged() -> None:
    result = _validate_custom_field_filters({"cf_12": {"operator": "=", "values": ["42"]}})
    assert result == {"cf_12": {"operator": "=", "values": ["42"]}}


def test_validate_custom_field_filters_normalizes_customfield_key() -> None:
    # customField<N> is CustomField#attribute_name(:camel_case), the JSON/PATCH
    # key -- cf_<N> is CustomField#column_name, the real OpenProject filter
    # key. Both are accepted transparently and always normalized to cf_<N>.
    result = _validate_custom_field_filters({"customField7": {"operator": "~", "values": ["Acme"]}})
    assert result == {"cf_7": {"operator": "~", "values": ["Acme"]}}


@pytest.mark.parametrize(
    "bad_key",
    ["story_points", "cf_abc", "CustomField7", "cf_0", "cf_01", "customfield7", "cf_-1", ""],
)
def test_validate_custom_field_filters_rejects_invalid_key_shape(bad_key: str) -> None:
    with pytest.raises(ValueError, match="must be of the form"):
        _validate_custom_field_filters({bad_key: {"operator": "=", "values": ["1"]}})


def test_validate_custom_field_filters_rejects_cf_and_customfield_collision() -> None:
    with pytest.raises(ValueError, match="both resolve to 'cf_5'"):
        _validate_custom_field_filters(
            {
                "cf_5": {"operator": "=", "values": ["1"]},
                "customField5": {"operator": "=", "values": ["2"]},
            }
        )


def test_validate_custom_field_filters_rejects_non_dict_value() -> None:
    with pytest.raises(ValueError, match="must be an object with 'operator' and 'values'"):
        _validate_custom_field_filters({"cf_1": "not-a-dict"})  # type: ignore[dict-item]


def test_validate_custom_field_filters_rejects_missing_operator_or_values() -> None:
    with pytest.raises(ValueError, match="must be an object with 'operator' and 'values'"):
        _validate_custom_field_filters({"cf_1": {"operator": "="}})
    with pytest.raises(ValueError, match="must be an object with 'operator' and 'values'"):
        _validate_custom_field_filters({"cf_1": {"values": ["1"]}})


def test_validate_custom_field_filters_rejects_unsupported_extra_keys() -> None:
    with pytest.raises(ValueError, match="unsupported key"):
        _validate_custom_field_filters({"cf_1": {"operator": "=", "values": ["1"], "extra": True}})


def test_validate_custom_field_filters_rejects_unknown_operator() -> None:
    with pytest.raises(ValueError, match="not a recognized custom-field filter operator"):
        _validate_custom_field_filters({"cf_1": {"operator": "LIKE", "values": ["1"]}})


def test_validate_custom_field_filters_rejects_non_string_values_list() -> None:
    with pytest.raises(ValueError, match="values must be a list of strings"):
        _validate_custom_field_filters({"cf_1": {"operator": "=", "values": [1, 2]}})
    with pytest.raises(ValueError, match="values must be a list of strings"):
        _validate_custom_field_filters({"cf_1": {"operator": "=", "values": "not-a-list"}})


def test_validate_custom_field_filters_operator_with_no_values_allowed() -> None:
    # "*"/"!*" operators take no values (e.g. AllAndNonBlank/NoneOrBlank) --
    # an empty list must be accepted, not rejected as "missing".
    result = _validate_custom_field_filters({"cf_9": {"operator": "!*", "values": []}})
    assert result == {"cf_9": {"operator": "!*", "values": []}}


def test_validate_custom_field_filters_rejects_too_many_entries() -> None:
    too_many = {f"cf_{i}": {"operator": "=", "values": ["1"]} for i in range(1, 22)}
    with pytest.raises(ValueError, match="at most 20 entries"):
        _validate_custom_field_filters(too_many)


def test_validate_custom_field_filters_rejects_too_many_values() -> None:
    with pytest.raises(ValueError, match="at most 100 items"):
        _validate_custom_field_filters({"cf_1": {"operator": "=", "values": [str(i) for i in range(101)]}})


def test_validate_custom_field_filters_rejects_overlong_value() -> None:
    with pytest.raises(ValueError, match="at most 1000 characters"):
        _validate_custom_field_filters({"cf_1": {"operator": "=", "values": ["x" * 1001]}})


def test_validate_custom_field_filters_rejects_not_a_dict() -> None:
    with pytest.raises(ValueError, match="must be an object mapping"):
        _validate_custom_field_filters([1, 2, 3])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "validator",
    [_validate_optional_text, _validate_optional_update_text, _validate_required_text],
)
def test_text_validators_accept_any_length_when_max_length_is_none(validator) -> None:
    long_text = "x" * 250_000
    assert validator(long_text, field_name="description", max_length=None) == long_text


@pytest.mark.parametrize(
    "validator",
    [_validate_optional_text, _validate_optional_update_text, _validate_required_text],
)
def test_text_validators_keep_enforcing_a_fixed_cap(validator) -> None:
    with pytest.raises(ValueError, match=r"^title must be at most 3 characters\.$"):
        validator("abcd", field_name="title", max_length=3)


def test_custom_fields_string_values_are_not_length_limited() -> None:
    from openproject_ce_mcp.tools_validation import _validate_optional_custom_fields

    long_value = " " + "y" * 60_000 + " "
    assert _validate_optional_custom_fields({"Notes": long_value, "Tags": [long_value]}) == {
        "Notes": long_value.strip(),
        "Tags": [long_value.strip()],
    }


def test_board_query_json_strings_keep_a_fixed_cap() -> None:
    from openproject_ce_mcp.tools_validation import BOARD_JSON_STRING_MAX, _validate_optional_filter_list

    assert BOARD_JSON_STRING_MAX == 10_000
    at_cap = "x" * BOARD_JSON_STRING_MAX
    assert _validate_optional_filter_list([{"status": at_cap}]) == [{"status": at_cap}]
    with pytest.raises(ValueError, match=r"filters string values must be at most 10000 characters\.$"):
        _validate_optional_filter_list([{"status": at_cap + "x"}])


def test_select_wrapper_field_constants_match_the_item_models() -> None:
    from dataclasses import fields

    from openproject_ce_mcp.models import BatchWorkPackageReadItemResult, BulkWorkPackageItemResult
    from openproject_ce_mcp.tools_validation import BATCH_READ_ITEM_WRAPPER_FIELDS, BULK_ITEM_WRAPPER_FIELDS

    assert BULK_ITEM_WRAPPER_FIELDS == {f.name for f in fields(BulkWorkPackageItemResult)} - {"result"}
    assert BATCH_READ_ITEM_WRAPPER_FIELDS == {f.name for f in fields(BatchWorkPackageReadItemResult)} - {"work_package"}


def test_validate_select_accepts_wrapper_fields_without_returning_them() -> None:
    from openproject_ce_mcp.models import WorkPackageWriteResult
    from openproject_ce_mcp.tools_validation import BULK_ITEM_WRAPPER_FIELDS, _validate_select

    assert _validate_select(
        ["index", "ready", "success"], row_type=WorkPackageWriteResult, wrapper_fields=BULK_ITEM_WRAPPER_FIELDS
    ) == ["ready"]
    assert _validate_select(["index"], row_type=WorkPackageWriteResult, wrapper_fields=BULK_ITEM_WRAPPER_FIELDS) == []
    with pytest.raises(ValueError, match="not a valid WorkPackageWriteResult field"):
        _validate_select(["index"], row_type=WorkPackageWriteResult)


def _validate_bulk_select(select: list[str]) -> list[str] | None:
    from openproject_ce_mcp.models import WorkPackageDetail, WorkPackageWriteResult
    from openproject_ce_mcp.tools_validation import BULK_ITEM_WRAPPER_FIELDS, _validate_select

    return _validate_select(
        select,
        row_type=WorkPackageWriteResult,
        wrapper_fields=BULK_ITEM_WRAPPER_FIELDS,
        nested={"result": WorkPackageDetail},
    )


def test_validate_select_accepts_a_path_into_the_nested_entity() -> None:
    assert _validate_bulk_select(["work_package_id", "result.status", "project", "result.project"]) == [
        "work_package_id",
        "result.status",
        "project",
        "result.project",
    ]


def test_validate_select_names_the_path_for_a_bare_nested_field() -> None:
    with pytest.raises(
        ValueError, match=r"'subject' is a field of the WorkPackageDetail in 'result'; select it as 'result\.subject'"
    ):
        _validate_bulk_select(["work_package_id", "subject"])


def test_validate_select_lists_prefixed_names_for_an_unknown_nested_field() -> None:
    with pytest.raises(
        ValueError, match=r"'result\.bogus' is not a valid result field\. Allowed: .*result\.status, result\.subject"
    ):
        _validate_bulk_select(["result.bogus"])


def test_validate_select_rejects_a_path_deeper_than_one_level() -> None:
    with pytest.raises(ValueError, match=r"'result\.custom_fields\.x' is not a valid result field"):
        _validate_bulk_select(["result.custom_fields.x"])


def test_validate_select_mentions_the_path_syntax_for_an_unknown_name() -> None:
    with pytest.raises(
        ValueError,
        match=r"not a valid WorkPackageWriteResult field\..*Fields of 'result' are selected as 'result\.<field>'",
    ):
        _validate_bulk_select(["bogus"])


@pytest.mark.parametrize("name", ["work_package.subject", "result.subject"])
def test_validate_select_without_nested_entities_rejects_paths(name: str) -> None:
    from openproject_ce_mcp.models import WorkPackageDetail
    from openproject_ce_mcp.tools_validation import BATCH_READ_ITEM_WRAPPER_FIELDS, _validate_select

    with pytest.raises(ValueError, match=f"'{name}' is not a valid WorkPackageDetail field"):
        _validate_select([name], row_type=WorkPackageDetail, wrapper_fields=BATCH_READ_ITEM_WRAPPER_FIELDS)
