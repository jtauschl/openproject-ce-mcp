from __future__ import annotations

import httpx
import pytest
from _tools_test_helpers import FakeContext, make_settings

from openproject_ce_mcp.client import CLEAR, CLEAR_PARENT, CLEAR_VERSION, OpenProjectClient
from openproject_ce_mcp.tools import (
    _validate_work_package_ref,
    add_work_package_comment,
    add_work_package_watcher,
    bulk_create_work_packages,
    bulk_update_work_packages,
    create_subtask,
    create_work_package,
    delete_relation,
    delete_work_package,
    get_project_work_package_context,
    get_work_package,
    get_work_packages,
    list_work_package_reactions,
    list_work_package_watchers,
    list_work_packages,
    remove_work_package_watcher,
    search_work_packages,
    toggle_activity_emoji_reaction,
    update_relation,
    update_work_package,
)


@pytest.mark.asyncio
async def test_get_work_package_returns_compact_summary() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Investigate API wrapper",
                    "startDate": "2026-03-20",
                    "dueDate": "2026-03-25",
                    "percentageDone": 50,
                    "lockVersion": 7,
                    "description": {"raw": "Detailed description"},
                    "_links": {
                        "type": {"title": "Task"},
                        "status": {"title": "In progress"},
                        "priority": {"title": "Normal"},
                        "assignee": {"title": "OpenProject Bot"},
                        "responsible": {"title": "Maintainer"},
                        "project": {"title": "Demo"},
                        "version": {"title": "v1"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await get_work_package(FakeContext(client), 42)

    assert result.id == 42
    assert result.subject == "Investigate API wrapper"
    assert result.activities_url == "https://op.example.com/api/v3/work_packages/42/activities"
    assert result.relations_url == "https://op.example.com/api/v3/work_packages/42/relations"

    await client.aclose()


@pytest.mark.asyncio
async def test_get_work_packages_tool_rejects_unknown_select_field() -> None:
    class StubClient:
        async def get_work_packages(self, **kwargs):
            raise AssertionError("client should not be called when select validation fails")

    with pytest.raises(ValueError, match="not a valid WorkPackageDetail field"):
        await get_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            ids=["1"],
            select=["bogus"],
        )


@pytest.mark.asyncio
async def test_get_work_packages_tool_does_not_forward_select_to_client() -> None:
    class StubClient:
        async def get_work_packages(self, **kwargs):
            return kwargs

    result = await get_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        ids=["1"],
        select=["id", "subject"],
    )

    assert "select" not in result
    assert result["ids"] == ["1"]


@pytest.mark.asyncio
async def test_search_work_packages_tool_accepts_parent_display_id_select_field() -> None:
    # parent_display_id was missing from WorkPackageSummary previously, so this
    # select value used to raise "not a valid WorkPackageSummary field".
    class StubClient:
        async def search_work_packages(self, **kwargs):
            return kwargs

    result = await search_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        search="Feature",
        select=["id", "parent_id", "parent_display_id"],
    )

    assert result["search"] == "Feature"


@pytest.mark.asyncio
async def test_search_work_packages_tool_passes_status_filter() -> None:
    class StubClient:
        async def search_work_packages(self, **kwargs):
            return kwargs

    result = await search_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        search="Feature",
        project="demo",
        status="In progress",
        open_only=True,
        assignee_me=False,
        limit=10,
    )

    assert result["search"] == "Feature"
    assert result["project"] == "demo"
    assert result["status"] == "In progress"
    assert result["open_only"] is True
    assert result["limit"] == 10


