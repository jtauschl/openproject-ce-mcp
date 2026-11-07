"""Hide-on-read and hide-on-preview of custom field keys, one rule for every entity."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.services._custom_field_masking import (
    custom_field_key_hidden,
    mask_custom_field_values,
    without_hidden_custom_fields,
)


@dataclasses.dataclass
class _Carrier:
    custom_fields: dict[str, Any] | None = None
    custom_fields_truncated: bool = False
    custom_comments: dict[str, str] | None = None
    custom_comments_truncated: bool = False


def _settings(*, keys: tuple[str, ...] = (), entity_hide: tuple[str, ...] = (), entity: str = "project"):
    return dataclasses.replace(
        make_settings(), hide_custom_fields=keys, hidden_fields={entity: entity_hide} if entity_hide else {}
    )


@pytest.mark.parametrize("entity", ["project", "work_package"])
def test_a_comment_is_hidden_with_its_field_even_when_the_field_value_is_not_in_the_result(entity: str) -> None:
    carrier = _Carrier(
        custom_fields={"customField1": "visible"},
        custom_comments={"customComment60": "secret", "customComment1": "kept"},
    )

    masked = mask_custom_field_values(carrier, entity=entity, settings=_settings(keys=("customField60",)))

    assert masked.custom_comments == {"customComment1": "kept"}
    assert masked.custom_fields == {"customField1": "visible"}


def test_a_hidden_field_leaves_neither_value_nor_comment() -> None:
    carrier = _Carrier(
        custom_fields={"customField2": "secret", "customField3": "ok"},
        custom_comments={"customComment2": "secret note"},
    )

    masked = mask_custom_field_values(carrier, entity="project", settings=_settings(keys=("customField2",)))

    assert masked.custom_fields == {"customField3": "ok"}
    assert masked.custom_comments is None


def test_nothing_hidden_returns_the_same_object() -> None:
    carrier = _Carrier(custom_fields={"customField2": "x"}, custom_comments={"customComment2": "y"})

    assert mask_custom_field_values(carrier, entity="project", settings=_settings(keys=("customField9",))) is carrier


def test_the_entity_hide_of_custom_fields_takes_the_comments_and_flags_too() -> None:
    carrier = _Carrier(
        custom_fields={"customField2": "x"},
        custom_fields_truncated=True,
        custom_comments={"customComment2": "y"},
        custom_comments_truncated=True,
    )

    masked = mask_custom_field_values(carrier, entity="project", settings=_settings(entity_hide=("custom_fields",)))

    assert (masked.custom_fields, masked.custom_comments) == (None, None)
    assert (masked.custom_fields_truncated, masked.custom_comments_truncated) == (False, False)


def test_the_entity_hide_of_custom_comments_keeps_the_values() -> None:
    carrier = _Carrier(custom_fields={"customField2": "x"}, custom_comments={"customComment2": "y"})

    masked = mask_custom_field_values(carrier, entity="project", settings=_settings(entity_hide=("custom_comments",)))

    assert masked.custom_fields == {"customField2": "x"}
    assert masked.custom_comments is None


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("customField5", True),
        ("customComment5", True),
        ("customField50", False),
        ("customComment50", False),
        ("name", False),
        ("customFieldX", False),
    ],
)
def test_a_key_is_judged_by_the_id_of_its_field(key: str, expected: bool) -> None:
    assert custom_field_key_hidden(key, entity="project", settings=_settings(keys=("customField5",))) is expected


@pytest.mark.parametrize("entity", ["project", "work_package"])
def test_a_preview_payload_drops_hidden_values_at_the_top_level_and_under_links(entity: str) -> None:
    payload = {
        "name": "Demo",
        "customField2": "SECRET VALUE",
        "customComment2": "SECRET NOTE",
        "customField3": "visible",
        "_links": {
            "customField2": {"href": "/api/v3/users/9"},
            "customField3": {"href": "/api/v3/users/8"},
            "parent": {},
        },
    }

    shown = without_hidden_custom_fields(
        payload, entity=entity, settings=_settings(keys=("customField2",), entity=entity)
    )

    assert shown == {
        "name": "Demo",
        "customField3": "visible",
        "_links": {"customField3": {"href": "/api/v3/users/8"}, "parent": {}},
    }
    assert "customField2" in payload and "customField2" in payload["_links"]


def test_a_preview_payload_without_hidden_fields_is_unchanged() -> None:
    payload = {"name": "Demo", "customField2": "x", "_links": {"parent": {}}}

    assert without_hidden_custom_fields(payload, entity="project", settings=_settings()) == payload
