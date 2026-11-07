"""`custom_fields` written into a form payload: key and value resolution, clearing, hide and scope rules."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.scoped_reference import ScopedReference
from openproject_ce_mcp.app.resource_href import ResourceLinks
from openproject_ce_mcp.app.services._custom_field_writes import (
    apply_custom_fields,
    ensure_custom_fields_input_writable,
)

LINKS = ResourceLinks("https://op.example.com")
SECRET_VERSION = ScopedReference("version", 7)


async def _all_visible(references):
    return dict.fromkeys(references, True)


async def _only_visible(references):
    return {reference: reference != SECRET_VERSION for reference in references}


def _option(option_id: int, name: str, kind: str = "versions") -> dict[str, Any]:
    return {"name": name, "_links": {"self": {"href": f"/api/v3/{kind}/{option_id}"}}}


def _versions_field(*, multi: bool = False) -> dict[str, Any]:
    return {
        "name": "Target",
        "type": "[]Version" if multi else "Version",
        "location": "_links",
        "_embedded": {"allowedValues": [_option(7, "Secret release"), _option(8, "Own release")]},
    }


def _plain_field(name: str = "Effort") -> dict[str, Any]:
    return {"name": name, "type": "String", "location": "customField"}


async def _apply(schema: dict[str, Any], custom_fields: dict[str, Any], *, settings=None, check=_all_visible):
    payload: dict[str, Any] = {}
    links: dict[str, Any] = {}
    await apply_custom_fields(
        payload,
        links,
        schema,
        custom_fields,
        subject="project",
        settings=settings or make_settings(),
        resource_links=LINKS,
        check=check,
    )
    return payload, links


@pytest.mark.asyncio
@pytest.mark.parametrize("hidden_name", ["Secret release", "Invented release"])
async def test_a_version_outside_the_read_scope_can_be_neither_set_nor_probed_for(hidden_name: str) -> None:
    restricted = dataclasses.replace(make_settings(), read_projects=("demo",), write_projects=("demo",))
    schema = {"customField3": _versions_field()}

    with pytest.raises(InvalidInputError, match=f"'{hidden_name}' is not allowed"):
        await _apply(schema, {"Target": hidden_name}, settings=restricted, check=_only_visible)

    _, links = await _apply(schema, {"Target": "Own release"}, settings=restricted, check=_only_visible)
    assert links == {"customField3": {"href": "/api/v3/versions/8"}}


@pytest.mark.asyncio
async def test_a_plain_value_goes_to_the_top_level_and_a_link_value_to_the_links() -> None:
    schema = {"customField1": _plain_field(), "customField3": _versions_field()}

    payload, links = await _apply(schema, {"effort": "3", "customField3": 8})

    assert payload == {"customField1": "3"}
    assert links == {"customField3": {"href": "/api/v3/versions/8"}}


@pytest.mark.asyncio
async def test_a_long_text_field_is_written_as_raw_text_and_cleared_with_null() -> None:
    schema = {"customField4": {"name": "Notes", "type": "Formattable", "location": "customField4"}}

    written, _ = await _apply(schema, {"customField4": "Some **markdown**"})
    cleared, _ = await _apply(schema, {"customField4": None})

    assert written == {"customField4": {"raw": "Some **markdown**"}}
    assert cleared == {"customField4": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [7, 2.5, True, ["a"], {"raw": "x"}])
async def test_a_long_text_field_refuses_a_value_that_openproject_would_drop_or_fail_on(value: Any) -> None:
    schema = {"customField4": {"name": "Notes", "type": "Formattable", "location": "customField4"}}

    with pytest.raises(InvalidInputError, match="customField4' is long text"):
        await _apply(schema, {"customField4": value})


@pytest.mark.asyncio
async def test_a_multi_value_link_field_takes_a_list_even_for_one_value() -> None:
    schema = {"customField3": _versions_field(multi=True)}

    _, one = await _apply(schema, {"Target": "Own release"})
    _, two = await _apply(schema, {"Target": [7, 8]})

    assert one == {"customField3": [{"href": "/api/v3/versions/8"}]}
    assert two == {"customField3": [{"href": "/api/v3/versions/7"}, {"href": "/api/v3/versions/8"}]}


@pytest.mark.asyncio
async def test_a_single_value_link_field_refuses_several_values() -> None:
    with pytest.raises(InvalidInputError, match="takes a single value"):
        await _apply({"customField3": _versions_field()}, {"Target": [7, 8]})


@pytest.mark.asyncio
async def test_clearing_follows_the_location_and_the_arity_of_the_field() -> None:
    schema = {
        "customField1": _plain_field(),
        "customField3": _versions_field(),
        "customField4": {**_versions_field(multi=True), "name": "Many"},
    }

    payload, links = await _apply(schema, {"effort": None, "Target": None, "Many": None})

    assert payload == {"customField1": None}
    assert links == {"customField3": {"href": None}, "customField4": []}


@pytest.mark.asyncio
async def test_an_empty_list_clears_a_multi_value_field_and_is_refused_on_a_single_value_field() -> None:
    _, links = await _apply({"customField4": _versions_field(multi=True)}, {"customField4": []})
    assert links == {"customField4": []}

    with pytest.raises(InvalidInputError, match="at least one value"):
        await _apply({"customField3": _versions_field()}, {"customField3": []})


@pytest.mark.asyncio
async def test_null_inside_a_list_is_refused_instead_of_becoming_the_text_none() -> None:
    with pytest.raises(InvalidInputError, match="null inside a list"):
        await _apply({"customField4": _versions_field(multi=True)}, {"customField4": [8, None]})


@pytest.mark.asyncio
async def test_a_field_hidden_by_name_or_key_is_refused_after_resolution() -> None:
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField1",))
    schema = {"customField1": _plain_field()}

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS"):
        await _apply(schema, {"Effort": "3"}, settings=settings)


def test_the_hidden_custom_fields_input_is_refused_before_a_schema_is_fetched() -> None:
    by_key = dataclasses.replace(make_settings(), hide_custom_fields=("customField1",))
    by_entity = dataclasses.replace(make_settings(), hidden_fields={"project": ("custom_fields",)})

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_CUSTOM_FIELDS"):
        ensure_custom_fields_input_writable("project", {"customField1": "x"}, settings=by_key)
    with pytest.raises(InvalidInputError, match="'custom_fields' is hidden"):
        ensure_custom_fields_input_writable("project", {"customField1": "x"}, settings=by_entity)
    ensure_custom_fields_input_writable("work_package", {"customField1": "x"}, settings=by_entity)


@pytest.mark.asyncio
async def test_the_messages_name_the_entity_that_was_written() -> None:
    with pytest.raises(InvalidInputError, match="not available for this project"):
        await _apply({"customField1": _plain_field()}, {"Missing": "x"})
