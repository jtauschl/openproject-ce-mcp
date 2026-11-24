"""Every read tool that filters by a hidden field refuses before it sends a request.

For each (tool, parameter, field) of the filter table the field is hidden alone and the tool is called through the
tool function with the parameter set (and, where the tool has an optional `project`, once with and once without it).
The call must raise the exact refusal and the fake server must have seen no request at all. The same call without the
hide setting must complete and reach the server, so a tool that is refused for another reason (a read group that is
off, a validation error, a missing fake) cannot pass.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _read_tool_harness import FOREIGN, OVERRIDES, READABLE, arguments, item, sentinel_serve
from _tools_test_helpers import FakeContext
from test_filter_policy import ALSO, EXPECTED, VALUE

from openproject_ce_mcp import tools  # noqa: F401 -- importing the tools registers them in _TOOL_FUNCTIONS
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY, TOOL_GROUPS
from openproject_ce_mcp.tool_errors import ToolInputError
from openproject_ce_mcp.tools_runtime import _TOOL_FUNCTIONS

# Arguments a tool needs besides the required ones the harness fills in and the parameter under test.
EXTRA: dict[str, dict[str, Any]] = {
    "get_category": {"category_id": 5},
    "list_user_non_working_times": {"user_ref": "7"},
}
# The tools whose generic call the fake cannot serve, with the reason; the number is bounded.
CANNOT_CALL: dict[str, str] = {}


def _serve_in_the_readable_project(request: httpx.Request) -> httpx.Response:
    """The generic fake files a category under a project outside the read scope; the category of the project in
    the call has to sit in the project it is asked for, or the tool answers not found before it filters."""
    if request.url.path == "/api/v3/categories/5":
        return httpx.Response(200, json=item("Category", 5, READABLE, "readable"), request=request)
    return sentinel_serve(request)


MAX_CANNOT_CALL = 3


def _settings(hidden: dict[str, tuple[str, ...]] | None = None):
    enabled = {group.read_attr: True for group in TOOL_GROUPS}
    settings = _base_settings(read_projects=("*",), write_projects=(), **enabled)
    return dataclasses.replace(settings, hidden_fields=hidden or {})


async def _call(
    tool: str, parameter: str, hidden: dict[str, tuple[str, ...]] | None, *, with_project: bool, supply: bool = True
) -> tuple[Exception | None, int]:
    """The exception the call raised (or None) and the number of requests the server saw after start-up."""
    function = _TOOL_FUNCTIONS[tool]
    seen: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return _serve_in_the_readable_project(request)

    client = OpenProjectClient(
        _settings(hidden),
        transport=httpx.MockTransport(
            serving_projects(serve, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    await client.initialize()
    seen.clear()
    given = {**arguments(function), **OVERRIDES.get(tool, {}), **EXTRA.get(tool, {})}
    if supply:
        given[parameter] = VALUE[parameter]
    if with_project and "project" in inspect.signature(function).parameters:
        given["project"] = "demo"
    try:
        await function(FakeContext(client), **given)
    except Exception as error:  # noqa: BLE001 -- the refusal is what the test looks for
        return error, len(seen)
    finally:
        await client.aclose()
    return None, len(seen)


def _owners(tool: str, parameter: str) -> list[tuple[str, str]]:
    entity, fields, _ = EXPECTED[(tool, parameter)]
    return [(entity, field) for field in fields] + list(ALSO.get((tool, parameter), ()))


CASES = [
    (tool, parameter, entity, field, with_project)
    for (tool, parameter) in sorted(EXPECTED)
    for entity, field in _owners(tool, parameter)
    for with_project in (
        (False, True) if "project" in inspect.signature(_TOOL_FUNCTIONS[tool]).parameters else (False,)
    )
]


def _refusal_text(entity: str, field: str, parameter: str) -> str:
    return (
        f"[validation_error] OpenProject {entity.replace('_', ' ')} field '{field}' is hidden by "
        f"{HIDE_FIELD_ENV_BY_ENTITY[entity]} and cannot be used to filter ('{parameter}')."
    )


def test_every_table_row_is_a_registered_read_tool_with_that_parameter() -> None:
    for tool, parameter in EXPECTED:
        assert tool in _TOOL_FUNCTIONS, f"{tool} is not registered: a row of a tool that does not exist"
        assert parameter in inspect.signature(_TOOL_FUNCTIONS[tool]).parameters, (tool, parameter)
    assert len(CANNOT_CALL) <= MAX_CANNOT_CALL


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "parameter", "entity", "field", "with_project"), CASES)
async def test_a_hidden_field_refuses_the_filter_before_any_request(
    tool: str, parameter: str, entity: str, field: str, with_project: bool
) -> None:
    baseline_error, baseline_requests = await _call(tool, parameter, None, with_project=with_project)
    refusal, requests = await _call(tool, parameter, {entity: (field,)}, with_project=with_project)

    assert baseline_error is None, f"the visible baseline did not complete: {baseline_error!r}"
    assert baseline_requests >= 1, "the visible baseline reached no server: the scan would pass without a request"
    assert isinstance(refusal, ToolInputError), repr(refusal)
    assert str(refusal) == _refusal_text(entity, field, parameter)
    assert requests == 0, f"{requests} request(s) went out before the refusal"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "parameter"), sorted((tool, parameter) for (tool, parameter), (_, _, always) in EXPECTED.items() if always)
)
async def test_a_parameter_whose_default_selects_is_refused_without_the_parameter(tool: str, parameter: str) -> None:
    for entity, field in _owners(tool, parameter):
        baseline_error, baseline_requests = await _call(tool, parameter, None, with_project=False, supply=False)
        refusal, requests = await _call(tool, parameter, {entity: (field,)}, with_project=False, supply=False)

        assert baseline_error is None, repr(baseline_error)
        assert baseline_requests >= 1
        assert isinstance(refusal, ToolInputError), repr(refusal)
        assert str(refusal) == _refusal_text(entity, field, parameter)
        assert requests == 0
