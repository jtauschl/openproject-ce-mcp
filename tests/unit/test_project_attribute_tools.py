"""Project attributes through the project tools: the parameters, their validation and the whole path to HTTP."""

from __future__ import annotations

import dataclasses
import json

import httpx
import pytest
from _tools_test_helpers import FakeContext, make_settings

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.models import SortCriterion
from openproject_ce_mcp.tools import copy_project, create_project, get_project, list_projects, update_project


class _Recorder:
    """Stands in for the client of the tool: records what the tool hands over."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.project = self

    async def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"ok": True}

    async def copy(self, **kwargs):
        self.calls.append(("copy", kwargs))
        return {"ok": True}

    async def create_project(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"ok": True}

    async def update_project(self, **kwargs):
        self.calls.append(("update", kwargs))
        return {"ok": True}


@pytest.mark.asyncio
async def test_list_projects_hands_over_normalized_filters_and_sort_criteria() -> None:
    recorder = _Recorder()

    await list_projects(
        FakeContext(recorder),  # type: ignore[arg-type]
        custom_field_filters={"customField12": {"operator": "=", "values": ["x"]}},
        sort_by=["cf_12:desc", "name"],
    )

    (_, kwargs) = recorder.calls[0]
    assert kwargs["custom_field_filters"] == {"cf_12": {"operator": "=", "values": ["x"]}}
    assert kwargs["sort_by"] == [SortCriterion("cf_12", "desc"), SortCriterion("name", "asc")]


@pytest.mark.asyncio
async def test_list_projects_without_a_query_hands_over_none() -> None:
    recorder = _Recorder()

    await list_projects(FakeContext(recorder))  # type: ignore[arg-type]

    (_, kwargs) = recorder.calls[0]
    assert kwargs["custom_field_filters"] is None and kwargs["sort_by"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"sort_by": ["description"]}, "unknown field 'description'"),
        ({"sort_by": ["name:up"]}, "direction must be"),
        ({"custom_field_filters": {"name": {"operator": "=", "values": []}}}, "must be of the form 'cf_<N>'"),
        ({"custom_field_filters": {"cf_1": {"operator": "??", "values": []}}}, "not a recognized"),
    ],
)
async def test_list_projects_refuses_a_bad_query_before_the_client_is_called(arguments, message) -> None:
    recorder = _Recorder()

    with pytest.raises(ValueError, match=message):
        await list_projects(FakeContext(recorder), **arguments)  # type: ignore[arg-type]

    assert recorder.calls == []


@pytest.mark.asyncio
async def test_the_write_tools_hand_over_the_attributes_stripped_and_validated() -> None:
    recorder = _Recorder()
    context = FakeContext(recorder)  # type: ignore[arg-type]
    values = {" customField1 ": " x ", "customField2": None, "customField3": [1, "a"]}

    await create_project(context, name="Demo", identifier="demo", custom_fields=values)
    await update_project(context, "demo", custom_fields=values)
    await copy_project(context, "demo", name="Copy", identifier="copy", custom_fields=values)

    expected = {"customField1": "x", "customField2": None, "customField3": [1, "a"]}
    assert [kwargs["custom_fields"] for _, kwargs in recorder.calls] == [expected] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["create", "update", "copy"])
@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"customField1": {"a": 1}}, "custom_fields values must be"),
        ({"": 1}, "keys must not be empty"),
        ({f"customField{n}": n for n in range(51)}, "at most 50 entries"),
    ],
)
async def test_the_write_tools_refuse_malformed_attributes(tool, values, message) -> None:
    recorder = _Recorder()
    context = FakeContext(recorder)  # type: ignore[arg-type]
    calls = {
        "create": lambda: create_project(context, name="Demo", identifier="demo", custom_fields=values),
        "update": lambda: update_project(context, "demo", custom_fields=values),
        "copy": lambda: copy_project(context, "demo", name="Copy", identifier="copy", custom_fields=values),
    }

    with pytest.raises(ValueError, match=message):
        await calls[tool]()

    assert recorder.calls == []


@pytest.mark.asyncio
async def test_update_project_counts_attributes_as_a_field_to_update() -> None:
    recorder = _Recorder()
    context = FakeContext(recorder)  # type: ignore[arg-type]

    await update_project(context, "demo", custom_fields={"customField1": "x"})
    with pytest.raises(ValueError, match="At least one field to update is required"):
        await update_project(context, "demo")
    with pytest.raises(ValueError, match="At least one field to update is required"):
        await update_project(context, "demo", custom_fields={})

    assert len(recorder.calls) == 1


# --- the whole path: tool -> client -> HTTP ---------------------------------------------------------

_SCHEMA = {
    "customField1": {"name": "Effort", "type": "String", "writable": True, "location": "customField1"},
    "customField10": {
        "name": "Owner",
        "type": "User",
        "writable": True,
        "location": "_links",
        "_links": {"allowedValues": {"href": "/api/v3/principals?filters=%5B%5D"}},
    },
    "customField11": {
        "name": "Release",
        "type": "[]Version",
        "writable": True,
        "location": "_links",
        "_embedded": {
            "allowedValues": [
                {"name": "Secret", "_links": {"self": {"href": "/api/v3/versions/7"}}},
                {"name": "Own", "_links": {"self": {"href": "/api/v3/versions/8"}}},
            ]
        },
    },
}


def _project(name: str = "Demo") -> dict:
    return {
        "id": 6,
        "_type": "Project",
        "name": name,
        "identifier": "demo",
        "active": True,
        "customField1": "old",
        "_links": {
            "self": {"href": "/api/v3/projects/6"},
            "customField11": [{"href": "/api/v3/versions/8", "title": "Own"}],
        },
    }


class _Instance:
    def __init__(self) -> None:
        self.bodies: list[tuple[str, str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.bodies.append((request.method, path, body))
        if path == "/api/v3/principals":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {"elements": [{"name": "Jane Doe", "_links": {"self": {"href": "/api/v3/users/5"}}}]},
                },
                request=request,
            )
        if path.endswith("/form") and request.method == "POST":
            return httpx.Response(
                200,
                json={"_embedded": {"schema": _SCHEMA, "payload": body, "validationErrors": {}}},
                request=request,
            )
        if path in {"/api/v3/projects/6", "/api/v3/projects/demo"} and request.method == "GET":
            return httpx.Response(200, json=_project(), request=request)
        if path == "/api/v3/projects/6" and request.method == "PATCH":
            return httpx.Response(200, json=_project("Renamed"), request=request)
        if path == "/api/v3/projects" and request.method == "GET":
            return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_project()]}}, request=request)
        if path.startswith("/api/v3/versions/"):
            return httpx.Response(
                200,
                json={"id": int(path.rsplit("/", 1)[1]), "_links": {"definingProject": {"href": "/api/v3/projects/6"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _client(instance: _Instance, **overrides) -> OpenProjectClient:
    settings = dataclasses.replace(make_settings(), enable_project_write=True, **overrides)
    return OpenProjectClient(settings, transport=httpx.MockTransport(instance.handler))


@pytest.mark.asyncio
async def test_update_project_writes_a_user_by_name_and_clears_a_version_list_end_to_end() -> None:
    instance = _Instance()
    client = _client(instance)

    result = await update_project(
        FakeContext(client),
        "demo",
        custom_fields={"owner": "Jane Doe", "Release": None, "Effort": None},
        confirm=True,
    )

    patch = next(body for method, path, body in instance.bodies if method == "PATCH")
    assert patch == {
        "customField1": None,
        "_links": {"customField10": {"href": "/api/v3/users/5"}, "customField11": []},
    }
    assert result.state == "confirmed"
    assert result.result is not None and result.result.custom_fields == {
        "customField1": "<user-content>old</user-content>",
        "customField11": ["Own"],
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_get_project_and_list_projects_show_the_attributes_end_to_end() -> None:
    instance = _Instance()
    client = _client(instance)

    detail = await get_project(FakeContext(client), "demo")
    listed = await list_projects(FakeContext(client))

    expected = {"customField1": "<user-content>old</user-content>", "customField11": ["Own"]}
    assert detail.custom_fields == expected
    assert listed.results[0].custom_fields == expected
    await client.aclose()


@pytest.mark.asyncio
async def test_create_project_preview_resolves_by_name_without_writing() -> None:
    instance = _Instance()
    client = _client(instance)

    result = await create_project(
        FakeContext(client), name="Demo", identifier="demo", custom_fields={"Release": ["Own"]}, confirm=False
    )

    assert result.state == "preview"
    assert not any(method == "POST" and path == "/api/v3/projects" for method, path, _ in instance.bodies)
    form = [body for method, path, body in instance.bodies if path == "/api/v3/projects/form"][-1]
    assert form["_links"] == {"customField11": [{"href": "/api/v3/versions/8"}]}
    await client.aclose()
