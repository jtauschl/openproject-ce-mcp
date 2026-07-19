"""Snapshot/shape tests for the OPM-48 ListResult consolidation and the
OPM-222 ConfirmationHeader (WriteResult family) consolidation.

Guards against the two failure modes a base-class migration could silently
introduce: (1) field order / serialization drift on any of the 36
`*ListResult` classes or 24 confirm-gated write-result classes, and (2) loss
of concrete element/result typing, which a naive `Generic[T]` base (rejected
during OPM-48 planning) would have caused -- verified here by literally
reproducing that rejected shape and showing it degrades the MCP output
schema, then showing our actual non-generic bases do not.
"""

from __future__ import annotations

import dataclasses
import typing
from dataclasses import fields as dataclass_fields
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from openproject_ce_mcp import models
from openproject_ce_mcp.presentation import _to_payload

# Captured from `main` before the OPM-48 base-class migration landed (via
# `dataclasses.fields()` on every *ListResult class) -- the source of truth
# this test protects. Do not "fix" this fixture to match a future change
# without confirming the new field order is actually intended.
EXPECTED_FIELD_ORDER: dict[str, list[str]] = {
    "ActionListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "ActivityListResult": ["count", "results"],
    "AttachmentListResult": ["count", "results"],
    "BoardListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "CapabilityListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "CategoryListResult": ["count", "results"],
    "DocumentListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "EmojiReactionListResult": ["count", "results"],
    "FileLinkListResult": ["count", "results"],
    "GridListResult": ["count", "results"],
    "GroupListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "HelpTextListResult": ["count", "results"],
    "MembershipListResult": ["count", "results"],
    "NewsListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "NonWorkingDayListResult": ["count", "results"],
    "NotificationListResult": ["count", "total", "results"],
    "PrincipalListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "PriorityListResult": ["count", "results"],
    "ProjectListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "ProjectPhaseDefinitionListResult": ["count", "results"],
    "QueryFilterInstanceSchemaListResult": ["count", "results"],
    "RelationListResult": ["count", "results"],
    "ReminderListResult": ["count", "results"],
    "RoleListResult": ["count", "results"],
    "SprintListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "StatusListResult": ["count", "results"],
    "TimeEntryActivityListResult": ["count", "results"],
    "TimeEntryListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "TypeListResult": ["count", "results"],
    "UserListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "VersionListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "ViewListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "WatcherListResult": ["count", "results"],
    "WikiPageListResult": ["count", "total", "results"],
    "WorkPackageListResult": ["offset", "limit", "total", "count", "next_offset", "truncated", "results"],
    "WorkingDayListResult": ["count", "results"],
}


def _all_list_result_classes() -> dict[str, type]:
    return {name: getattr(models, name) for name in dir(models) if name.endswith("ListResult")}


def test_every_list_result_class_is_captured_in_the_fixture() -> None:
    found = set(_all_list_result_classes())
    assert found == set(EXPECTED_FIELD_ORDER), (
        f"ListResult classes changed since the fixture was captured: "
        f"added={found - set(EXPECTED_FIELD_ORDER)} removed={set(EXPECTED_FIELD_ORDER) - found}"
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_FIELD_ORDER))
def test_list_result_field_order_unchanged(name: str) -> None:
    cls = getattr(models, name)
    actual = [f.name for f in dataclass_fields(cls)]
    assert actual == EXPECTED_FIELD_ORDER[name]


def _dummy_for_type(tp: Any) -> Any:  # noqa: ANN401
    origin = typing.get_origin(tp)
    if origin is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return _dummy_for_type(args[0]) if args else None
    if origin in (list, tuple, set, frozenset):
        return origin()
    if origin is dict:
        return {}
    if tp is int:
        return 1
    if tp is float:
        return 1.0
    if tp is bool:
        return False
    if tp is str:
        return "x"
    if dataclasses.is_dataclass(tp):
        return _dummy_instance(tp)
    return None


def _dummy_instance(cls: type) -> Any:  # noqa: ANN401
    hints = typing.get_type_hints(cls)
    kwargs = {f.name: _dummy_for_type(hints[f.name]) for f in dataclass_fields(cls)}
    return cls(**kwargs)


