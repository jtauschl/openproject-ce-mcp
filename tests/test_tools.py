from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import httpx
import pytest

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.tools import (
    _validate_optional_work_package_ref,
    _validate_work_package_ref,
    add_project_favorite,
    add_work_package_comment,
    add_work_package_watcher,
    bulk_create_work_packages,
    bulk_update_work_packages,
    copy_project,
    create_board,
    create_grid,
    create_group,
    create_news,
    create_subtask,
    create_time_entry,
    create_user,
    create_version,
    create_work_package,
    create_work_package_attachment,
    create_work_package_relation,
    create_work_package_reminder,
    delete_attachment,
    delete_board,
    delete_file_link,
    delete_grid,
    delete_group,
    delete_news,
    delete_relation,
    delete_reminder,
    delete_time_entry,
    delete_user,
    delete_version,
    delete_work_package,
    get_attachment,
    get_board,
    get_category,
    get_document,
    get_grid,
    get_instance_configuration,
    get_job_status,
    get_my_project_access,
    get_news,
    get_priority,
    get_project_configuration,
    get_project_phase,
    get_project_phase_definition,
    get_project_work_package_context,
    get_status,
    get_time_entry,
    get_type,
    get_version,
    get_view,
    get_wiki_page,
    get_work_package,
    list_boards,
    list_categories,
    list_documents,
    list_grids,
    list_news,
    list_notifications,
    list_priorities,
    list_project_memberships,
    list_project_phase_definitions,
    list_projects,
    list_reminders,
    list_roles,
    list_statuses,
    list_time_entries,
    list_time_entry_activities,
    list_types,
    list_versions,
    list_views,
    list_work_package_attachments,
    list_work_package_file_links,
    list_work_package_reactions,
    list_work_package_watchers,
    list_work_packages,
    lock_user,
    mark_all_notifications_read,
    mark_notification_read,
    remove_project_favorite,
    remove_work_package_watcher,
    search_work_packages,
    toggle_activity_emoji_reaction,
    unlock_user,
    update_board,
    update_document,
    update_grid,
    update_group,
    update_news,
    update_reminder,
    update_time_entry,
    update_user,
    update_version,
    update_work_package,
)


def make_settings() -> Settings:
    return Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )


@dataclass
class FakeAppContext:
    client: OpenProjectClient


class FakeContext:
    def __init__(self, client: OpenProjectClient) -> None:
        self.request_context = SimpleNamespace(lifespan_context=FakeAppContext(client=client))


@pytest.mark.asyncio
async def test_list_projects_filters_out_non_project_workspaces() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects":
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "Project",
                                "id": 1,
                                "name": "Demo",
                                "identifier": "demo",
                                "active": True,
                                "description": {"raw": "Project description"},
                            },
                            {
                                "_type": "Program",
                                "id": 2,
                                "name": "Ignore me",
                            },
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await list_projects(FakeContext(client))

    assert result.count == 1
    assert result.results[0].identifier == "demo"

    await client.aclose()


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
async def test_search_work_packages_tool_passes_status_filter() -> None:
    class StubClient:
        async def search_work_packages(self, **kwargs):
            return kwargs

    result = await search_work_packages(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        query="Feature",
        project="demo",
        status="In progress",
        open_only=True,
        assignee_me=False,
        limit=10,
    )

    assert result["query"] == "Feature"
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
    assert result.results[0].description == "Sync Apple Health data"
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
async def test_delete_relation_tool_passes_confirmation_flag() -> None:
    class StubClient:
        async def delete_relation(self, **kwargs):
            return kwargs

    result = await delete_relation(FakeContext(StubClient()), 99, confirm=True)  # type: ignore[arg-type]

    assert result["relation_id"] == 99
    assert result["confirm"] is True


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
async def test_list_roles_tool_calls_client() -> None:
    class StubClient:
        async def list_roles(self, **kwargs):
            return {"ok": True}

    result = await list_roles(FakeContext(StubClient()))  # type: ignore[arg-type]
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_project_access_tools_pass_project_ref() -> None:
    class StubClient:
        async def list_project_memberships(self, project):
            return {"project": project}

        async def get_my_project_access(self, project):
            return {"project": project}

    memberships = await list_project_memberships(FakeContext(StubClient()), "demo")  # type: ignore[arg-type]
    access = await get_my_project_access(FakeContext(StubClient()), "demo")  # type: ignore[arg-type]

    assert memberships["project"] == "demo"
    assert access["project"] == "demo"


