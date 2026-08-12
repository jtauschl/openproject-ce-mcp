"""Integration tests for the User Non-Working Times / User Working Hours
domains (per-user schedule overrides).

Requires OpenProject 17.3+ (feature-flag-gated `guard_feature_flag
:user_working_times` through 17.6, generally available 17.7+ -- verified
against op-sources: present in 17.3-17.6's `working_hours_by_user_api.rb`/
`non_working_times_by_user_api.rb`, absent in 17.7's; the route does not
exist at all before 17.3). Earlier versions are expected to fail with a
[server_error] on every tool in this file; no client-side version gate
exists (this MCP passes server errors through unmodified, per this
project's established pattern), so these tests are only meaningful run
against a 17.3+ instance.

user_ref="me" (self-service) is used throughout as the primary path, for two
reasons: it works regardless of whether the integration token's user has the
`manage_working_times` global permission, and it avoids needing a second real
user id in the test project's data to exercise the "manage another user"
case. That cross-user case (an admin/`manage_working_times`-holding caller
managing a DIFFERENT user's schedule) is NOT covered here -- it would need a
second real, disposable user id on the target instance, which (unlike
`second_user_client` elsewhere in this suite) still would not exercise
anything different for THIS domain: the route-level auth decision is a
single `after_validation` gate in OpenProject itself
(`@user == current_user || current_user.allowed_globally?(:manage_working_times)`),
not something this MCP's own code branches on, so a cross-user test would
only re-prove OpenProject's own authorization, not this client's behavior.
Documented explicitly here (mirroring how test_wiki_page_links.py documents
its own upstream-bug scope decisions) rather than silently omitted.

This domain has no project concept at all (see
`app/ports/user_non_working_time_api.py`'s / `user_working_hours_api.py`'s
module docstrings) -- unlike every other write-test file in this suite,
these tests do not use `test_project`/`wp_ids` and do not need
`OPENPROJECT_WRITE_PROJECTS` to include the resource being mutated; only
`OPENPROJECT_ENABLE_USER_SCHEDULE_READ`/`_WRITE` (set unconditionally by
`_integration_settings()` in conftest.py) govern access here.
"""

from __future__ import annotations

import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration

_USER_REF = "me"


# --- User Non-Working Times ---------------------------------------------


async def test_create_list_update_delete_user_non_working_time(
    client: OpenProjectClient, user_non_working_time_ids: list[tuple[str, int]]
) -> None:
    # Use a random-ish date range far in the future to avoid colliding with
    # any real non-working time an operator may have configured for this
    # account, and to keep repeated runs independent of each other.
    year_offset = (uuid.uuid4().int % 20) + 5
    start_date = f"20{50 + year_offset}-01-10"
    end_date = f"20{50 + year_offset}-01-15"

    create_result = await client.create_user_non_working_time(
        _USER_REF, start_date=start_date, end_date=end_date, confirm=True
    )
    assert create_result.ready and create_result.state == "confirmed", create_result.validation_errors
    non_working_time_id = create_result.non_working_time_id
    assert non_working_time_id is not None and non_working_time_id > 0
    user_non_working_time_ids.append((_USER_REF, non_working_time_id))

    listed = await client.list_user_non_working_times(_USER_REF, year=2050 + year_offset)
    assert any(item.id == non_working_time_id for item in listed.results)

    updated_end_date = f"20{50 + year_offset}-01-20"
    update_result = await client.update_user_non_working_time(
        _USER_REF, non_working_time_id, end_date=updated_end_date, confirm=True
    )
    assert update_result.ready and update_result.state == "confirmed", update_result.validation_errors
    assert update_result.result is not None
    assert update_result.result.end_date == updated_end_date

    await client.delete_user_non_working_time(_USER_REF, non_working_time_id, confirm=True)
    user_non_working_time_ids.remove((_USER_REF, non_working_time_id))

    listed_after_delete = await client.list_user_non_working_times(_USER_REF, year=2050 + year_offset)
    assert all(item.id != non_working_time_id for item in listed_after_delete.results)


async def test_create_user_non_working_time_preview_without_confirm_does_not_write(
    client: OpenProjectClient, user_non_working_time_ids: list[tuple[str, int]]
) -> None:
    preview_result = await client.create_user_non_working_time(
        _USER_REF, start_date="2077-02-01", end_date="2077-02-05", confirm=False
    )
    assert preview_result.state == "preview"
    assert preview_result.result is None

    listed = await client.list_user_non_working_times(_USER_REF, year=2077)
    assert all(item.start_date != "2077-02-01" for item in listed.results)


async def test_update_user_non_working_time_raises_not_found_for_unknown_id(client: OpenProjectClient) -> None:
    from openproject_ce_mcp.client import NotFoundError

    with pytest.raises(NotFoundError):
        await client.update_user_non_working_time(_USER_REF, 2**31 - 1, end_date="2077-03-01", confirm=False)


# --- User Working Hours ---------------------------------------------------


async def test_create_get_list_update_delete_user_working_hours(
    client: OpenProjectClient, user_working_hours_ids: list[tuple[str, int]]
) -> None:
    year_offset = (uuid.uuid4().int % 20) + 5
    valid_from = f"20{50 + year_offset}-02-01"

    create_result = await client.create_user_working_hours(
        _USER_REF, valid_from=valid_from, monday_hours=8.0, tuesday_hours=8.0, confirm=True
    )
    assert create_result.ready and create_result.state == "confirmed", create_result.validation_errors
    working_hours_id = create_result.working_hours_id
    assert working_hours_id is not None and working_hours_id > 0
    user_working_hours_ids.append((_USER_REF, working_hours_id))

    fetched = await client.get_user_working_hours(_USER_REF, working_hours_id)
    assert fetched.id == working_hours_id
    assert fetched.valid_from == valid_from

    listed = await client.list_user_working_hours(_USER_REF)
    assert any(item.id == working_hours_id for item in listed.results)

    update_result = await client.update_user_working_hours(_USER_REF, working_hours_id, monday_hours=6.0, confirm=True)
    assert update_result.ready and update_result.state == "confirmed", update_result.validation_errors
    assert update_result.result is not None
    assert update_result.result.monday_hours == 6.0

    await client.delete_user_working_hours(_USER_REF, working_hours_id, confirm=True)
    user_working_hours_ids.remove((_USER_REF, working_hours_id))

    from openproject_ce_mcp.client import NotFoundError, OpenProjectServerError

    with pytest.raises((NotFoundError, OpenProjectServerError)):
        await client.get_user_working_hours(_USER_REF, working_hours_id)


async def test_create_user_working_hours_preview_without_confirm_does_not_write(
    client: OpenProjectClient, user_working_hours_ids: list[tuple[str, int]]
) -> None:
    preview_result = await client.create_user_working_hours(_USER_REF, valid_from="2078-03-01", confirm=False)
    assert preview_result.state == "preview"
    assert preview_result.result is None


async def test_user_schedule_denies_read_when_scope_disabled(client: OpenProjectClient) -> None:
    import dataclasses

    from openproject_ce_mcp.client import PermissionDeniedError

    disabled_settings = dataclasses.replace(client.settings, enable_user_schedule_read=False)
    disabled_client = OpenProjectClient(disabled_settings)
    await disabled_client.initialize()

    with pytest.raises(PermissionDeniedError):
        await disabled_client.list_user_working_hours(_USER_REF)