@pytest.mark.parametrize("name", sorted(EXPECTED_FIELD_ORDER))
def test_list_result_to_payload_drops_count_and_truncated(name: str) -> None:
    cls = getattr(models, name)
    instance = _dummy_instance(cls)
    out = _to_payload(instance)
    assert "count" not in out
    assert "truncated" not in out
    expected_keys = [f for f in EXPECTED_FIELD_ORDER[name] if f not in ("count", "truncated")]
    assert list(out.keys()) == expected_keys


# --- OPM-222: ConfirmationHeader (WriteResult family) ----------------------

# The 21 `*WriteResult`-suffixed classes plus 3 same-shaped-but-differently-
# named classes (ProjectCopyResult, RelationUpdateResult, NotificationMarkResult)
# that OPM-222 classified. Discovery mirrors _all_list_result_classes()'s
# suffix filter, widened by an explicit small set for the 3 non-suffix names
# -- unlike *ListResult, this family doesn't share one common suffix.
_EXTRA_CONFIRMATION_HEADER_CLASSES = frozenset({"ProjectCopyResult", "RelationUpdateResult", "NotificationMarkResult"})


def _all_write_result_classes() -> dict[str, type]:
    return {
        name: getattr(models, name)
        for name in dir(models)
        if name.endswith("WriteResult") or name in _EXTRA_CONFIRMATION_HEADER_CLASSES
    }


# Captured from `main` before the OPM-222 ConfirmationHeader migration landed
# (via `dataclasses.fields()` on every class below) -- the source of truth
# this test protects. Do not "fix" this fixture to match a future change
# without confirming the new field order is actually intended.
# BulkWorkPackageWriteResult is included as a fixed control: OPM-222
# deliberately leaves it unconsolidated (no `ready` field, batch-shaped), so
# its entry must never gain a ConfirmationHeader-shaped prefix.
EXPECTED_WRITE_RESULT_FIELD_ORDER: dict[str, list[str]] = {
    "ActivityWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "work_package_id",
        "payload",
        "validation_errors",
        "result",
    ],
    "AttachmentWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "attachment_id",
        "work_package_id",
        "payload",
        "validation_errors",
        "result",
    ],
    "BoardWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "board_id",
        "project",
        "payload",
        "validation_errors",
        "result",
    ],
    "BulkWorkPackageWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "total",
        "succeeded",
        "failed",
        "message",
        "items",
    ],
    "DocumentWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "document_id",
        "project",
        "payload",
        "validation_errors",
        "result",
    ],
    "EmojiReactionWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "activity_id",
        "reaction",
        "result",
    ],
    "FavoriteWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "project_id",
        "project",
    ],
    "FileLinkWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "file_link_id",
        "work_package_id",
        "validation_errors",
        "result",
    ],
    "GridWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "grid_id",
        "scope",
        "payload",
        "validation_errors",
        "result",
    ],
    "GroupWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "group_id",
        "payload",
        "validation_errors",
        "result",
    ],
    "MembershipWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "membership_id",
        "project",
        "payload",
        "validation_errors",
        "result",
    ],
    "NewsWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "news_id",
        "project",
        "payload",
        "validation_errors",
        "result",
    ],
    "NotificationMarkResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "notification_id",
    ],
    "ProjectCopyResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "source_project_id",
        "source_project",
        "payload",
        "validation_errors",
        "job_status_id",
        "job_status_url",
    ],
    "ProjectWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "project_id",
        "project",
        "payload",
        "validation_errors",
        "result",
    ],
    "RelationUpdateResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "relation_id",
        "payload",
        "result",
    ],
    "RelationWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "relation_id",
        "work_package_id",
        "payload",
        "validation_errors",
        "result",
    ],
    "ReminderWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "reminder_id",
        "payload",
        "validation_errors",
        "result",
    ],
    "TimeEntryWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "time_entry_id",
        "project",
        "payload",
        "validation_errors",
        "result",
    ],
    "UserPreferencesWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "payload",
        "result",
    ],
    "UserWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "user_id",
        "payload",
        "validation_errors",
        "result",
    ],
    "VersionWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "version_id",
        "project",
        "payload",
        "validation_errors",
        "result",
    ],
    "WatcherWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "work_package_id",
        "watcher_user_id",
        "validation_errors",
        "result",
    ],
    "WorkPackageWriteResult": [
        "action",
        "confirmed",
        "requires_confirmation",
        "ready",
        "message",
        "work_package_id",
        "project",
        "payload",
        "validation_errors",
        "result",
    ],
}


