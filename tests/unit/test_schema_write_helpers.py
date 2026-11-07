"""A title that several allowed values share is ambiguous, not resolved to the first of them."""

from __future__ import annotations

from typing import Any

import pytest

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.services._schema_write_helpers import (
    resolve_custom_field_key,
    resolve_custom_field_links,
    resolve_schema_option_href,
)


def _option(option_id: int, name: str) -> dict[str, Any]:
    return {"name": name, "_links": {"self": {"href": f"/api/v3/things/{option_id}", "title": name}}}


def _field(*options: dict[str, Any]) -> dict[str, Any]:
    return {"_embedded": {"allowedValues": list(options)}}


def test_a_title_shared_by_two_allowed_values_is_ambiguous_and_names_both() -> None:
    schema = {"responsible": _field(_option(3, "Jane Doe"), _option(7, "Jane Doe"), _option(9, "John"))}

    with pytest.raises(InvalidInputError, match=r"ambiguous.*3, 7.*numeric id"):
        resolve_schema_option_href(schema, "responsible", "jane doe")


def test_a_unique_title_still_resolves_and_the_id_still_picks_one_of_two_equal_titles() -> None:
    schema = {"responsible": _field(_option(3, "Jane Doe"), _option(7, "Jane Doe"), _option(9, "John"))}

    assert resolve_schema_option_href(schema, "responsible", "john") == "/api/v3/things/9"
    assert resolve_schema_option_href(schema, "responsible", "7") == "/api/v3/things/7"


def test_the_same_allowed_value_listed_twice_is_not_ambiguous() -> None:
    schema = {"priority": _field(_option(3, "High"), _option(3, "High"))}

    assert resolve_schema_option_href(schema, "priority", "High") == "/api/v3/things/3"


def test_a_custom_field_title_shared_by_two_options_is_ambiguous() -> None:
    field = _field(_option(11, "Blue"), _option(12, "Blue"))

    with pytest.raises(InvalidInputError, match=r"ambiguous.*11, 12"):
        resolve_custom_field_links(field, "blue", "customField4", subject="work package")


def test_a_custom_field_option_list_with_digit_titles_still_resolves_in_option_order() -> None:
    field = _field(_option(1, "3"), _option(2, "5"), _option(3, "8"))

    assert resolve_custom_field_links(field, 5, "customField4", subject="work package") == ["/api/v3/things/2"]


def test_an_id_settles_a_clash_between_digit_titles() -> None:
    field = _field(_option(5, "8"), _option(6, "8"), _option(8, "13"))

    assert resolve_custom_field_links(field, 8, "customField4", subject="work package") == ["/api/v3/things/8"]


def test_digit_titles_that_clash_without_an_id_to_settle_them_are_ambiguous() -> None:
    field = _field(_option(5, "9"), _option(6, "9"))

    with pytest.raises(InvalidInputError, match="ambiguous"):
        resolve_custom_field_links(field, "9", "customField4", subject="work package")


def test_each_value_of_a_multi_value_custom_field_is_checked() -> None:
    field = _field(_option(1, "A"), _option(2, "A"), _option(3, "B"))

    with pytest.raises(InvalidInputError, match="ambiguous"):
        resolve_custom_field_links(field, ["B", "A"], "customField4", subject="work package")


def test_two_custom_fields_with_the_same_name_are_ambiguous_by_name_but_not_by_key() -> None:
    schema = {"customField1": {"name": "Effort"}, "customField2": {"name": "Effort"}, "customField3": {"name": "Risk"}}

    with pytest.raises(InvalidInputError, match=r"ambiguous.*customField1, customField2"):
        resolve_custom_field_key(schema, "effort", subject="work package")
    assert resolve_custom_field_key(schema, "customField2", subject="work package") == "customField2"
    assert resolve_custom_field_key(schema, "risk", subject="work package") == "customField3"
