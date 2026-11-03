from __future__ import annotations

import asyncio

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from openproject_ce_mcp import tools
from openproject_ce_mcp import tools_runtime as _tools_runtime
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.tool_annotations import build_tool_annotations

# (destructive, idempotent) for every tool that changes data. Hand-written on
# purpose: a write tool annotated read-only would let clients that skip
# confirmation for read-only tools run it without a human.
EXPECTED_WRITE_HINTS: dict[str, tuple[bool, bool]] = {
    "add_work_package_comment": (False, False),
    "bulk_create_work_packages": (True, False),
    "bulk_update_work_packages": (True, True),
    "cancel_recurring_meeting_occurrence": (True, True),
    "copy_project": (False, False),
    "create_board": (False, False),
    "create_container_attachment": (False, False),
    "create_grid": (False, False),
    "create_group": (False, False),
    "create_meeting": (False, False),
    "create_meeting_agenda_item": (False, False),
    "create_meeting_outcome": (False, False),
    "create_meeting_section": (False, False),
    "create_membership": (False, False),
    "create_news": (False, False),
    "create_project": (False, False),
    "create_recurring_meeting": (False, False),
    "create_storage": (False, False),
    "create_subtask": (True, False),
    "create_time_entry": (False, False),
    "create_time_entry_until": (False, False),
    "create_user": (False, False),
    "create_user_non_working_time": (False, False),
    "create_user_working_hours": (False, False),
    "create_version": (False, False),
    "create_work_package": (True, False),
    "create_work_package_attachment": (False, False),
    "create_work_package_relation": (True, False),
    "create_work_package_reminder": (False, False),
    "create_work_package_wiki_link": (False, False),
    "delete_attachment": (True, True),
    "delete_board": (True, True),
    "delete_file_link": (True, True),
    "delete_grid": (True, True),
    "delete_group": (True, False),
    "delete_meeting": (True, True),
    "delete_meeting_agenda_item": (True, True),
    "delete_meeting_outcome": (True, True),
    "delete_meeting_section": (True, True),
    "delete_membership": (True, True),
    "delete_news": (True, True),
    "delete_project": (True, False),
    "delete_recurring_meeting": (True, True),
    "delete_relation": (True, True),
    "delete_reminder": (True, True),
    "delete_storage": (True, True),
    "delete_time_entry": (True, True),
    "delete_user": (True, False),
    "delete_user_non_working_time": (True, True),
    "delete_user_working_hours": (True, True),
    "delete_version": (True, True),
    "delete_work_package": (True, True),
    "delete_work_package_wiki_link": (True, True),
    "end_recurring_meeting": (True, False),
    "init_recurring_meeting_occurrence": (True, True),
    "mark_notifications_read": (True, False),
    "mark_notifications_unread": (True, False),
    "set_project_favorite": (True, True),
    "set_query_starred": (True, True),
    "set_user_locked": (True, True),
    "set_work_package_watcher": (True, True),
    "toggle_activity_emoji_reaction": (True, False),
    "update_board": (True, False),
    "update_document": (True, True),
    "update_grid": (True, True),
    "update_group": (True, True),
    "update_meeting": (True, False),
    "update_meeting_agenda_item": (True, False),
    "update_meeting_outcome": (True, True),
    "update_meeting_section": (True, True),
    "update_membership": (True, False),
    "update_my_preferences": (True, True),
    "update_news": (True, True),
    "update_project": (True, False),
    "update_recurring_meeting": (True, False),
    "update_relation": (True, False),
    "update_reminder": (True, True),
    "update_storage": (True, True),
    "update_time_entry": (True, True),
    "update_time_entry_until": (True, True),
    "update_user": (True, True),
    "update_user_non_working_time": (True, True),
    "update_user_working_hours": (True, True),
    "update_version": (True, True),
    "update_work_package": (True, True),
    "update_work_package_comment": (True, False),
}

FULL_CATALOG_ENV = {
    "OPENPROJECT_BASE_URL": "https://op.example.com",
    "OPENPROJECT_API_TOKEN": "token",
    "OPENPROJECT_READ_PROJECTS": "*",
    "OPENPROJECT_WRITE_PROJECTS": "*",
    "OPENPROJECT_ENABLE_PERSONAL_READ": "true",
    "OPENPROJECT_ENABLE_PERSONAL_WRITE": "true",
    "OPENPROJECT_ENABLE_ADMIN_READ": "true",
    "OPENPROJECT_ENABLE_ADMIN_WRITE": "true",
    "OPENPROJECT_ENABLE_USER_SCHEDULE_READ": "true",
    "OPENPROJECT_ENABLE_USER_SCHEDULE_WRITE": "true",
    "OPENPROJECT_ENABLE_EXTENDED_READ": "true",
}


@pytest.fixture(scope="module")
def wire_annotations(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, bool]]:
    """Every tool's annotations as a client receives them in tools/list."""
    attachment_root = str(tmp_path_factory.mktemp("attachments"))
    settings = Settings.from_env({**FULL_CATALOG_ENV, "OPENPROJECT_ATTACHMENT_ROOT": attachment_root})
    listed = asyncio.run(create_app(settings).list_tools())
    return {
        tool.name: tool.model_dump(by_alias=True, mode="json", exclude_none=True).get("annotations", {})
        for tool in listed
    }


