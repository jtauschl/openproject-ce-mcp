"""OPM-209 (Phase D): registry-driven behavioral contracts for every registered
write/delete MCP tool.

Properties proven here, generically across all 55 tools in `WRITE_TOOL_CASES`
(see `_write_contract_cases.py`):

(a) every write/delete tool returns a preview (requires_confirmation=True,
    confirmed=False) without confirm=true;
(b) no mutating HTTP call happens while confirm=false;
(c) authorization runs strictly before the mutating call, including for tools
    whose outer API contract absorbs the resulting error instead of
    propagating it (the two bulk work-package tools).

What this file does NOT prove: that authorization precedes *every* follow-up
request (several preview/form-based write paths deliberately issue their own
GET/POST-form requests before the write-scope gate is ever reached, and those
are expected, not violations). The stronger "zero follow-up requests at all
before the check trips" guarantee, for a representative handful of domains, is
`tests/unit/test_project_resolution.py`'s OPM-117 matrix -- see its module
docstring/comments for how the two complement each other.

Payload preview/confirm semantic equivalence (property c in OPM-209's ticket
text, a different "c" from the property list above) is proven separately in
`tests/unit/test_write_payload_equivalence.py`.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable

import httpx
import pytest
from _tools_test_helpers import FakeContext
from _write_contract_cases import WRITE_TOOL_CASES
from _write_contract_cases_types import WriteToolCase, materialize_case

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.tools import (
    _TOOL_FUNCTIONS,
    ADMIN_WRITE_TOOLS,
    ATTACHMENT_UPLOAD_TOOLS,
    PERSONAL_MUTATION_TOOLS,
    WRITE_TOOLS_BY_SCOPE,
)


def test_every_registered_write_tool_has_a_contract_case() -> None:
    all_write_tools: set[str] = set(ADMIN_WRITE_TOOLS) | set(PERSONAL_MUTATION_TOOLS) | set(ATTACHMENT_UPLOAD_TOOLS)
    for names in WRITE_TOOLS_BY_SCOPE.values():
        all_write_tools |= set(names)

    covered = set(WRITE_TOOL_CASES)
    missing = all_write_tools - covered
    stale = covered - all_write_tools
    assert not missing, f"registered write tools with no WriteToolCase: {sorted(missing)}"
    assert not stale, f"WRITE_TOOL_CASES entries for unregistered/removed tools: {sorted(stale)}"


def _handler_rejecting_the_write_request(case: WriteToolCase) -> Callable[[httpx.Request], httpx.Response]:
    """Wrap `case.handler` so the parametrized preview test fails loudly if the
    mutating call is ever issued, without requiring every case's own handler to
    police this itself -- the case only needs to know how to *answer* its
    write_request when asked, not whether it *should* be asked this time.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if (request.method, request.url.path) == case.write_request:
            raise AssertionError(f"Unexpected mutating request while confirm=False: {request.method} {request.url}")
        result = case.handler(request)
        if inspect.isawaitable(result):
            return await result
        return result

    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize("case", WRITE_TOOL_CASES.values(), ids=list(WRITE_TOOL_CASES.keys()))
async def test_write_tool_returns_preview_and_issues_no_mutating_call_when_unconfirmed(
    case: WriteToolCase, tmp_path
) -> None:
    materialized = materialize_case(case, tmp_path)
    fn = _TOOL_FUNCTIONS[case.tool]
    client = OpenProjectClient(
        materialized.settings, transport=httpx.MockTransport(_handler_rejecting_the_write_request(case))
    )
    try:
        result = await fn(FakeContext(client), **materialized.kwargs, confirm=False)
        assert result.requires_confirmation is True, case.tool
        assert result.confirmed is False, case.tool
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", WRITE_TOOL_CASES.values(), ids=list(WRITE_TOOL_CASES.keys()))
async def test_write_tool_commits_when_confirmed(case: WriteToolCase, tmp_path) -> None:
    materialized = materialize_case(case, tmp_path)
    fn = _TOOL_FUNCTIONS[case.tool]
    client = OpenProjectClient(materialized.settings, transport=httpx.MockTransport(case.handler))
    try:
        result = await fn(FakeContext(client), **materialized.kwargs, confirm=True)
        assert result.confirmed is True, case.tool
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", WRITE_TOOL_CASES.values(), ids=list(WRITE_TOOL_CASES.keys()))
async def test_write_tool_denies_when_its_write_scope_is_disabled(case: WriteToolCase, tmp_path) -> None:
    """The third authorization state, not covered by the two tests above.

    Critical ordering: materialize() runs *first*, so the attachment case's
    disabled Settings still carries an attachment_root pointed at this test's
    actual tmp_path -- deriving the disabled variant from the case's static
    settings instead would leave a stale/empty attachment_root, and the call
    could fail on the file-path/root check before ever reaching the
    write-scope gate, proving nothing about authorization ordering.
    """
    materialized = materialize_case(case, tmp_path)
    disabled_settings = dataclasses.replace(materialized.settings, **{f"enable_{case.write_scope}_write": False})
    fn = _TOOL_FUNCTIONS[case.tool]
    client = OpenProjectClient(
        disabled_settings, transport=httpx.MockTransport(_handler_rejecting_the_write_request(case))
    )
    try:
        if case.denial_mode == "raises":
            with pytest.raises(RuntimeError, match=r"\[permission_denied\]"):
                await fn(FakeContext(client), **materialized.kwargs, confirm=True)
        else:
            result = await fn(FakeContext(client), **materialized.kwargs, confirm=True)
            assert result.items, case.tool
            assert all(not item.success for item in result.items), case.tool
            assert result.succeeded == 0, case.tool
    finally:
        await client.aclose()