@pytest.mark.asyncio
async def test_list_work_packages_returns_version_and_description_flags() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 204,
                                "subject": "Apple HealthKit Anbindung",
                                "description": {"raw": "Sync Apple Health data"},
                                "_links": {
                                    "type": {"title": "Feature"},
                                    "status": {"title": "Open"},
                                    "project": {"title": "Demo"},
                                    "version": {"title": "Q2"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await list_work_packages(FakeContext(client), project="demo")

    assert result.count == 1
    assert result.results[0].version == "Q2"
    # Description includes <user-content> tags
    assert result.results[0].description == "<user-content>Sync Apple Health data</user-content>"
    assert result.results[0].has_description is True

    await client.aclose()


@pytest.mark.asyncio
async def test_create_work_package_tool_requires_confirmation_before_write() -> None:
    class StubClient:
        async def create_work_package(self, **kwargs):
            return kwargs

    result = await create_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        project="demo",
        type="Feature",
        subject="New feature",
        project_phase="Executing",
        confirm=False,
    )

    assert result["project"] == "demo"
    assert result["project_phase"] == "Executing"
    assert result["confirm"] is False


@pytest.mark.asyncio
async def test_update_work_package_tool_requires_at_least_one_field() -> None:
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match="At least one field"):
        await update_work_package(FakeContext(StubClient()), 42)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_update_work_package_tool_passes_project_phase() -> None:
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        project_phase="Executing",
        confirm=False,
    )

    assert result["work_package_id"] == "42"
    assert result["project_phase"] == "Executing"


@pytest.mark.asyncio
async def test_update_work_package_tool_passes_parent_ref() -> None:
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        parent="PROJ-7",
        confirm=False,
    )

    assert result["parent_work_package_id"] == "PROJ-7"


@pytest.mark.asyncio
async def test_update_work_package_tool_maps_none_to_clear_parent_sentinel() -> None:
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        parent="none",
        confirm=False,
    )

    # 'none' (un-parent) must reach the client as the sentinel, not the string "none".
    assert result["parent_work_package_id"] is CLEAR_PARENT


@pytest.mark.asyncio
async def test_update_work_package_tool_parent_alone_satisfies_field_requirement() -> None:
    # Clearing the parent is a real change: it must not trip "at least one field".
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        parent="none",
        confirm=False,
    )

    assert result["parent_work_package_id"] is CLEAR_PARENT


@pytest.mark.asyncio
async def test_update_work_package_tool_maps_none_to_clear_version_sentinel() -> None:
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        version="none",
        confirm=False,
    )

    # 'none' (unassign version) must reach the client as the sentinel, not the string "none".
    assert result["version"] is CLEAR_VERSION


@pytest.mark.asyncio
async def test_update_work_package_tool_version_alone_satisfies_field_requirement() -> None:
    # Clearing the version is a real change: it must not trip "at least one field".
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        version="none",
        confirm=False,
    )

    assert result["version"] is CLEAR_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    ["assignee", "responsible", "category", "project_phase", "sprint", "estimated_time", "remaining_time", "duration"],
)
async def test_update_work_package_tool_maps_none_to_clear_sentinel(field) -> None:
    # 'none' on a nullable association field must reach the client as the CLEAR
    # sentinel (unassign), not the literal string "none".
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        **{field: "none"},
        confirm=False,
    )

    assert result[field] is CLEAR


@pytest.mark.asyncio
async def test_update_work_package_tool_clear_field_satisfies_field_requirement() -> None:
    # Clearing assignee alone is a real change: it must not trip "at least one field".
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        assignee="none",
        confirm=False,
    )

    assert result["assignee"] is CLEAR


@pytest.mark.asyncio
async def test_update_work_package_tool_clears_description() -> None:
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        description="",
        confirm=True,
    )

    assert result["description"] == ""


@pytest.mark.asyncio
async def test_update_work_package_tool_passes_real_version_name() -> None:
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        version="0.3.0",
        confirm=False,
    )

    # A real version name passes through unchanged (not the sentinel).
    assert result["version"] == "0.3.0"


@pytest.mark.asyncio
async def test_update_work_package_tool_passes_real_sprint_name() -> None:
    class StubClient:
        async def update_work_package(self, **kwargs):
            return kwargs

    result = await update_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        sprint="Cleanup",
        confirm=False,
    )

    # A real sprint name passes through unchanged (not the sentinel).
    assert result["sprint"] == "Cleanup"