@pytest.mark.asyncio
async def test_instance_configuration_and_phase_tools_call_client() -> None:
    class StubClient:
        async def get_instance_configuration(self):
            return {"configuration": True}

        async def get_project_configuration(self, project):
            return {"project": project, "project_configuration": True}

        async def list_project_phase_definitions(self):
            return {"phases": True}

        async def get_project_phase_definition(self, phase_definition_id):
            return {"phase_definition_id": phase_definition_id}

        async def get_project_phase(self, phase_id):
            return {"phase_id": phase_id}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    configuration = await get_instance_configuration(ctx)
    project_configuration = await get_project_configuration(ctx, "demo")
    phases = await list_project_phase_definitions(ctx)
    phase = await get_project_phase_definition(ctx, 3)
    project_phase = await get_project_phase(ctx, 5)

    assert configuration["configuration"] is True
    assert project_configuration["project"] == "demo"
    assert project_configuration["project_configuration"] is True
    assert phases["phases"] is True
    assert phase["phase_definition_id"] == 3
    assert project_phase["phase_id"] == 5


@pytest.mark.asyncio
async def test_copy_project_tool_passes_expected_arguments() -> None:
    class StubClient:
        async def copy_project(self, **kwargs):
            return kwargs

    result = await copy_project(
        FakeContext(StubClient()),  # type: ignore[arg-type]
        source_project="demo",
        name="Demo Copy",
        identifier="demo-copy",
        confirm=False,
    )

    assert result["source_project"] == "demo"
    assert result["name"] == "Demo Copy"
    assert result["identifier"] == "demo-copy"
    assert result["confirm"] is False


@pytest.mark.asyncio
async def test_job_document_news_and_wiki_tools_pass_arguments() -> None:
    class StubClient:
        async def get_job_status(self, job_status_id):
            return {"job_status_id": job_status_id}

        async def list_documents(self, **kwargs):
            return kwargs

        async def get_document(self, document_id):
            return {"document_id": document_id}

        async def update_document(self, **kwargs):
            return kwargs

        async def list_news(self, **kwargs):
            return kwargs

        async def get_news(self, news_id):
            return {"news_id": news_id}

        async def create_news(self, **kwargs):
            return kwargs

        async def update_news(self, **kwargs):
            return kwargs

        async def delete_news(self, **kwargs):
            return kwargs

        async def get_wiki_page(self, wiki_page_id):
            return {"wiki_page_id": wiki_page_id}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    job = await get_job_status(ctx, 77)
    documents = await list_documents(ctx, project="demo")
    document = await get_document(ctx, 5)
    document_update = await update_document(ctx, 5, title="Architecture", confirm=True)
    news_list = await list_news(ctx, project="demo", search="release")
    news = await get_news(ctx, 7)
    news_create = await create_news(ctx, project="demo", title="Fresh Update", summary="Ready", confirm=False)
    news_update = await update_news(ctx, 7, summary="Stable", confirm=True)
    news_delete = await delete_news(ctx, 7, confirm=True)
    wiki_page = await get_wiki_page(ctx, 9)

    assert job["job_status_id"] == 77
    assert documents["project"] == "demo"
    assert document["document_id"] == 5
    assert document_update["document_id"] == 5
    assert document_update["confirm"] is True
    assert news_list["search"] == "release"
    assert news["news_id"] == 7
    assert news_create["project"] == "demo"
    assert news_update["news_id"] == 7
    assert news_delete["news_id"] == 7
    assert wiki_page["wiki_page_id"] == 9