def test_every_write_result_class_is_captured_in_the_fixture() -> None:
    found = set(_all_write_result_classes())
    assert found == set(EXPECTED_WRITE_RESULT_FIELD_ORDER), (
        f"WriteResult-family classes changed since the fixture was captured: "
        f"added={found - set(EXPECTED_WRITE_RESULT_FIELD_ORDER)} "
        f"removed={set(EXPECTED_WRITE_RESULT_FIELD_ORDER) - found}"
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_WRITE_RESULT_FIELD_ORDER))
def test_write_result_field_order_unchanged(name: str) -> None:
    cls = getattr(models, name)
    actual = [f.name for f in dataclass_fields(cls)]
    assert actual == EXPECTED_WRITE_RESULT_FIELD_ORDER[name]


def test_confirmation_header_subclasses_are_registered() -> None:
    for name in sorted(EXPECTED_WRITE_RESULT_FIELD_ORDER):
        if name == "BulkWorkPackageWriteResult":
            continue
        cls = getattr(models, name)
        assert issubclass(cls, models.ConfirmationHeader), f"{name} should subclass ConfirmationHeader"
    assert not issubclass(models.BulkWorkPackageWriteResult, models.ConfirmationHeader), (
        "BulkWorkPackageWriteResult is deliberately excluded (no `ready` field, batch-shaped)"
    )


@pytest.mark.asyncio
async def test_confirmation_header_result_field_keeps_concrete_type_in_mcp_schema() -> None:
    """Proves introducing ConfirmationHeader doesn't affect MCP output schema
    generation for `result` (a scalar Optional[Concrete] field, so the right
    template is test_project_detail_ancestors_boundary_in_mcp_schema's
    anyOf/$ref check, not the results.items list check used for PageResult/
    CollectionResult's `results` field).
    """
    mcp = FastMCP("shape-test")

    @mcp.tool()
    def project_write_probe() -> models.ProjectWriteResult:
        return _dummy_instance(models.ProjectWriteResult)

    @mcp.tool()
    def favorite_write_probe() -> models.FavoriteWriteResult:
        return _dummy_instance(models.FavoriteWriteResult)

    tools = {t.name: t for t in await mcp.list_tools()}

    write_schema = tools["project_write_probe"].outputSchema
    assert list(write_schema["properties"]) == EXPECTED_WRITE_RESULT_FIELD_ORDER["ProjectWriteResult"]
    result_field = write_schema["properties"]["result"]
    result_refs = [entry["$ref"] for entry in result_field.get("anyOf", []) if "$ref" in entry]
    assert result_refs, f"expected a $ref among result's anyOf branches, got {result_field!r}"
    result_summary_schema = write_schema["$defs"][result_refs[0].rsplit("/", 1)[-1]]
    assert result_summary_schema["title"] == "ProjectSummary"

    favorite_schema = tools["favorite_write_probe"].outputSchema
    assert list(favorite_schema["properties"]) == EXPECTED_WRITE_RESULT_FIELD_ORDER["FavoriteWriteResult"]


_RejectedT = typing.TypeVar("_RejectedT")


@dataclasses.dataclass
class _RejectedGenericPageResult(typing.Generic[_RejectedT]):
    """Module-level (not function-local) so FastMCP's `eval_str=True` signature
    evaluation can resolve it as a return-type annotation -- reproduces the
    Generic[T]-with-results-on-the-base design rejected during OPM-48 planning.
    """

    total: int
    results: list[_RejectedT]


@dataclasses.dataclass
class _RejectedGenericProjectListResult(_RejectedGenericPageResult[models.ProjectSummary]):
    pass


def test_version_detail_and_news_detail_keep_their_own_class_identity() -> None:
    # Guards against ever "simplifying" the subclass back into a bare alias
    # (VersionDetail = VersionSummary), which would silently rename the
    # registered get_version/get_news MCP output schema title.
    assert models.VersionDetail.__name__ == "VersionDetail"
    assert models.NewsDetail.__name__ == "NewsDetail"
    assert models.VersionDetail is not models.VersionSummary
    assert models.NewsDetail is not models.NewsSummary