@pytest.mark.asyncio
async def test_create_work_package_tool_passes_parent_ref() -> None:
    class StubClient:
        async def create_work_package(self, **kwargs):
            return kwargs

    result = await create_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        project="PROJ",
        type="Task",
        subject="child",
        parent="PROJ-7",
        confirm=False,
    )

    assert result["parent_work_package_id"] == "PROJ-7"


@pytest.mark.asyncio
async def test_delete_work_package_tool_passes_confirmation_flag() -> None:
    class StubClient:
        async def delete_work_package(self, **kwargs):
            return kwargs

    result = await delete_work_package(FakeContext(StubClient()), "42", confirm=True)  # type: ignore[arg-type]

    assert result["work_package_id"] == "42"
    assert result["confirm"] is True


@pytest.mark.asyncio
async def test_add_work_package_comment_tool_passes_notify_flag() -> None:
    class StubClient:
        async def add_work_package_comment(self, **kwargs):
            return kwargs

    result = await add_work_package_comment(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        "Looks good",
        notify=False,
        confirm=True,
    )

    assert result["work_package_id"] == "42"
    assert result["notify"] is False
    assert result["confirm"] is True


@pytest.mark.asyncio
async def test_delete_relation_tool_passes_confirmation_flag() -> None:
    class StubClient:
        async def delete_relation(self, **kwargs):
            return kwargs

    result = await delete_relation(FakeContext(StubClient()), 99, confirm=True)  # type: ignore[arg-type]

    assert result["relation_id"] == 99
    assert result["confirm"] is True


@pytest.mark.asyncio
async def test_update_relation_tool_clears_description() -> None:
    # The old falsy short-circuit (`if description else None`) meant an
    # explicit "" never even reached validation; this must now clear.
    class StubClient:
        async def update_relation(self, **kwargs):
            return kwargs

    result = await update_relation(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        99,
        description="",
        confirm=True,
    )

    assert result["description"] == ""


@pytest.mark.asyncio
async def test_create_subtask_tool_passes_parent_id() -> None:
    class StubClient:
        async def create_subtask(self, **kwargs):
            return kwargs

    result = await create_subtask(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        "42",
        "Task",
        "Child ticket",
        project_phase="Executing",
        confirm=False,
    )

    assert result["parent_work_package_id"] == "42"
    assert result["project_phase"] == "Executing"
    assert result["subject"] == "Child ticket"


@pytest.mark.asyncio
async def test_get_project_work_package_context_tool_passes_type() -> None:
    class StubClient:
        async def get_project_work_package_context(self, **kwargs):
            return kwargs

    result = await get_project_work_package_context(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        project="demo",
        type="Feature",
    )

    assert result["project"] == "demo"
    assert result["type"] == "Feature"


@pytest.mark.asyncio
async def test_create_work_package_tool_passes_custom_fields() -> None:
    class StubClient:
        async def create_work_package(self, **kwargs):
            return kwargs

    result = await create_work_package(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        project="demo",
        type="Feature",
        subject="New feature",
        custom_fields={"Story points": 5},
        confirm=False,
    )

    assert result["custom_fields"] == {"Story points": 5}


@pytest.mark.asyncio
async def test_watcher_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_work_package_watchers(self, work_package_id):
            return {"work_package_id": work_package_id}

        async def add_work_package_watcher(self, work_package_id, user_id, **kwargs):
            return {"work_package_id": work_package_id, "user_id": user_id, **kwargs}

        async def remove_work_package_watcher(self, work_package_id, user_id, **kwargs):
            return {"work_package_id": work_package_id, "user_id": user_id, **kwargs}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_work_package_watchers(ctx, "42")
    added = await add_work_package_watcher(ctx, "42", 7, confirm=False)
    removed = await remove_work_package_watcher(ctx, "42", 7, confirm=True)

    assert listed["work_package_id"] == "42"
    assert added["user_id"] == 7
    assert removed["confirm"] is True


