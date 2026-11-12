"""A hide setting reaches every read tool: with every entity hidden, no text of a result survives.

Every read tool runs against a server whose every text carries a canary. All masking entities are set to `*`, and
the result is read through the serializer a caller sees (`_to_payload`, the serializer of the tool wrapper), because the masked keys are
dropped there and not on the result object. A tool whose result model is never passed through masking returns the
canary and fails. A tool whose generic call is refused for another reason (a hidden field it filters by) or needs
other arguments sits in `UNEXERCISED` with the reason, so the gap is listed.

Limits: one generic call per tool; the matrix proves that masking is applied at all, not that each field of each model
is covered (the per-entity tests and the config-map structural test do that).
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _read_tool_harness import CANARY, FOREIGN, OVERRIDES, READABLE, arguments, serve
from _tools_test_helpers import FakeContext

from openproject_ce_mcp import tools, tools_runtime
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY, TOOL_GROUPS
from openproject_ce_mcp.presentation import ContentBundle, _to_payload

# A generic call that does not reach masking, with the reason; each entry is a gap of this matrix, not a pass.
UNEXERCISED: dict[str, tuple[str, str]] = {
    "get_grid": (
        "the fake grid names no project scope, so the read is refused before any text is built",
        "grid has a scope",
    ),
    "list_my_open_work_packages": (
        "filters by the assignee field, which is hidden: refused before any read",
        "is hidden by",
    ),
    "search_work_packages": ("filters by the subject field, which is hidden: refused before any read", "is hidden by"),
    "render_text": (
        "is switched off while fields it would render are hidden, so nothing is rendered",
        "render_text is disabled",
    ),
}


def _server(request: httpx.Request) -> httpx.Response:
    response = serve(request)
    text = response.content.decode().replace('"readable"', f'"{CANARY}"').replace('"global"', f'"{CANARY}"')
    return httpx.Response(200, content=text, headers={"content-type": "application/json"}, request=request)


def _settings():
    enabled = {group.read_attr: True for group in TOOL_GROUPS}
    settings = _base_settings(read_projects=("*",), write_projects=(), **enabled)
    return dataclasses.replace(settings, hidden_fields=dict.fromkeys(HIDE_FIELD_ENV_BY_ENTITY, ("*",)))


async def _output(name: str) -> tuple[str, str]:
    function = tools_runtime._TOOL_FUNCTIONS[name]
    client = OpenProjectClient(
        _settings(),
        transport=httpx.MockTransport(
            serving_projects(_server, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    await client.initialize()
    try:
        result = await function(FakeContext(client), **{**arguments(function), **OVERRIDES.get(name, {})})
    except Exception as error:  # noqa: BLE001
        return ("canary" if CANARY in str(error) else "refused"), f"{type(error).__name__}: {error}"
    finally:
        await client.aclose()
    body = result.body if isinstance(result, ContentBundle) else result
    elide_none = "select" in inspect.signature(function).parameters
    text = json.dumps(_to_payload(body, select=None, elide_none=elide_none), default=str)
    return ("canary" if CANARY in text else "masked"), text


_READ_TOOLS = sorted({name for names in tools.READ_TOOLS_BY_SCOPE.values() for name in names})


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _READ_TOOLS)
async def test_a_read_tool_returns_no_text_when_every_entity_is_hidden(name: str) -> None:
    if name not in tools_runtime._TOOL_FUNCTIONS:
        pytest.skip("not registered")
    outcome, detail = await _output(name)

    assert outcome != "canary", (name, detail[:300])
    if name in UNEXERCISED:
        reason, expected_refusal = UNEXERCISED[name]
        assert outcome == "refused" and expected_refusal in detail, (name, detail[:300])
        pytest.skip(reason)
    assert outcome == "masked", (name, detail[:300])


def test_the_work_package_context_entity_is_read_from_its_environment_variable() -> None:
    from openproject_ce_mcp.config import Settings

    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token",
            "OPENPROJECT_HIDE_PROJECT_WORK_PACKAGE_CONTEXT_FIELDS": "project_name, available_types",
        }
    )

    assert settings.hidden_fields["project_work_package_context"] == ("project_name", "available_types")
