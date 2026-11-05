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
from openproject_ce_mcp.app.form_result import ValidationFailure
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"
ADAPTERS = Path(__file__).resolve().parents[2] / "src" / "openproject_ce_mcp" / "app" / "adapters"

_CONSTRAINT = "urn:openproject-org:api:v3:errors:PropertyConstraintViolation"
_READ_ONLY = "urn:openproject-org:api:v3:errors:PropertyIsReadOnly"

# What OpenProject renders for a field with two violated constraints (form.rb, create_if_many):
# one MultipleErrors entry whose own message only says so.
MULTIPLE_ERRORS: dict[str, Any] = {
    "_type": "Error",
    "errorIdentifier": "urn:openproject-org:api:v3:errors:MultipleErrors",
    "message": "Multiple field constraints have been violated.",
    "_embedded": {
        "errors": [
            {"_type": "Error", "errorIdentifier": _CONSTRAINT, "message": "Name can't be blank."},
            {
                "_type": "Error",
                "errorIdentifier": _CONSTRAINT,
                "message": "Name is too short (minimum is 3 characters).",
            },
        ]
    },
}
SINGLE_ERROR: dict[str, Any] = {
    "_type": "Error",
    "errorIdentifier": _CONSTRAINT,
    "message": "Title can't be blank.",
}
EXPECTED = {
    "multiple": ValidationFailure(
        "Name can't be blank.; Name is too short (minimum is 3 characters).", ("PropertyConstraintViolation",)
    ),
    "single": ValidationFailure("Title can't be blank.", ("PropertyConstraintViolation",)),
}


def _nested(*errors: Any) -> dict[str, Any]:
    return {**MULTIPLE_ERRORS, "_embedded": {"errors": list(errors)}}


@pytest.mark.parametrize(
    ("errors", "expected"),
    [
        ({"name": MULTIPLE_ERRORS, "title": SINGLE_ERROR}, {"name": EXPECTED["multiple"], "title": EXPECTED["single"]}),
        ({"hours": {"raw": "must be positive"}}, {"hours": ValidationFailure("must be positive")}),
        ({"name": _nested()}, {"name": ValidationFailure(MULTIPLE_ERRORS["message"])}),
        ({"name": _nested({"message": ""}, "text", {"message": "x"})}, {"name": ValidationFailure("x")}),
        ({"name": {"message": "is invalid", "_embedded": {}}}, {"name": ValidationFailure("is invalid")}),
        ({"name": "just text"}, {"name": ValidationFailure("just text")}),
        (
            {"id": {"errorIdentifier": _READ_ONLY, "message": "id is read-only."}},
            {"id": ValidationFailure("id is read-only.", ("PropertyIsReadOnly",))},
        ),
        (
            {
                "name": _nested(
                    {"errorIdentifier": _READ_ONLY, "message": "a"},
                    {"errorIdentifier": _CONSTRAINT, "message": "b"},
                    {"errorIdentifier": _READ_ONLY, "message": "c"},
                )
            },
            {"name": ValidationFailure("a; b; c", ("PropertyIsReadOnly", "PropertyConstraintViolation"))},
        ),
        (
            {"name": _nested({"errorIdentifier": _CONSTRAINT, "message": "a"}, {"message": "b"})},
            {"name": ValidationFailure("a; b", ("PropertyConstraintViolation",))},
        ),
        (
            {"name": {"errorIdentifier": "urn:openproject-org:api:v3:errors:MultipleErrors", "message": "only"}},
            {"name": ValidationFailure("only")},
        ),
        (
            {
                "name": _nested(
                    {"errorIdentifier": "urn:openproject-org:api:v3:errors:MultipleErrors", "message": "a"},
                    {"errorIdentifier": _CONSTRAINT, "message": "b"},
                )
            },
            {"name": ValidationFailure("a; b", ("PropertyConstraintViolation",))},
        ),
        (None, {}),
        ([1, 2], {}),
    ],
)
def test_the_shared_normalizer_reads_every_real_error_shape(
    errors: Any, expected: dict[str, ValidationFailure]
) -> None:
    assert normalize_form_validation_errors(errors) == expected


@pytest.mark.parametrize(
    "identifier",
    [
        "PropertyConstraintViolation",
        "urn:openproject-org:api:v3:errors:Foo bar",
        "urn:openproject-org:api:v3:errors:Foo\nbar",
        "urn:openproject-org:api:v3:errors:Foo; PropertyIsReadOnly (x)",
        "urn:openproject-org:api:v3:errors:OutboundRequest:NotFound",
        "urn:openproject-org:api:v3:errors:" + "A" * 65,
        "urn:openproject-org:api:v3:errors:",
        "xurn:openproject-org:api:v3:errors:Foo",
        42,
        None,
    ],
)
def test_an_identifier_that_is_not_the_documented_shape_yields_no_code(identifier: Any) -> None:
    entry = {"errorIdentifier": identifier, "message": "m"}

    assert normalize_form_validation_errors({"name": entry}) == {"name": ValidationFailure("m")}
    assert normalize_form_validation_errors({"name": _nested(entry)}) == {"name": ValidationFailure("m")}


def test_the_german_and_the_english_response_give_the_same_codes() -> None:
    german = {"subject": {**SINGLE_ERROR, "message": "Thema muss ausgefüllt werden."}}
    english = {"subject": {**SINGLE_ERROR, "message": "Subject can't be blank."}}

    codes = [normalize_form_validation_errors(errors)["subject"].error_codes for errors in (german, english)]

    assert codes == [("PropertyConstraintViolation",)] * 2


def test_every_nested_message_is_cut_to_the_limit() -> None:
    long_error = {**MULTIPLE_ERRORS, "_embedded": {"errors": [{"message": "a" * 500}, {"message": "b"}]}}

    failure = normalize_form_validation_errors({"name": long_error}, limit=20)["name"]

    assert failure == ValidationFailure("a" * 19 + "…" + "; b")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


async def _form_errors(api_factory, call) -> dict[str, ValidationFailure]:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"payload": {}, "validationErrors": {"name": MULTIPLE_ERRORS, "title": SINGLE_ERROR}}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = api_factory(HttpxTransport(http_client))
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


def test_every_validation_errors_field_has_the_one_type() -> None:
    """Scans every file, not only `models.py`: a field annotated as a bare `dict` would otherwise pass unnoticed."""
    src = Path(__file__).resolve().parents[2] / "src" / "openproject_ce_mcp"
    wrong = []
    seen = 0
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id.endswith("validation_errors")
            ):
                seen += 1
                if ast.unparse(node.annotation).replace(" ", "") != "dict[str,ValidationFailure]":
                    wrong.append(f"{path.relative_to(src)}:{node.lineno}")
    assert wrong == []
    assert seen >= 30
