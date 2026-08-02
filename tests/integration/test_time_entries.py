"""Integration tests for time entry CRUD operations."""

from __future__ import annotations

import dataclasses
import datetime
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from openproject_ce_mcp import tools
from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient

pytestmark = pytest.mark.integration


@dataclass
class _FakeAppContext:
    client: OpenProjectClient


class _FakeContext:
    """Minimal Context stand-in so a tools.py function can be exercised
    directly against a real client -- create_time_entry_until/
    update_time_entry_until are tools.py-layer only (they compute `hours`
    locally, then delegate to client.create_time_entry/update_time_entry),
    with no dedicated client.py method of their own to call directly, unlike
    every other time entry operation this file otherwise tests via `client`."""

    def __init__(self, client: OpenProjectClient) -> None:
        self.request_context = SimpleNamespace(lifespan_context=_FakeAppContext(client=client))


async def _first_activity_name(client: OpenProjectClient) -> str:
    activities = await client.list_time_entry_activities()
    if activities.count == 0:
        pytest.skip("Instance has no time entry activities configured")
    return activities.results[0].name


async def _first_wp_id(client: OpenProjectClient, test_project: str) -> int | None:
    result = await client.list_work_packages(project=test_project, limit=1)
    if result.count == 0:
        return None
    return result.results[0].id


async def test_list_time_entry_activities(client: OpenProjectClient) -> None:
    result = await client.list_time_entry_activities()
    assert result.count >= 0