@pytest.mark.asyncio
async def test_version_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_versions(self, **kwargs):
            return kwargs

        async def get_version(self, version_id):
            return {"version_id": version_id}

        async def create_version(self, **kwargs):
            return kwargs

        async def update_version(self, **kwargs):
            return kwargs

        async def delete_version(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_versions(ctx, project="demo")
    detail = await get_version(ctx, 7)
    created = await create_version(
        ctx,
        project="demo",
        name="Release 1",
        status="open",
        sharing="none",
        confirm=False,
    )
    updated = await update_version(ctx, 7, name="Release 1.1", confirm=True)
    deleted = await delete_version(ctx, 7, confirm=True)

    assert listed["project"] == "demo"
    assert detail["version_id"] == 7
    assert created["project"] == "demo"
    assert created["name"] == "Release 1"
    assert updated["version_id"] == 7
    assert updated["confirm"] is True
    assert deleted["version_id"] == 7
    assert deleted["confirm"] is True


@pytest.mark.asyncio
async def test_update_version_tool_requires_at_least_one_field() -> None:
    class StubClient:
        async def update_version(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match="At least one field"):
        await update_version(FakeContext(StubClient()), 7)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_board_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_boards(self, **kwargs):
            return kwargs

        async def get_board(self, board_id):
            return {"board_id": board_id}

        async def create_board(self, **kwargs):
            return kwargs

        async def update_board(self, **kwargs):
            return kwargs

        async def delete_board(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_boards(ctx, project="demo", search="Sprint")
    detail = await get_board(ctx, 11)
    created = await create_board(
        ctx,
        name="Sprint Board",
        project="demo",
        columns=["id", "subject"],
        sort_by=["id-asc"],
        confirm=False,
    )
    updated = await update_board(ctx, 11, name="Sprint Board Updated", public=True, confirm=True)
    deleted = await delete_board(ctx, 11, confirm=True)

    assert listed["project"] == "demo"
    assert listed["search"] == "Sprint"
    assert detail["board_id"] == 11
    assert created["project"] == "demo"
    assert created["columns"] == ["id", "subject"]
    assert created["sort_by"] == ["id-asc"]
    assert updated["board_id"] == 11
    assert updated["confirm"] is True
    assert deleted["board_id"] == 11
    assert deleted["confirm"] is True


@pytest.mark.asyncio
async def test_update_board_tool_requires_at_least_one_field() -> None:
    class StubClient:
        async def update_board(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match="At least one field"):
        await update_board(FakeContext(StubClient()), 11)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_view_category_and_attachment_tools_pass_expected_arguments(tmp_path) -> None:
    sample_file = tmp_path / "notes.txt"
    sample_file.write_text("hello", encoding="utf-8")

    class StubClient:
        async def list_views(self, **kwargs):
            return kwargs

        async def get_view(self, view_id):
            return {"view_id": view_id}

        async def list_categories(self, project):
            return {"project": project}

        async def get_category(self, **kwargs):
            return kwargs

        async def list_work_package_attachments(self, work_package_id):
            return {"work_package_id": work_package_id}

        async def get_attachment(self, attachment_id):
            return {"attachment_id": attachment_id}

        async def create_work_package_attachment(self, **kwargs):
            return kwargs

        async def delete_attachment(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    views = await list_views(ctx, project="demo", type="Views::TeamPlanner")
    view = await get_view(ctx, 12)
    categories = await list_categories(ctx, "demo")
    category = await get_category(ctx, "demo", 3)
    attachments = await list_work_package_attachments(ctx, "7")
    attachment = await get_attachment(ctx, 5)
    created = await create_work_package_attachment(ctx, "7", str(sample_file), description="Spec", confirm=False)
    deleted = await delete_attachment(ctx, 5, confirm=True)

    assert views["project"] == "demo"
    assert views["view_type"] == "Views::TeamPlanner"
    assert view["view_id"] == 12
    assert categories["project"] == "demo"
    assert category["project_ref"] == "demo"
    assert category["category_id"] == 3
    assert attachments["work_package_id"] == "7"
    assert attachment["attachment_id"] == 5
    assert created["work_package_id"] == "7"
    assert created["file_path"] == str(sample_file)
    assert deleted["attachment_id"] == 5
    assert deleted["confirm"] is True


@pytest.mark.asyncio
async def test_time_entry_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_time_entry_activities(self):
            return {"activities": True}

        async def list_time_entries(self, **kwargs):
            return kwargs

        async def get_time_entry(self, time_entry_id):
            return {"time_entry_id": time_entry_id}

        async def create_time_entry(self, **kwargs):
            return kwargs

        async def update_time_entry(self, **kwargs):
            return kwargs

        async def delete_time_entry(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    activities = await list_time_entry_activities(ctx)
    listed = await list_time_entries(ctx, project="demo", work_package_id="7", user="me")
    detail = await get_time_entry(ctx, 5)
    created = await create_time_entry(
        ctx,
        project="demo",
        activity="Development",
        hours="PT1H30M",
        spent_on="2026-03-20",
        start_time="2026-03-20T09:00:00Z",
        end_time="2026-03-20T10:30:00Z",
        confirm=False,
    )
    updated = await update_time_entry(ctx, 5, hours="PT2H", confirm=True)
    deleted = await delete_time_entry(ctx, 5, confirm=True)

    assert activities["activities"] is True
    assert listed["project"] == "demo"
    assert listed["work_package_id"] == "7"
    assert listed["user"] == "me"
    assert detail["time_entry_id"] == 5
    assert created["hours"] == "PT1H30M"
    assert created["start_time"] == "2026-03-20T09:00:00Z"
    assert created["end_time"] == "2026-03-20T10:30:00Z"
    assert updated["confirm"] is True
    assert deleted["confirm"] is True

    with pytest.raises(ValueError, match="start_time must be an ISO 8601 date-time"):
        await create_time_entry(
            ctx,
            project="demo",
            activity="Development",
            hours="PT1H",
            spent_on="2026-03-20",
            start_time="09:00",
            confirm=False,
        )


@pytest.mark.asyncio
async def test_create_time_entry_requires_scope_and_update_requires_change() -> None:
    class StubClient:
        async def create_time_entry(self, **kwargs):
            return kwargs

        async def update_time_entry(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Either project or work_package_id"):
        await create_time_entry(ctx, activity="Development", hours="PT1H", spent_on="2026-03-20")

    with pytest.raises(ValueError, match="At least one field"):
        await update_time_entry(ctx, 5)


@pytest.mark.asyncio
async def test_status_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_statuses(self):
            return {"statuses": True}

        async def get_status(self, status_id):
            return {"status_id": status_id}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_statuses(ctx)
    detail = await get_status(ctx, 3)

    assert listed["statuses"] is True
    assert detail["status_id"] == 3


@pytest.mark.asyncio
async def test_priority_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_priorities(self):
            return {"priorities": True}

        async def get_priority(self, priority_id):
            return {"priority_id": priority_id}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_priorities(ctx)
    detail = await get_priority(ctx, 2)

    assert listed["priorities"] is True
    assert detail["priority_id"] == 2


@pytest.mark.asyncio
async def test_type_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_types(self, **kwargs):
            return kwargs

        async def get_type(self, type_id):
            return {"type_id": type_id}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_types(ctx, project="demo")
    detail = await get_type(ctx, 4)

    assert listed["project"] == "demo"
    assert detail["type_id"] == 4


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

        async def toggle_activity_emoji_reaction(self, activity_id, reaction):
            return {"activity_id": activity_id, "reaction": reaction}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_work_package_reactions(ctx, "PROJ-1")
    toggled = await toggle_activity_emoji_reaction(ctx, 1988, "thumbs_up")

    assert listed["work_package_id"] == "PROJ-1"
    assert toggled["activity_id"] == 1988
    assert toggled["reaction"] == "thumbs_up"


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
async def test_reminder_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_reminders(self):
            return {"listed": True}

        async def create_work_package_reminder(self, **kwargs):
            return kwargs

        async def update_reminder(self, **kwargs):
            return kwargs

        async def delete_reminder(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_reminders(ctx)
    created = await create_work_package_reminder(ctx, "PROJ-1", "2026-12-01T09:00:00Z", note="hi", confirm=True)
    updated = await update_reminder(ctx, 5, note="changed", confirm=True)
    deleted = await delete_reminder(ctx, 5, confirm=True)

    assert listed["listed"] is True
    assert created["work_package_id"] == "PROJ-1"
    assert created["remind_at"] == "2026-12-01T09:00:00Z"
    assert updated["reminder_id"] == 5
    assert deleted["confirm"] is True


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
async def test_project_favorite_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def add_project_favorite(self, **kwargs):
            return {"action": "favorite", **kwargs}

        async def remove_project_favorite(self, **kwargs):
            return {"action": "unfavorite", **kwargs}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    added = await add_project_favorite(ctx, "demo", confirm=True)
    removed = await remove_project_favorite(ctx, "demo", confirm=False)

    assert added["project"] == "demo"
    assert added["confirm"] is True
    assert removed["action"] == "unfavorite"
    assert removed["confirm"] is False


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
async def test_notification_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_notifications(self, **kwargs):
            return kwargs

        async def mark_notification_read(self, notification_id):
            return {"notification_id": notification_id}

        async def mark_all_notifications_read(self):
            return {"all": True}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_notifications(ctx, unread_only=True)
    marked = await mark_notification_read(ctx, 10)
    marked_all = await mark_all_notifications_read(ctx)

    assert listed["unread_only"] is True
    assert marked["notification_id"] == 10
    assert marked_all["all"] is True


@pytest.mark.asyncio
async def test_user_crud_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def create_user(self, **kwargs):
            return kwargs

        async def update_user(self, user_id, **kwargs):
            return {"user_id": user_id, **kwargs}

        async def delete_user(self, user_id, **kwargs):
            return {"user_id": user_id, **kwargs}

        async def lock_user(self, user_id, **kwargs):
            return {"user_id": user_id, **kwargs}

        async def unlock_user(self, user_id, **kwargs):
            return {"user_id": user_id, **kwargs}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    created = await create_user(
        ctx, login="jdoe", email="jdoe@example.com", firstname="John", lastname="Doe", confirm=False
    )
    updated = await update_user(ctx, 5, email="new@example.com", confirm=True)
    deleted = await delete_user(ctx, 5, confirm=True)
    locked = await lock_user(ctx, 5, confirm=True)
    unlocked = await unlock_user(ctx, 5, confirm=True)

    assert created["login"] == "jdoe"
    assert updated["user_id"] == 5
    assert updated["confirm"] is True
    assert deleted["confirm"] is True
    assert locked["confirm"] is True
    assert unlocked["confirm"] is True


@pytest.mark.asyncio
async def test_update_user_requires_at_least_one_field() -> None:
    class StubClient:
        async def update_user(self, user_id, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="At least one field"):
        await update_user(ctx, 5)


@pytest.mark.asyncio
async def test_group_crud_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def create_group(self, **kwargs):
            return kwargs

        async def update_group(self, group_id, **kwargs):
            return {"group_id": group_id, **kwargs}

        async def delete_group(self, group_id, **kwargs):
            return {"group_id": group_id, **kwargs}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    created = await create_group(ctx, name="Developers", user_ids=[1, 2], confirm=False)
    updated = await update_group(ctx, 3, name="Backend", confirm=True)
    deleted = await delete_group(ctx, 3, confirm=True)

    assert created["name"] == "Developers"
    assert updated["group_id"] == 3
    assert deleted["confirm"] is True


@pytest.mark.asyncio
async def test_update_group_requires_at_least_one_field() -> None:
    class StubClient:
        async def update_group(self, group_id, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="At least one field"):
        await update_group(ctx, 3)


@pytest.mark.asyncio
async def test_file_link_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_work_package_file_links(self, work_package_id):
            return {"work_package_id": work_package_id}

        async def delete_file_link(self, file_link_id, **kwargs):
            return {"file_link_id": file_link_id, **kwargs}

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_work_package_file_links(ctx, "42")
    deleted = await delete_file_link(ctx, 5, confirm=True)

    assert listed["work_package_id"] == "42"
    assert deleted["confirm"] is True


@pytest.mark.asyncio
async def test_grid_tools_pass_expected_arguments() -> None:
    class StubClient:
        async def list_grids(self, **kwargs):
            return kwargs

        async def get_grid(self, grid_id):
            return {"grid_id": grid_id}

        async def create_grid(self, **kwargs):
            return kwargs

        async def update_grid(self, **kwargs):
            return kwargs

        async def delete_grid(self, **kwargs):
            return kwargs

    ctx = FakeContext(StubClient())  # type: ignore[arg-type]

    listed = await list_grids(ctx, scope="/my/page")
    detail = await get_grid(ctx, 2)
    created = await create_grid(ctx, name="My Grid", scope="/projects/demo", row_count=2, column_count=3, confirm=False)
    updated = await update_grid(ctx, grid_id=55, name="Renamed", row_count=4, confirm=False)
    deleted = await delete_grid(ctx, grid_id=55, confirm=True)

    assert listed["scope"] == "/my/page"
    assert detail["grid_id"] == 2
    assert created["name"] == "My Grid"
    assert created["scope"] == "/projects/demo"
    assert created["row_count"] == 2
    assert created["column_count"] == 3
    assert updated["grid_id"] == 55
    assert updated["name"] == "Renamed"
    assert updated["row_count"] == 4
    assert deleted["grid_id"] == 55
    assert deleted["confirm"] is True


@pytest.mark.asyncio
async def test_update_grid_requires_at_least_one_field() -> None:
    class StubClient:
        async def update_grid(self, **kwargs):
            return kwargs

    with pytest.raises(ValueError, match="At least one field"):
        await update_grid(FakeContext(StubClient()), grid_id=55)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_statuses_returns_normalized_results() -> None:
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
                                "color": "#1A67A3",
                                "position": 1,
                            }
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await list_statuses(FakeContext(client))

    assert result.count == 1
    assert result.results[0].name == "New"
    assert result.results[0].is_default is True
    assert result.results[0].is_closed is False

    await client.aclose()


@pytest.mark.asyncio
async def test_list_notifications_returns_normalized_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/notifications":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 5,
                                "subject": "You were mentioned",
                                "readIAN": False,
                                "createdAt": "2026-03-20T10:00:00Z",
                                "_links": {
                                    "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await list_notifications(FakeContext(client))

    assert result.count == 1
    assert result.total == 1
    assert result.results[0].subject == "You were mentioned"
    assert result.results[0].read is False
    assert result.results[0].project_name == "Demo"

    await client.aclose()


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
    assert received[0]["parent_work_package_id"] == 7
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

    with pytest.raises(ValueError, match=r"items\[0\].parent_work_package_id must be at least 1"):
        await bulk_update_work_packages(  # type: ignore[arg-type]
            FakeContext(StubClient()),
            items=[{"work_package_id": 1, "parent_work_package_id": -1}],
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
            {"work_package_id": 10, "subject": "New title", "status": "In progress", "parent_work_package_id": 30},
            {"work_package_id": 20, "due_date": "2026-12-31"},
        ],
        confirm=True,
    )

    assert len(received) == 2
    assert received[0]["work_package_id"] == 10
    assert received[0]["subject"] == "New title"
    assert received[0]["status"] == "In progress"
    assert received[0]["parent_work_package_id"] == 30
    assert received[1]["due_date"] == "2026-12-31"


def test_validate_work_package_ref_accepts_numeric_and_semantic() -> None:
    assert _validate_work_package_ref(42) == "42"
    assert _validate_work_package_ref("42") == "42"
    assert _validate_work_package_ref("PROJ-123") == "PROJ-123"
    # Surrounding whitespace is normalized.
    assert _validate_work_package_ref("  PROJ-7  ") == "PROJ-7"


def test_validate_work_package_ref_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="work_package_id is required"):
        _validate_work_package_ref("   ")
    with pytest.raises(ValueError, match="positive integer id or a work package reference"):
        _validate_work_package_ref("PROJ/123")
    with pytest.raises(ValueError, match="positive integer id or a work package reference"):
        _validate_work_package_ref("PROJ 123")
    with pytest.raises(ValueError, match="positive integer id or a work package reference"):
        # A project identifier without a "-<number>" suffix is not a work package ref.
        _validate_work_package_ref("PROJ")
    with pytest.raises(ValueError, match="must be at least 1"):
        _validate_work_package_ref("0")


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
