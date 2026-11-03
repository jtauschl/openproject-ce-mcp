"""`dump_payload` is the one serialiser of every tool result.

It must differ from the serialiser the MCP SDK used before only in whitespace, so the oracle is the SDK's own
call (`pydantic_core.to_json(..., fallback=str)`) with its indentation removed.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import enum
import json

import pydantic_core
import pytest

from openproject_ce_mcp.presentation import ResultSerializationError, dump_payload


class _Colour(enum.Enum):
    RED = "red"


@dataclasses.dataclass
class _Row:
    id: int
    name: str


class _Opaque:
    def __str__(self) -> str:
        return "opaque-object"


CORPUS = {
    "nested": {"a": {"b": [1, 2, {"c": None}], "d": True}, "e": []},
    "non_ascii": {"subject": "Überprüfung für 東京 \U0001f680"},
    "control_characters": {"text": "line\nbreak\ttab   \x01"},
    "datetime": {"at": datetime.datetime(2026, 11, 2, 20, 22, 38), "on": datetime.date(2026, 11, 2)},
    "decimal": {"hours": decimal.Decimal("1.50")},
    "enum": {"colour": _Colour.RED},
    "set": {"ids": {7}},
    "dataclass_in_dict": {"row": _Row(1, "x")},
    "non_string_keys": {1: "one", (2, 3): "pair"},
    "floats": {"big": 1e20, "small": 1e-7, "plain": 0.5},
    "empty_containers": {"list": [], "dict": {}, "text": ""},
    "fallback_object": {"thing": _Opaque()},
}


@pytest.mark.parametrize("name", CORPUS)
def test_it_equals_the_sdk_serialisation_without_its_indentation(name: str) -> None:
    value = CORPUS[name]

    assert dump_payload(value) == pydantic_core.to_json(value, fallback=str).decode()


@pytest.mark.parametrize("name", CORPUS)
def test_it_is_one_line_that_parses_back_to_the_sdk_value(name: str) -> None:
    value = CORPUS[name]

    text = dump_payload(value)

    assert "\n" not in text
    assert json.loads(text) == json.loads(pydantic_core.to_json(value, fallback=str, indent=2))


def test_it_has_no_whitespace_between_structural_tokens() -> None:
    text = dump_payload({"a": [1, {"b": 2}], "c": "x y"})

    assert text == '{"a":[1,{"b":2}],"c":"x y"}'


def test_it_keeps_non_ascii_characters_unescaped() -> None:
    assert dump_payload({"s": "für 東京"}) == '{"s":"für 東京"}'


def test_it_serialises_a_datetime_as_iso_8601() -> None:
    assert dump_payload({"at": datetime.datetime(2026, 11, 2, 20, 22, 38)}) == '{"at":"2026-11-02T20:22:38"}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_float_becomes_null_because_json_has_no_such_number(value: float) -> None:
    assert dump_payload({"x": value}) == '{"x":null}'


def test_an_unserialisable_value_raises_an_error_that_does_not_carry_its_text_or_pass_as_a_value_error() -> None:
    class Unrenderable:
        def __str__(self) -> str:
            raise RuntimeError("secret internal detail")

    with pytest.raises(ResultSerializationError) as raised:
        dump_payload({"x": Unrenderable()})

    assert not isinstance(raised.value, ValueError)
    assert "secret" not in str(raised.value)