async def test_list_time_entries(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_time_entries(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_create_get_update_delete_time_entry(
    client: OpenProjectClient, test_project: str, time_entry_ids: list[int]
) -> None:
    activity = await _first_activity_name(client)
    wp_id = await _first_wp_id(client, test_project)
    spent_on = datetime.date.today().isoformat()

    # Create
    result = await client.create_time_entry(
        activity=activity,
        hours="PT1H30M",
        spent_on=spent_on,
        project=test_project,
        work_package_id=wp_id,
        comment="Integration test time entry",
        confirm=True,
    )
    assert result.ready, result.validation_errors
    te_id = result.time_entry_id
    assert te_id > 0
    time_entry_ids.append(te_id)

    # Read
    te = await client.get_time_entry(te_id)
    assert te.id == te_id

    # Update
    update_result = await client.update_time_entry(
        time_entry_id=te_id,
        hours="PT2H",
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    # Delete
    delete_result = await client.delete_time_entry(time_entry_id=te_id, confirm=True)
    assert delete_result.ready and delete_result.confirmed
    time_entry_ids.remove(te_id)


async def test_create_get_update_time_entry_until(
    client: OpenProjectClient, test_project: str, time_entry_ids: list[int]
) -> None:
    """create_time_entry_until/update_time_entry_until compute `hours` from
    start_time/end_time locally and must never forward `end_time` itself to
    OpenProject (the server rejects it as a write field -- see the
    create_time_entry/update_time_entry `end_time` removal). Uses whole
    seconds throughout: OpenProject's own hours-to-ISO8601-duration API
    serialization truncates (not rounds) a fractional-second remainder --
    verified against a live instance: `hours` itself
    is stored with full float precision (confirmed via a direct DB read),
    but the response serializer builds `Duration.new(seconds: hours * 3600)`
    (the `ruby-duration` gem's own `Duration` class, not `ActiveSupport::
    Duration`/`ISO8601::Duration`), whose constructor does `args[:seconds]
    .to_i`, and Ruby's `Float#to_i` truncates toward zero. So a fractional
    end_time would not round-trip byte-identically through a subsequent read
    -- a server property, not something create_time_entry_until's own
    arithmetic could be wrong about, so not re-verified here.

    `hours` is always asserted -- it's this tool's own computed value,
    independent of instance configuration. `start_time`/`end_time` on the
    result are only asserted if the instance actually stored `start_time`
    (gated by its own "allow tracking of start and end times" setting,
    `TimeEntry.can_track_start_and_end_time?`); if that instance setting is
    off, OpenProject silently accepts and discards `startTime` rather than
    rejecting it, so start_time/end_time on the read-back result being None
    is expected instance behavior, not a bug in this test or in
    create_time_entry_until."""
    ctx = _FakeContext(client)  # type: ignore[arg-type]
    activity = await _first_activity_name(client)
    wp_id = await _first_wp_id(client, test_project)
    spent_on = datetime.date.today().isoformat()

    result = await tools.create_time_entry_until(
        ctx,
        activity=activity,
        start_time=f"{spent_on}T09:00:00Z",
        end_time=f"{spent_on}T10:30:00Z",
        spent_on=spent_on,
        project=test_project,
        work_package_id=wp_id,
        comment="Integration test time entry (until)",
        confirm=True,
    )
    assert result.ready, result.validation_errors
    te_id = result.time_entry_id
    assert te_id > 0
    time_entry_ids.append(te_id)
    assert result.result is not None
    assert result.result.hours == "PT1H30M"
    if result.result.start_time is None:
        pytest.skip("Instance does not have start/end time tracking enabled (start_time was silently discarded)")
    assert result.result.start_time == f"{spent_on}T09:00:00.000Z"
    assert result.result.end_time == f"{spent_on}T10:30:00.000Z"

    te = await client.get_time_entry(te_id)
    assert te.id == te_id
    assert te.hours == "PT1H30M"

    update_result = await tools.update_time_entry_until(
        ctx,
        time_entry_id=te_id,
        start_time=f"{spent_on}T09:00:00Z",
        end_time=f"{spent_on}T11:00:00Z",
        spent_on=spent_on,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors
    assert update_result.result is not None
    assert update_result.result.hours == "PT2H"
    assert update_result.result.end_time == f"{spent_on}T11:00:00.000Z"
    assert update_result.result.ongoing is False

    delete_result = await client.delete_time_entry(time_entry_id=te_id, confirm=True)
    assert delete_result.ready and delete_result.confirmed
    time_entry_ids.remove(te_id)


async def test_create_time_entry_until_rejects_end_time_before_start_time(
    client: OpenProjectClient, test_project: str
) -> None:
    ctx = _FakeContext(client)  # type: ignore[arg-type]
    activity = await _first_activity_name(client)
    wp_id = await _first_wp_id(client, test_project)
    spent_on = datetime.date.today().isoformat()

    with pytest.raises(ValueError, match="end_time must be after start_time"):
        await tools.create_time_entry_until(
            ctx,
            activity=activity,
            start_time=f"{spent_on}T10:30:00Z",
            end_time=f"{spent_on}T09:00:00Z",
            spent_on=spent_on,
            project=test_project,
            work_package_id=wp_id,
            confirm=False,
        )


async def test_create_time_entry_rejects_hidden_start_time_field(client: OpenProjectClient, test_project: str) -> None:
    """Regression: create_time_entry/update_time_entry's start_time/end_time
    were the only two time entry fields that bypassed the hidden-field
    write check every other field already had."""
    activity = await _first_activity_name(client)
    spent_on = datetime.date.today().isoformat()

    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"time_entry": ("start_time",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_TIME_ENTRY_FIELDS"):
        await hidden_client.create_time_entry(
            project=test_project,
            activity=activity,
            hours="PT1H",
            spent_on=spent_on,
            start_time="09:00",
            confirm=False,
        )


async def test_create_time_entry_preview_surfaces_openproject_validation_error(
    client: OpenProjectClient, test_project: str
) -> None:
    """Regression: create_time_entry/update_time_entry's preview always
    hardcoded ready=True instead of round-tripping through OpenProject's own
    form validation -- a payload that passes this server's own field checks
    (a well-formed activity name, a syntactically valid ISO8601 duration)
    could still be rejected by OpenProject's own form (e.g. an entity/work
    package requirement this server doesn't itself enforce), which the
    previous hardcoded preview could never surface."""
    activity = await _first_activity_name(client)
    spent_on = datetime.date.today().isoformat()

    result = await client.create_time_entry(
        project=test_project,
        activity=activity,
        hours="PT0H",
        spent_on=spent_on,
        confirm=False,
    )
    assert not result.ready
    assert result.validation_errors


async def test_create_time_entry_with_semantic_work_package_ref(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], time_entry_ids: list[int]
) -> None:
    activity = await _first_activity_name(client)
    spent_on = datetime.date.today().isoformat()

    wp_result = await client.create_work_package(
        project=test_project, type="Task", subject="Integration test WP for semantic time entry", confirm=True
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_id = wp_result.work_package_id
    assert wp_id is not None
    wp_ids.append(wp_id)
    wp = await client.get_work_package(wp_id)
    display_id = wp.display_id or ""
    # Semantic identifiers (project-prefixed, e.g. "TST-105") only exist on 17.5+
    # in semantic mode. On 16.x display_id is absent (added in 17.4); on classic
    # 17.x it's the numeric id as a string. Same detection as
    # test_semantic_identifiers.py::test_reference_resolution_matches_instance_mode.
    is_semantic = "-" in display_id and not display_id.isdigit()
    if not is_semantic:
        pytest.skip("instance is not in semantic identifier mode; nothing to resolve")

    # The numeric-HAL-link-from-semantic-ref resolution path (client.py
    # _work_package_ref) — passing the display_id string, not the numeric id.
    result = await client.create_time_entry(
        activity=activity,
        hours="PT1H",
        spent_on=spent_on,
        work_package_id=display_id,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    te_id = result.time_entry_id
    assert te_id > 0
    time_entry_ids.append(te_id)

    te = await client.get_time_entry(te_id)
    # entity_id is the proof that the semantic ref resolved to the right numeric
    # work package via the HAL entity link. entityType is not reliably present
    # on the live response (unlike the hand-built payloads in the unit tests),
    # so it isn't asserted here.
    assert te.entity_id == wp_id
