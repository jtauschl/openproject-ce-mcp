"""Every long-form text a read tool returns is wrapped in the `<user-content>` delimiter.

OpenProject stores user-authored text verbatim, so the server instructions promise that long-form text comes back
between `<user-content>` tags and that stored text cannot close them (`test_user_content.py`). This matrix runs every read
tool against a server whose every item carries each Formattable property of the upstream representers (the
`formattable_property` list of OpenProject 17.9: work package, project, version, news, document, attachment, activity,
time entry, meeting agenda item and outcome, help text, GitHub and GitLab bodies, long text custom fields) with its own
marker, and reads the result through the serializer a caller sees. A marker that reaches a result outside the delimiter
fails the tool. A new read tool joins the matrix without an entry.

Limits, stated on purpose: one generic call per tool and the keys listed in `FORMATTABLE`; short strings (names,
subjects, titles) are not covered, which is an open owner decision; the JSON of one fake server shows that a
property is wrapped where the adapter reads it, not that an adapter reads every property of its representer.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _read_tool_harness import FOREIGN, OVERRIDES, READABLE, arguments, serve
from _tools_test_helpers import FakeContext

from openproject_ce_mcp import tools, tools_runtime
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import TOOL_GROUPS
from openproject_ce_mcp.presentation import ContentBundle, _to_payload

OPEN, CLOSE = "<user-content>", "</user-content>"
PREFIX = "LONGFORM-"

# JSON keys (after the representer's `as:`: the time entry's `comments` is `comment`, an activity's `notes` too) of
# the Formattable properties that a read tool can return (upstream representers, 17.9). `details` is a list of them.
# `message` of a revision and `notificationMessage` of a membership are left out: no read tool of both lines returns
# them. The `message` of a job status is a plain string upstream, so the fake sets it as one, not as a Formattable.
FORMATTABLE = (
    "description",
    "statusExplanation",
    "comment",
    "notes",
    "helpText",
    "body",
    "customField1",
)
# Keys that must surface in at least one read tool on every line, so the matrix cannot pass by seeing nothing.
MUST_SURFACE = {*FORMATTABLE, "details", "message"}

# A generic call that is refused before any text is built, with the reason; each entry is a gap of this matrix.
UNEXERCISED: dict[str, tuple[str, str]] = {
    "get_grid": ("the fake grid names no project scope, so the read is refused first", "grid has a scope"),
}


def _decorate(node: Any) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("_type"), str) and node["_type"] != "Collection":
            for key in FORMATTABLE:
                node[key] = {"format": "markdown", "raw": f"{PREFIX}{key}", "html": f"<p>{PREFIX}{key}</p>"}
            node["details"] = [{"format": "markdown", "raw": f"{PREFIX}details", "html": f"<p>{PREFIX}details</p>"}]
        for value in node.values():
            _decorate(value)
    elif isinstance(node, list):
        for value in node:
            _decorate(value)


def _server(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith(("/render/markdown", "/render/plain")):
        # The endpoint renders the caller's own text; a live check against OpenProject 17.9 showed that its work package
        # macros and mentions emit ids and attributes for the browser to fill in, never a stored text.
        return httpx.Response(200, text="<p>rendered</p>", request=request)
    body = json.loads(serve(request).content)
    _decorate(body)
    if request.url.path.rsplit("/", 2)[-2] == "job_statuses":
        body["message"] = f"{PREFIX}message"
    return httpx.Response(200, json=body, request=request)


def _leaves(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [leaf for key, item in value.items() for leaf in _leaves(item, f"{path}.{key}" if path else key)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item, f"{path}[]")]
    return [(path, value)] if isinstance(value, str) and PREFIX in value else []


async def _long_form_texts(name: str) -> list[tuple[str, str]]:
    function = tools_runtime._TOOL_FUNCTIONS[name]
    enabled = {group.read_attr: True for group in TOOL_GROUPS}
    client = OpenProjectClient(
        _base_settings(read_projects=("*",), write_projects=(), **enabled),
        transport=httpx.MockTransport(
            serving_projects(_server, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    await client.initialize()
    try:
        result = await function(FakeContext(client), **{**arguments(function), **OVERRIDES.get(name, {})})
    finally:
        await client.aclose()
    body = result.body if isinstance(result, ContentBundle) else result
    elide_none = "select" in inspect.signature(function).parameters
    return _leaves(json.loads(json.dumps(_to_payload(body, select=None, elide_none=elide_none), default=str)))


def _is_wrapped(text: str) -> bool:
    return text.startswith(OPEN) and text.endswith(CLOSE) and text.count(OPEN) == 1 and text.count(CLOSE) == 1


_READ_TOOLS = sorted({name for names in tools.READ_TOOLS_BY_SCOPE.values() for name in names})


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _READ_TOOLS)
async def test_a_read_tool_returns_long_form_text_only_inside_the_delimiter(name: str) -> None:
    if name not in tools_runtime._TOOL_FUNCTIONS:
        pytest.skip("not registered")
    try:
        texts = await _long_form_texts(name)
    except Exception as error:  # noqa: BLE001
        if name not in UNEXERCISED:
            raise
        reason, expected_refusal = UNEXERCISED[name]
        assert expected_refusal in str(error), (name, str(error)[:300])
        pytest.skip(reason)

    unwrapped = [(path, text[:80]) for path, text in texts if not _is_wrapped(text)]
    assert unwrapped == [], (name, unwrapped[:5])


@pytest.mark.asyncio
async def test_every_formattable_key_of_the_catalog_surfaces_in_some_read_tool() -> None:
    seen: set[str] = set()
    for name in _READ_TOOLS:
        if name in tools_runtime._TOOL_FUNCTIONS and name not in UNEXERCISED:
            for _, text in await _long_form_texts(name):
                seen.add(text.removeprefix(OPEN).split(PREFIX, 1)[1].split("<", 1)[0])

    assert MUST_SURFACE <= seen, sorted(MUST_SURFACE - seen)


def test_the_delimiter_check_reads_the_whole_text() -> None:
    assert _is_wrapped(f"{OPEN}{PREFIX}x{CLOSE}")
    assert not _is_wrapped(f"{PREFIX}x")
    assert not _is_wrapped(f"{OPEN}{PREFIX}x")
    assert not _is_wrapped(f"{OPEN}a{CLOSE}{PREFIX}x")
    assert not _is_wrapped(f"{OPEN}{PREFIX}x{CLOSE}{OPEN}y{CLOSE}")
