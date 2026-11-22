from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import httpx
import pytest

from openproject_ce_mcp.app.adapters._text import normalize_form_validation_errors
from openproject_ce_mcp.app.adapters.httpx_board_api import HttpxBoardApi, _normalize_board_filter
from openproject_ce_mcp.app.adapters.httpx_meeting_api import HttpxMeetingApi
from openproject_ce_mcp.app.adapters.httpx_membership_api import HttpxMembershipApi
from openproject_ce_mcp.app.adapters.httpx_user_api import HttpxUserApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"
ADAPTERS = Path(__file__).resolve().parents[2] / "src" / "openproject_ce_mcp" / "app" / "adapters"

# What OpenProject renders for a field with two violated constraints (form.rb, create_if_many):
# one MultipleErrors entry whose own message only says so.
MULTIPLE_ERRORS: dict[str, Any] = {
    "_type": "Error",
    "errorIdentifier": "urn:openproject-org:api:v3:errors:MultipleErrors",
    "message": "Multiple field constraints have been violated.",
    "_embedded": {
        "errors": [
            {"_type": "Error", "message": "Name can't be blank."},
            {"_type": "Error", "message": "Name is too short (minimum is 3 characters)."},
        ]
    },
}
SINGLE_ERROR: dict[str, Any] = {
    "_type": "Error",
    "errorIdentifier": "urn:openproject-org:api:v3:errors:PropertyConstraintViolation",
    "message": "Title can't be blank.",
}
EXPECTED = {
    "multiple": "Name can't be blank.; Name is too short (minimum is 3 characters).",
    "single": "Title can't be blank.",
}


@pytest.mark.parametrize(
    ("errors", "expected"),
    [
        ({"name": MULTIPLE_ERRORS, "title": SINGLE_ERROR}, {"name": EXPECTED["multiple"], "title": EXPECTED["single"]}),
        ({"hours": {"raw": "must be positive"}}, {"hours": "must be positive"}),
        ({"name": {**MULTIPLE_ERRORS, "_embedded": {"errors": []}}}, {"name": MULTIPLE_ERRORS["message"]}),
        (
            {"name": {**MULTIPLE_ERRORS, "_embedded": {"errors": [{"message": ""}, "text", {"message": "x"}]}}},
            {"name": "x"},
        ),
        ({"name": {"message": "is invalid", "_embedded": {}}}, {"name": "is invalid"}),
        (None, {}),
        ([1, 2], {}),
    ],
)
def test_the_shared_normalizer_reads_every_real_error_shape(errors: Any, expected: dict[str, str]) -> None:
    assert normalize_form_validation_errors(errors) == expected


def test_every_nested_message_is_cut_to_the_limit() -> None:
    long_error = {**MULTIPLE_ERRORS, "_embedded": {"errors": [{"message": "a" * 500}, {"message": "b"}]}}

    message = normalize_form_validation_errors({"name": long_error}, limit=20)["name"]

    assert message == "a" * 19 + "…" + "; b"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


async def _form_errors(api_factory, call) -> dict[str, str]:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"payload": {}, "validationErrors": {"name": MULTIPLE_ERRORS, "title": SINGLE_ERROR}}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = api_factory(HttpxTransport(http_client, redact_server_text=False))
        return (await call(api)).validation_errors


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_factory", "call"),
    [
        pytest.param(HttpxBoardApi, lambda api: api.create_form({"name": "b"}), id="board"),
        pytest.param(
            lambda transport: HttpxUserApi(transport, base_url=BASE_URL),
            lambda api: api.create_form({"login": "ada"}),
            id="user",
        ),
        pytest.param(
            lambda transport: HttpxMembershipApi(transport, base_url=BASE_URL),
            lambda api: api.create_form({"_links": {}}),
            id="membership",
        ),
        pytest.param(HttpxMeetingApi, lambda api: api.create_form({}), id="meeting"),
    ],
)
async def test_an_adapter_reports_the_same_validation_errors_as_the_shared_normalizer(api_factory, call) -> None:
    errors = await _form_errors(api_factory, call)

    assert errors == normalize_form_validation_errors({"name": MULTIPLE_ERRORS, "title": SINGLE_ERROR})
    assert errors == {"name": EXPECTED["multiple"], "title": EXPECTED["single"]}


def test_no_adapter_keeps_its_own_validation_error_or_slug_helper() -> None:
    """A second copy is how the nested `MultipleErrors` messages and the percent-encoded operator
    names were lost in some adapters and not in others."""
    offenders = []
    for path in sorted(ADAPTERS.glob("*.py")):
        if path.name == "_text.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
                "validation_errors" in node.name or "slug_from_href" in node.name
            ):
                offenders.append(f"{path.name}:{node.name}")
    assert offenders == []


def test_a_board_operator_without_a_title_is_named_by_its_decoded_href() -> None:
    normalized = _normalize_board_filter(
        {
            "_links": {
                "filter": {"href": "/api/v3/queries/filters/status"},
                "operator": {"href": "/api/v3/queries/operators/%3D"},
            }
        }
    )

    assert normalized.operator == "="