@pytest.mark.asyncio
async def test_emoji_reaction_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_work_package_reactions(self, work_package_id):
            return {"work_package_id": work_package_id}

        async def toggle_activity_emoji_reaction(self, activity_id, reaction, confirm=False):
            return {"activity_id": activity_id, "reaction": reaction, "confirm": confirm}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_work_package_reactions(ctx, "PROJ-1")
    toggled = await toggle_activity_emoji_reaction(ctx, 1988, "thumbs_up", confirm=True)

    assert listed["work_package_id"] == "PROJ-1"
    assert toggled["activity_id"] == 1988
    assert toggled["reaction"] == "thumbs_up"
    assert toggled["confirm"] is True


@pytest.mark.asyncio
async def test_list_work_packages_version_status_validation() -> None:
    class StubClient:
        async def list_work_packages(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    ok = await list_work_packages(ctx, version_status="open")
    assert ok["version_status"] == "open"

    with pytest.raises(ValueError, match="version_status must be one of"):
        await list_work_packages(ctx, version_status="archived")


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_clears_item_description() -> None:
    # Per-item description has its own normalization pass distinct from
    # update_work_package's — worth its own test rather than assuming it
    # shares behavior just because it calls the same validator.
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return kwargs

    result = await bulk_update_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        items=[{"work_package_id": 1, "description": ""}],
        confirm=True,
    )

    assert result["items"][0]["description"] == ""


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_accepts_each_duration_field_alone() -> None:
    # Regression guard: each of estimated_time/remaining_time/duration
    # must independently satisfy the "at least one field" check, not just when
    # combined with an already-supported field like subject/status.
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
            {"work_package_id": 10, "estimated_time": "PT8H"},
            {"work_package_id": 20, "remaining_time": "PT3H"},
            {"work_package_id": 30, "duration": "PT10H"},
            {"work_package_id": 40, "percentage_done": 0},
        ],
        confirm=True,
    )

    assert len(received) == 4
    assert received[0]["estimated_time"] == "PT8H"
    assert received[1]["remaining_time"] == "PT3H"
    assert received[2]["duration"] == "PT10H"
    assert received[3]["percentage_done"] == 0


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_maps_none_duration_to_clear_sentinel() -> None:
    # 'none' on estimated_time/remaining_time/duration must reach the client as
    # the CLEAR sentinel, not the literal string "none" (which would fail the
    # ISO 8601 duration regex).
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
            {"work_package_id": 10, "estimated_time": "none"},
            {"work_package_id": 20, "remaining_time": "None"},
            {"work_package_id": 30, "duration": "NONE"},
        ],
        confirm=True,
    )

    assert received[0]["estimated_time"] is CLEAR
    assert received[1]["remaining_time"] is CLEAR
    assert received[2]["duration"] is CLEAR


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_maps_none_to_clear_sentinel() -> None:
    # 'none' on version/project_phase/assignee/responsible/category/
    # parent_work_package_id must reach the client as the matching clear
    # sentinel in bulk mode too, same as update_work_package already does.
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
            {"work_package_id": 10, "version": "none"},
            {"work_package_id": 20, "project_phase": "None"},
            {"work_package_id": 30, "assignee": "NONE"},
            {"work_package_id": 40, "responsible": "none"},
            {"work_package_id": 50, "category": "none"},
            {"work_package_id": 60, "parent_work_package_id": "none"},
        ],
        confirm=True,
    )

    assert received[0]["version"] is CLEAR_VERSION
    assert received[1]["project_phase"] is CLEAR
    assert received[2]["assignee"] is CLEAR
    assert received[3]["responsible"] is CLEAR
    assert received[4]["category"] is CLEAR
    assert received[5]["parent_work_package_id"] is CLEAR_PARENT


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_accepts_numeric_parent_work_package_id() -> None:
    # Regression guard: parent_work_package_id can legitimately be a JSON number
    # (not a "none"-string), and _clearable must not choke trying to .strip() it.
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
        items=[{"work_package_id": 10, "parent_work_package_id": 952}],
        confirm=True,
    )

    assert received[0]["parent_work_package_id"] == "952"


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_accepts_parent_alias() -> None:
    # `parent` is accepted as an alias for `parent_work_package_id`, matching
    # update_work_package's own parameter name — must reach the client under
    # the same parent_work_package_id key either way.
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
        items=[{"work_package_id": 10, "parent": "952"}],
        confirm=True,
    )

    assert received[0]["parent_work_package_id"] == "952"


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_parent_alias_maps_none_to_clear_sentinel() -> None:
    # The parent alias must support the documented clear semantics too, not
    # just setting a normal reference.
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
        items=[{"work_package_id": 60, "parent": "none"}],
        confirm=True,
    )

    assert received[0]["parent_work_package_id"] is CLEAR_PARENT


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_rejects_both_parent_aliases() -> None:
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match=r"items\[0\] must not specify both parent and parent_work_package_id"):
        await bulk_update_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"work_package_id": 10, "parent": "952", "parent_work_package_id": "952"}],
            confirm=True,
        )


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_invalid_parent_alias_reports_own_field_name() -> None:
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match=r"items\[0\]\.parent"):
        await bulk_update_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"work_package_id": 10, "parent": 0}],
            confirm=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["assignee", "responsible", "category", "project_phase", "version"])