@pytest.mark.asyncio
async def test_version_detail_and_news_detail_schema_title_matches_class_name() -> None:
    mcp = FastMCP("shape-test")

    @mcp.tool()
    def get_version_probe() -> models.VersionDetail:
        return _dummy_instance(models.VersionDetail)

    @mcp.tool()
    def get_news_probe() -> models.NewsDetail:
        return _dummy_instance(models.NewsDetail)

    tools = {t.name: t for t in await mcp.list_tools()}
    assert tools["get_version_probe"].outputSchema["title"] == "VersionDetail"
    assert tools["get_news_probe"].outputSchema["title"] == "NewsDetail"


@pytest.mark.asyncio
async def test_page_result_and_collection_result_keep_concrete_element_types() -> None:
    """Reproduces the rejected Generic[T]-with-results-on-the-base design
    directly, to show what it would have done to the MCP output schema, then
    proves our actual PageResult/CollectionResult bases don't have that problem.
    """
    mcp = FastMCP("shape-test")

    @mcp.tool()
    def rejected_probe() -> _RejectedGenericProjectListResult:
        return _RejectedGenericProjectListResult(total=1, results=[_dummy_instance(models.ProjectSummary)])

    @mcp.tool()
    def project_list_probe() -> models.ProjectListResult:
        return _dummy_instance(models.ProjectListResult)

    @mcp.tool()
    def role_list_probe() -> models.RoleListResult:
        return _dummy_instance(models.RoleListResult)

    tools = {t.name: t for t in await mcp.list_tools()}

    # The rejected design: `results.items` degrades to an untyped `{}`.
    rejected_items_schema = tools["rejected_probe"].outputSchema["properties"]["results"]["items"]
    assert rejected_items_schema == {}

    # Our actual Group A (PageResult) and Group B (CollectionResult) design:
    # `results.items` stays a concrete $ref to the real summary model.
    for tool_name, expected_ref_name in [
        ("project_list_probe", "ProjectSummary"),
        ("role_list_probe", "RoleSummary"),
    ]:
        schema = tools[tool_name].outputSchema
        items_schema = schema["properties"]["results"]["items"]
        assert "$ref" in items_schema, f"{tool_name}: expected a concrete $ref, got {items_schema!r}"
        ref_defs = schema.get("$defs", {})
        ref_name = items_schema["$ref"].rsplit("/", 1)[-1]
        assert ref_name in ref_defs
        assert ref_defs[ref_name]["title"] == expected_ref_name


@pytest.mark.asyncio
async def test_project_detail_ancestors_boundary_in_mcp_schema() -> None:
    """OPM-221: get_project (ProjectDetail) exposes ancestors/ancestors_truncated;
    list_projects rows (ProjectSummary) and ProjectWriteResult.result (also
    ProjectSummary) must NOT -- proves the Detail/Summary split actually holds
    at the schema boundary, not just in the dataclass definitions.
    """
    mcp = FastMCP("shape-test")

    @mcp.tool()
    def project_detail_probe() -> models.ProjectDetail:
        return _dummy_instance(models.ProjectDetail)

    @mcp.tool()
    def project_list_probe() -> models.ProjectListResult:
        return _dummy_instance(models.ProjectListResult)

    @mcp.tool()
    def project_write_probe() -> models.ProjectWriteResult:
        return _dummy_instance(models.ProjectWriteResult)

    tools = {t.name: t for t in await mcp.list_tools()}

    detail_schema = tools["project_detail_probe"].outputSchema
    assert "ancestors" in detail_schema["properties"]
    assert "ancestors_truncated" in detail_schema["properties"]

    list_schema = tools["project_list_probe"].outputSchema
    items_ref = list_schema["properties"]["results"]["items"]["$ref"]
    project_summary_schema = list_schema["$defs"][items_ref.rsplit("/", 1)[-1]]
    assert project_summary_schema["title"] == "ProjectSummary"
    assert "ancestors" not in project_summary_schema["properties"]

    write_schema = tools["project_write_probe"].outputSchema
    result_field = write_schema["properties"]["result"]
    result_refs = [entry["$ref"] for entry in result_field.get("anyOf", []) if "$ref" in entry]
    assert result_refs, f"expected a $ref among result's anyOf branches, got {result_field!r}"
    result_summary_schema = write_schema["$defs"][result_refs[0].rsplit("/", 1)[-1]]
    assert result_summary_schema["title"] == "ProjectSummary"
    assert "ancestors" not in result_summary_schema["properties"]
