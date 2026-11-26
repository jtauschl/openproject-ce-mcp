"""The typed `project` filter of the list and search tools adds the subprojects only while the hierarchy is shown.

OpenProject expands a named project to every descendant unless told otherwise, so the work packages it returns show
which projects sit below the named one. With the project `parent_id`, `parent_name` or `ancestors` hidden the
filter names the project alone and sends `includeSubprojects=false`; any other hidden project field changes nothing.
Stated boundary: the two tools that take a `project` are covered here; a saved query's own flag is judged in
`test_stored_query_policy.py`.
"""

from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings
from test_app_work_package_service import _FakeWorkPackageApi, _payload, _ReadableIds, _service

HIERARCHY_FIELDS = ["parent_id", "parent_name", "ancestors"]


def _hiding(*fields: str, **changes):
    return dataclasses.replace(make_settings(), hidden_fields={"project": tuple(fields)}, **changes)


async def _call(method: str, service) -> None:
    arguments = {"search": "x"} if method == "search" else {}
    await getattr(service, method)(project="demo", limit=2, **arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "search"])
@pytest.mark.parametrize("field", HIERARCHY_FIELDS)
async def test_a_hidden_hierarchy_field_makes_the_filter_name_the_project_alone_under_every_project(
    method: str, field: str
) -> None:
    api = _FakeWorkPackageApi(raw_elements=[_payload(1)], server_total=1)
    readable = _ReadableIds({1, 5}, descendants={1: {5}})
    service, _ = _service(api, settings=_hiding(field), readable_projects=readable)

    await _call(method, service)

    call = api.list_calls[0]
    assert {"project_id": {"operator": "=", "values": ["1"]}} in call["filters"]
    assert call["include_subprojects"] is False
    assert readable.descendant_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "search"])
@pytest.mark.parametrize("field", HIERARCHY_FIELDS)
async def test_a_hidden_hierarchy_field_stops_a_restricted_scope_from_naming_the_readable_descendants(
    method: str, field: str
) -> None:
    api = _FakeWorkPackageApi(raw_elements=[_payload(1)], server_total=1)
    readable = _ReadableIds({1, 5}, descendants={1: {5}})
    service, _ = _service(
        api,
        settings=_hiding(field, read_projects=("demo",)),
        project_id_to_identifier={1: "demo"},
        readable_projects=readable,
    )

    await _call(method, service)

    call = api.list_calls[0]
    assert {"project_id": {"operator": "=", "values": ["1"]}} in call["filters"]
    assert call["include_subprojects"] is False
    assert readable.descendant_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "search"])
async def test_another_hidden_project_field_leaves_the_expansion_alone(method: str) -> None:
    api = _FakeWorkPackageApi(raw_elements=[_payload(1)], server_total=1)
    service, _ = _service(api, settings=_hiding("description"), readable_projects=_ReadableIds({1}))

    await _call(method, service)

    call = api.list_calls[0]
    assert {"project_id": {"operator": "=", "values": ["1"]}} in call["filters"]
    assert call["include_subprojects"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("read_projects", [("*",), ("demo",)], ids=["unrestricted scope", "restricted scope"])
@pytest.mark.parametrize("field", HIERARCHY_FIELDS)
async def test_the_exact_match_lookup_of_a_search_does_not_expand_the_project_either(
    read_projects: tuple[str, ...], field: str
) -> None:
    api = _FakeWorkPackageApi(raw_elements=[_payload(1)], server_total=1)
    service, _ = _service(
        api,
        settings=_hiding(field, read_projects=read_projects),
        project_id_to_identifier={1: "demo"},
        readable_projects=_ReadableIds({1, 5}, descendants={1: {5}}),
    )

    await service.search(search="6", project="demo", limit=2)

    exact_lookups = [c for c in api.list_calls if {"id": {"operator": "=", "values": ["6"]}} in c["filters"]]
    assert len(exact_lookups) == 1
    assert {"project_id": {"operator": "=", "values": ["1"]}} in exact_lookups[0]["filters"]
    assert exact_lookups[0]["include_subprojects"] is False
    assert all(call["include_subprojects"] is False for call in api.list_calls)


@pytest.mark.asyncio
async def test_the_exact_match_lookup_keeps_the_server_default_while_the_hierarchy_is_shown() -> None:
    api = _FakeWorkPackageApi(raw_elements=[_payload(1)], server_total=1)
    service, _ = _service(api, settings=_hiding("description"), readable_projects=_ReadableIds({1}))

    await service.search(search="6", project="demo", limit=2)

    exact_lookups = [c for c in api.list_calls if {"id": {"operator": "=", "values": ["6"]}} in c["filters"]]
    assert len(exact_lookups) == 1
    assert exact_lookups[0]["include_subprojects"] is None