async def test_bulk_update_work_packages_tool_rejects_non_string_scalar_cleanly(field) -> None:
    # Regression guard: a bare JSON number/bool for a field that expects a string
    # (e.g. an LLM caller sending assignee=42 instead of assignee="42") must raise
    # a clean [validation_error] ValueError, not an unhandled AttributeError from
    # .split()/.strip() deep inside a validator.
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match="must be a string"):
        await bulk_update_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"work_package_id": 10, field: 42}],
            confirm=True,
        )


@pytest.mark.asyncio
async def test_bulk_update_work_packages_tool_version_error_has_item_index() -> None:
    # Regression guard: version's error message must be indexed like every
    # sibling field in the same loop (items[1].version, not just "version"),
    # so a caller can tell which item in the batch failed.
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match=r"items\[1\]\.version must be at most 100 characters"):
        await bulk_update_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[
                {"work_package_id": 10, "subject": "ok"},
                {"work_package_id": 20, "version": "x" * 101},
            ],
            confirm=True,
        )


@pytest.mark.asyncio
async def test_bulk_create_work_packages_assignee_error_is_indexed_by_item() -> None:
    # OPM-218 fix: assignee's error is now indexed with "items[{i}]." like every
    # sibling field in this loop, so a multi-item bulk call can tell which item
    # failed.
    class StubClient:
        async def bulk_create_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match=r"^items\[0\]\.assignee: 'me' or numeric user id"):
        await bulk_create_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"project": "demo", "type": "Task", "subject": "ok", "assignee": "not-a-user"}],
            confirm=True,
        )


@pytest.mark.asyncio
async def test_bulk_create_work_packages_responsible_error_is_indexed_by_item() -> None:
    # OPM-218 fix, for responsible.
    class StubClient:
        async def bulk_create_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match=r"^items\[0\]\.responsible: 'me' or numeric user id"):
        await bulk_create_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"project": "demo", "type": "Task", "subject": "ok", "responsible": "not-a-user"}],
            confirm=True,
        )


@pytest.mark.asyncio
async def test_bulk_update_work_packages_assignee_error_is_indexed_by_item() -> None:
    # OPM-218 fix, same as the two bulk_create tests above.
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match=r"^items\[0\]\.assignee: 'me' or numeric user id"):
        await bulk_update_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"work_package_id": 10, "assignee": "not-a-user"}],
            confirm=True,
        )


@pytest.mark.asyncio
async def test_bulk_update_work_packages_responsible_error_is_indexed_by_item() -> None:
    # OPM-218 fix, for responsible.
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match=r"^items\[0\]\.responsible: 'me' or numeric user id"):
        await bulk_update_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"work_package_id": 10, "responsible": "not-a-user"}],
            confirm=True,
        )


