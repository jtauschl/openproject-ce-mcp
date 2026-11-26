"""A filter or an order whose value another entity shows is closed by that entity's setting too.

The work package row shows the name of its status, its project, its version, its users and its sprint, so a sort by
one of those columns is decided by the work package setting. It does not show whether a status is closed, where a
status, type or priority stands in its list, whether a version is open, the name of its bucket, the dates of its
sprint, or the id of a user: the server filters and orders by those values (`status_id` with the operator `o`, the
`position` of the association, the sprint name and then its dates, the user's lastname, firstname and then id), so the
setting of the entity that shows the value has to close the
call. A tie-break key is no exception: it orders rows that are equal in the shown key and still shows the order
of the hidden values.

The expectation is a literal table here, not read from `OTHER_ENTITY_OWNERS_OF_*`: a removed row fails a test instead
of removing its own case. Stated boundary: the sort definitions of the core columns were read in the server source for
16.0 to 17.9 (identical for these columns; `target_versions` and `observed_in_versions` appear with 17.8 and 17.9);
those of `sprint` and `backlog_bucket` were read once from the upstream default branch and not per release;
"before any request" is asserted on the call lists of the work package fake only; a project phase is not a pair (the row leaves out an inactive phase, as the sort does).
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest
from _client_test_helpers import make_settings
from test_app_work_package_service import _FakeWorkPackageApi, _payload, _record, _service, _summary

from openproject_ce_mcp import models
from openproject_ce_mcp.app.errors import InvalidInputError, NotFoundError
from openproject_ce_mcp.app.policies.work_package_query_policy import ensure_query_allowed
from openproject_ce_mcp.app.ports.work_package_ref import ResolvedRecord
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.work_package_columns import (
    OTHER_ENTITY_OWNERS_OF_COLUMN,
    OTHER_ENTITY_OWNERS_OF_FILTER,
)

FILTER_PAIRS = {
    "open_only": (("status", "is_closed"),),
    "overdue_only": (("status", "is_closed"),),
    "version_status": (("version", "status"),),
}
COLUMN_PAIRS = {
    "status": (("status", "position"),),
    "type": (("type", "position"),),
    "priority": (("priority", "position"),),
    "sprint": (("sprint", "start_date"), ("sprint", "finish_date")),
    "backlog_bucket": (("backlog_bucket", "name"),),
    "author": (("user", "id"), ("principal", "id")),
    "assigned_to": (("user", "id"), ("group", "id"), ("principal", "id")),
    "assignee": (("user", "id"), ("group", "id"), ("principal", "id")),
    "responsible": (("user", "id"), ("group", "id"), ("principal", "id")),
}
# The class that carries the field of each entity here.
SUMMARY_OF = {
    "status": models.StatusSummary,
    "type": models.TypeSummary,
    "priority": models.PrioritySummary,
    "version": models.VersionSummary,
    "sprint": models.SprintSummary,
    "backlog_bucket": models.BacklogBucketSummary,
    "user": models.UserSummary,
    "group": models.GroupSummary,
    "principal": models.PrincipalSummary,
}


def _hiding(entity: str, *fields: str):
    return dataclasses.replace(make_settings(), hidden_fields={entity: tuple(fields)})


def _refusal(entity: str, field: str, use: str, name: str) -> str:
    return (
        f"OpenProject {entity.replace('_', ' ')} field '{field}' is hidden by {HIDE_FIELD_ENV_BY_ENTITY[entity]} "
        f"and cannot be used to {use} ('{name}')."
    )


def test_the_pair_tables_are_the_ones_written_here() -> None:
    assert OTHER_ENTITY_OWNERS_OF_FILTER == FILTER_PAIRS
    assert OTHER_ENTITY_OWNERS_OF_COLUMN == COLUMN_PAIRS


@pytest.mark.parametrize(
    ("entity", "field"),
    sorted({pair for pairs in (*FILTER_PAIRS.values(), *COLUMN_PAIRS.values()) for pair in pairs}),
)
def test_every_pair_names_an_entity_with_a_setting_and_a_field_of_its_summary(entity: str, field: str) -> None:
    assert entity in HIDE_FIELD_ENV_BY_ENTITY
    assert field in {f.name for f in dataclasses.fields(SUMMARY_OF[entity])}


@pytest.mark.parametrize(
    ("name", "entity", "field"),
    [(name, entity, field) for name, pairs in sorted(FILTER_PAIRS.items()) for entity, field in pairs],
)
def test_a_filter_whose_value_another_entity_shows_is_closed_by_that_entity(name: str, entity: str, field: str) -> None:
    with pytest.raises(InvalidInputError) as refusal:
        ensure_query_allowed(settings=_hiding(entity, field), filters=[name], sort_fields=[], group_by=None)

    assert str(refusal.value) == _refusal(entity, field, "filter", name)
    ensure_query_allowed(settings=_hiding(entity, "name"), filters=[name], sort_fields=[], group_by=None)
    ensure_query_allowed(settings=_hiding("work_package", "description"), filters=[name], sort_fields=[], group_by=None)


@pytest.mark.parametrize(
    ("column", "entity", "field"),
    [(column, entity, field) for column, pairs in sorted(COLUMN_PAIRS.items()) for entity, field in pairs],
)
def test_a_column_whose_value_another_entity_shows_is_closed_by_that_entity_for_sort_and_group(
    column: str, entity: str, field: str
) -> None:
    settings = _hiding(entity, field)
    with pytest.raises(InvalidInputError) as sort_refusal:
        ensure_query_allowed(settings=settings, filters=[], sort_fields=[column], group_by=None)
    with pytest.raises(InvalidInputError) as group_refusal:
        ensure_query_allowed(settings=settings, filters=[], sort_fields=[], group_by=column)

    assert str(sort_refusal.value) == _refusal(entity, field, "sort", column)
    assert str(group_refusal.value) == _refusal(entity, field, "group", column)
    other = "id" if field == "name" else "name"
    ensure_query_allowed(settings=_hiding(entity, other), filters=[], sort_fields=[column], group_by=column)


# The columns the work package row names, with the settings that must NOT close them: the names are decided by the work
# package setting (the user columns also sort by the `id` of the user, which has its own pair).
NAME_COLUMNS = {
    "project": {"project": ("*",)},
    "category": {"category": ("*",)},
    "version": {"version": ("*",)},
    "target_versions": {"version": ("*",)},
    "author": {"user": ("firstname", "lastname", "name", "login")},
    "assigned_to": {"user": ("firstname", "lastname", "name"), "group": ("name",), "principal": ("name",)},
    "assignee": {"user": ("firstname", "lastname", "name"), "group": ("name",), "principal": ("name",)},
    "responsible": {"user": ("firstname", "lastname", "name"), "group": ("name",), "principal": ("name",)},
}


@pytest.mark.parametrize(("column", "hidden"), sorted(NAME_COLUMNS.items()))
def test_a_column_the_work_package_row_names_is_not_closed_by_the_name_of_another_entity(
    column: str, hidden: dict[str, tuple[str, ...]]
) -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields=hidden)

    ensure_query_allowed(settings=settings, filters=[], sort_fields=[column], group_by=column)


# --- through the service: refused before any request ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "arguments", "entity", "field"),
    [
        ("list", {"open_only": True}, "status", "is_closed"),
        ("list", {"overdue_only": True}, "status", "is_closed"),
        ("list", {"version_status": "open"}, "version", "status"),
        ("search", {"search": "x", "open_only": True}, "status", "is_closed"),
        ("search", {"search": "x", "overdue_only": True}, "status", "is_closed"),
        ("list", {"sort_by": [models.SortCriterion(field="status", direction="asc")]}, "status", "position"),
        ("list", {"sort_by": [models.SortCriterion(field="type", direction="asc")]}, "type", "position"),
        ("list", {"group_by": "priority"}, "priority", "position"),
    ],
)
async def test_the_list_and_search_tools_refuse_before_any_request(
    method: str, arguments: dict[str, object], entity: str, field: str
) -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api, settings=_hiding(entity, field))

    with pytest.raises(InvalidInputError, match=f"{entity.replace('_', ' ')} field '{field}' is hidden"):
        await getattr(service, method)(**arguments)

    assert api.list_calls == [] and api.get_calls == [] and api.validate_create_calls == []


@pytest.mark.asyncio
async def test_list_my_open_is_refused_while_the_closed_flag_of_a_status_is_hidden() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api, settings=_hiding("status", "is_closed"))

    with pytest.raises(InvalidInputError) as refusal:
        await service.list_my_open()

    assert str(refusal.value) == _refusal("status", "is_closed", "filter", "open_only")
    assert api.list_calls == [] and api.get_calls == [] and api.validate_create_calls == []


@pytest.mark.asyncio
async def test_the_same_calls_complete_while_nothing_is_hidden() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    await service.list(open_only=True, version_status="open", group_by="priority")
    await service.list_my_open()

    assert len(api.list_calls) == 2


# --- a typed display id leaves a hidden display_id out of the result ------------------------------------------------


class _ExactMatchApi(_FakeWorkPackageApi):
    """The text search finds nothing, the lookup of the typed reference by id finds the work package."""

    def __init__(self) -> None:
        super().__init__()
        self._records_by_id[6] = _record(6, summary=dataclasses.replace(_summary(6), display_id="DEMO-6"))

    async def list(self, *, filters, **kwargs):
        found = self._raw_elements
        if not any("id" in item for item in filters):
            self._raw_elements = []
        try:
            return await super().list(filters=filters, **kwargs)
        finally:
            self._raw_elements = found


async def _resolve_typed_display_id(reference, *, write=False):
    if str(reference) in {"DEMO-6", "6"}:
        return ResolvedRecord(id=6, payload=_payload(6))
    raise NotFoundError(f"OpenProject work package '{reference}' was not found.")


class _Client:
    def __init__(self, service) -> None:
        self.work_package = service


async def _search_through_the_registered_tool(settings, reference: str) -> dict:
    service, _ = _service(_ExactMatchApi(), settings=settings, resolve_work_package_record=_resolve_typed_display_id)
    context = SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=SimpleNamespace(client=_Client(service)))
    )
    tool = {t.name: t for t in create_app(settings)._tool_manager.list_tools()}["search_work_packages"]
    return json.loads(await tool.fn(context, search=reference))


@pytest.mark.asyncio
async def test_a_typed_display_id_returns_no_hidden_display_id_anywhere() -> None:
    visible = await _search_through_the_registered_tool(make_settings(), "DEMO-6")
    hidden = await _search_through_the_registered_tool(_hiding("work_package", "display_id"), "DEMO-6")

    assert visible["exact_match"]["id"] == 6 and visible["exact_match"]["display_id"] == "DEMO-6"
    assert hidden["exact_match"]["id"] == 6
    assert "DEMO-6" not in json.dumps(hidden) and "display_id" not in json.dumps(hidden)
