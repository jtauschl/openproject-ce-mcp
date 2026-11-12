"""No read tool hands back data that belongs to a project outside OPENPROJECT_READ_PROJECTS.

Every tool of `_PROJECT_SCOPED_READ_TOOLS` runs against a server whose every resource that is not under the
readable project belongs to a project outside the read scope and carries a canary string in each of its texts.
A tool passes when it refuses the read (a scope error), or answers without the canary. The arguments come from
the tool's own signature (an id of `5`, the readable project `demo`), so a new read tool joins the matrix without
an entry; a tool whose generic call fails for another reason sits in `UNEXERCISED` with the reason, so the gap is
listed and cannot grow unnoticed.

Limits, stated on purpose: one synthetic argument set per tool and a fake server that assigns ownership by URL
path. It proves the id, link and list paths of that call, not alternate ids, project or filter values, pagination,
optional flags or each endpoint's real response shape. It does not reach a gate that depends on a particular
parameter value, a filter parameter, or a foreign link inside an allowed resource; those have their own tests
(`test_app_policies_scope.py`, the domain service tests). The global lookups (`GLOBAL_LOOKUPS` in the harness) rest on a reading of
the OpenProject 17.9 representers: statuses, priorities, roles and types carry no project link; the others
(`custom_options`, `days`, `help_texts`, `configuration`, `time_entries/activities`, `users/me`) are instance-wide
by their endpoint and tool signature.
"""

from __future__ import annotations

import inspect

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _read_tool_harness import CANARY, FOREIGN, OVERRIDES, READABLE, arguments, serve
from _tools_test_helpers import FakeContext

from openproject_ce_mcp import tools, tools_runtime
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import TOOL_GROUPS
from openproject_ce_mcp.presentation import ContentBundle, _to_payload, dump_payload

# A generic call that does not reach a gate, with the reason; each entry is a gap of this matrix, not a pass.
UNEXERCISED: dict[str, str] = {}


def _settings():
    enabled = {group.read_attr: True for group in TOOL_GROUPS}
    return _base_settings(read_projects=("demo",), write_projects=(), **enabled)


async def _call(name: str) -> tuple[str, str]:
    function = tools_runtime._TOOL_FUNCTIONS[name]
    client = OpenProjectClient(
        _settings(),
        transport=httpx.MockTransport(
            serving_projects(serve, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    await client.initialize()
    try:
        result = await function(FakeContext(client), **{**arguments(function), **OVERRIDES.get(name, {})})
    except Exception as error:  # noqa: BLE001
        text = f"{type(error).__name__}: {error}"
        return (
            "canary" if CANARY in text else "refused" if "SCOPE_DENIED" in text or "PERMISSION" in text else "other"
        ), text
    finally:
        await client.aclose()
    body = result.body if isinstance(result, ContentBundle) else result
    elide_none = "select" in inspect.signature(function).parameters
    text = dump_payload(_to_payload(body, select=None, elide_none=elide_none))
    return ("canary" if CANARY in text else "answered"), text


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(tools._PROJECT_SCOPED_READ_TOOLS))
async def test_a_read_tool_never_returns_data_of_a_project_outside_the_read_scope(name: str) -> None:
    outcome, detail = await _call(name)

    assert outcome != "canary", (name, detail[:300])
    if name in UNEXERCISED:
        pytest.skip(UNEXERCISED[name])
    assert outcome in ("refused", "answered"), (name, detail[:300])


def test_the_matrix_covers_every_project_scoped_read_tool_that_is_registered() -> None:
    registered = set(tools_runtime._TOOL_FUNCTIONS)

    assert set(tools._PROJECT_SCOPED_READ_TOOLS) <= registered
    assert set(UNEXERCISED) <= set(tools._PROJECT_SCOPED_READ_TOOLS)