@pytest.mark.asyncio
async def test_bulk_create_work_packages_accepts_select() -> None:
    # OPM-155: select is validated by the tool function but not forwarded to the
    # client -- the actual field-dropping happens one layer up, in the FastMCP
    # registration wrapper's _to_payload call (see tests/test_trimming.py's
    # wrapper-integration test for that). This test only proves the tool
    # function accepts and validates select without erroring.
    class StubClient:
        async def bulk_create_work_packages(self, **kwargs):
            return {"action": "bulk_create", "items": []}

    result = await bulk_create_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        items=[{"project": "demo", "type": "Task", "subject": "ok"}],
        select=["ready", "work_package_id"],
        confirm=False,
    )
    assert result["action"] == "bulk_create"


@pytest.mark.asyncio
async def test_bulk_create_work_packages_rejects_invalid_select_field() -> None:
    class StubClient:
        async def bulk_create_work_packages(self, **kwargs):
            return {"action": "bulk_create", "items": []}

    with pytest.raises(ValueError, match="not a valid WorkPackageWriteResult field"):
        await bulk_create_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"project": "demo", "type": "Task", "subject": "ok"}],
            select=["bogus"],
            confirm=False,
        )


@pytest.mark.asyncio
async def test_bulk_update_work_packages_accepts_select() -> None:
    # Same split as the bulk_create test above: validation only, not threading.
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return {"action": "bulk_update", "items": []}

    result = await bulk_update_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        items=[{"work_package_id": 10, "subject": "New"}],
        select=["ready", "work_package_id"],
        confirm=False,
    )
    assert result["action"] == "bulk_update"


@pytest.mark.asyncio
async def test_bulk_update_work_packages_rejects_invalid_select_field() -> None:
    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            return {"action": "bulk_update", "items": []}

    with pytest.raises(ValueError, match="not a valid WorkPackageWriteResult field"):
        await bulk_update_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"work_package_id": 10, "subject": "New"}],
            select=["bogus"],
            confirm=False,
        )


@pytest.mark.asyncio
async def test_bulk_work_packages_accept_semantic_refs() -> None:
    received: dict = {}

    class StubClient:
        async def bulk_update_work_packages(self, **kwargs):
            received["update"] = kwargs["items"]
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

        async def bulk_create_work_packages(self, **kwargs):
            received["create"] = kwargs["items"]
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

    # A project-prefixed ref must be accepted by the bulk tools, not only the
    # single-item tools: previously it failed the whole batch with a raw
    # TypeError from the int validator.
    await bulk_update_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        items=[{"work_package_id": "OPM-61", "subject": "X", "parent_work_package_id": "OPM-7"}],
        confirm=True,
    )
    assert received["update"][0]["work_package_id"] == "OPM-61"
    assert received["update"][0]["parent_work_package_id"] == "OPM-7"

    await bulk_create_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        items=[{"project": "demo", "type": "Task", "subject": "X", "parent_work_package_id": "OPM-7"}],
        confirm=True,
    )
    assert received["create"][0]["parent_work_package_id"] == "OPM-7"
    with pytest.raises(ValueError, match="must be at least 1"):
        _validate_work_package_ref("0")


@pytest.mark.asyncio
async def test_bulk_create_work_packages_tool_accepts_parent_alias() -> None:
    # `parent` is accepted as an alias for `parent_work_package_id`, matching
    # create_work_package's own parameter name — must reach the client under
    # the same parent_work_package_id key either way.
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
        items=[{"project": "demo", "type": "Task", "subject": "X", "parent": "OPM-7"}],
        confirm=True,
    )

    assert received[0]["parent_work_package_id"] == "OPM-7"


@pytest.mark.asyncio
async def test_bulk_create_work_packages_tool_rejects_both_parent_aliases() -> None:
    class StubClient:
        async def bulk_create_work_packages(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match=r"items\[0\] must not specify both parent and parent_work_package_id"):
        await bulk_create_work_packages(
            FakeContext(StubClient()),  # type: ignore[arg-type]
            items=[{"project": "demo", "type": "Task", "subject": "X", "parent": "7", "parent_work_package_id": "7"}],
            confirm=True,
        )