def test_every_tool_declares_all_four_hints(wire_annotations: dict[str, dict[str, bool]]) -> None:
    hints = {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}

    missing = {name: sorted(hints - set(annotations)) for name, annotations in wire_annotations.items()}

    assert {name: gap for name, gap in missing.items() if gap} == {}


def test_write_tools_carry_the_expected_hints(wire_annotations: dict[str, dict[str, bool]]) -> None:
    actual = {
        name: (annotations["destructiveHint"], annotations["idempotentHint"])
        for name, annotations in wire_annotations.items()
        if not annotations["readOnlyHint"]
    }

    assert actual == EXPECTED_WRITE_HINTS


def test_every_other_tool_is_read_only(wire_annotations: dict[str, dict[str, bool]]) -> None:
    read_tools = set(wire_annotations) - set(EXPECTED_WRITE_HINTS)

    assert {"list_projects", "get_work_package", "search_work_packages", "execute_query", "render_text"} <= read_tools
    for name in read_tools:
        assert wire_annotations[name] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }, name


def test_the_wire_catalog_is_the_whole_annotated_catalog(wire_annotations: dict[str, dict[str, bool]]) -> None:
    assert set(wire_annotations) == set(tools.TOOL_ANNOTATIONS)


def test_no_tool_that_takes_confirm_is_read_only(tmp_path) -> None:
    settings = Settings.from_env({**FULL_CATALOG_ENV, "OPENPROJECT_ATTACHMENT_ROOT": str(tmp_path)})
    listed = asyncio.run(create_app(settings).list_tools())

    writes_marked_read_only = [
        tool.name
        for tool in listed
        if "confirm" in tool.input_schema.get("properties", {})
        and tool.annotations is not None
        and tool.annotations.read_only_hint
    ]

    assert writes_marked_read_only == []


def test_every_tool_is_open_world(wire_annotations: dict[str, dict[str, bool]]) -> None:
    assert {name for name, annotations in wire_annotations.items() if not annotations["openWorldHint"]} == set()


def test_unclassified_write_tool_fails_with_its_name() -> None:
    with pytest.raises(ValueError, match="'archive_project'"):
        build_tool_annotations(read_names=(), write_names=("archive_project", *EXPECTED_WRITE_HINTS))


def test_effect_table_entry_without_a_write_tool_fails() -> None:
    write_names = tuple(name for name in EXPECTED_WRITE_HINTS if name != "init_recurring_meeting_occurrence")

    with pytest.raises(ValueError, match="init_recurring_meeting_occurrence"):
        build_tool_annotations(read_names=(), write_names=write_names)


def test_registration_refuses_a_tool_without_annotations(monkeypatch) -> None:
    async def synthetic_tool() -> str:
        """Synthetic."""
        return "ok"

    monkeypatch.setitem(_tools_runtime._TOOL_FUNCTIONS, synthetic_tool.__name__, synthetic_tool)

    with pytest.raises(RuntimeError, match="synthetic_tool"):
        _tools_runtime.register_selected_tools(
            MCPServer("annotations-test"), names=[synthetic_tool.__name__], annotations={}
        )


def test_a_write_tool_added_to_the_production_classification_without_an_effect_fails_the_build(monkeypatch) -> None:
    monkeypatch.setitem(tools.WRITE_TOOLS_BY_SCOPE, "synthetic_scope", ("archive_project",))

    with pytest.raises(ValueError, match="'archive_project'"):
        tools._classified_tool_annotations()


def test_annotations_cover_exactly_the_classified_tools() -> None:
    classified = {name for names in tools.READ_TOOLS_BY_SCOPE.values() for name in names}
    classified |= {name for names in tools.WRITE_TOOLS_BY_SCOPE.values() for name in names}
    classified |= {*tools.PERSONAL_MUTATION_TOOLS, *tools.ATTACHMENT_UPLOAD_TOOLS}

    assert set(tools.TOOL_ANNOTATIONS) == classified


def test_a_client_receives_the_annotations_over_the_protocol(tmp_path) -> None:
    from mcp.client import Client

    settings = Settings.from_env({**FULL_CATALOG_ENV, "OPENPROJECT_ATTACHMENT_ROOT": str(tmp_path)})

    async def listed_annotations() -> dict[str, ToolAnnotations | None]:
        async with Client(create_app(settings)) as client:
            result = await client.list_tools()
        return {tool.name: tool.annotations for tool in result.tools}

    received = asyncio.run(listed_annotations())

    delete = received["delete_work_package"]
    listing = received["list_projects"]
    assert delete is not None and listing is not None
    assert (delete.read_only_hint, delete.destructive_hint, delete.idempotent_hint, delete.open_world_hint) == (
        False,
        True,
        True,
        True,
    )
    assert listing.read_only_hint is True
