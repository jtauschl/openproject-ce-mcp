from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.policies import hidden_fields


@dataclass
class _FakeSummary:
    id: int
    name: str
    updated_at: str | None


def test_normalize_hide_token_folds_case_and_separators() -> None:
    assert hidden_fields.normalize_hide_token("Updated-At") == "updated_at"
    assert hidden_fields.normalize_hide_token("updated at") == "updated_at"


def test_field_hidden_matches_configured_pattern() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"version": ("updated_at",)})
    assert hidden_fields.field_hidden("version", "updated_at", settings=settings) is True
    assert hidden_fields.field_hidden("version", "name", settings=settings) is False


def test_field_hidden_false_when_no_patterns_configured() -> None:
    settings = make_settings()
    assert hidden_fields.field_hidden("version", "updated_at", settings=settings) is False


def test_ensure_field_writable_raises_with_env_var_hint_for_hidden_field() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"version": ("name",)})
    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_VERSION_FIELDS"):
        hidden_fields.ensure_field_writable("version", "name", settings=settings)


def test_ensure_field_writable_noop_for_visible_field() -> None:
    settings = make_settings()
    hidden_fields.ensure_field_writable("version", "name", settings=settings)  # must not raise


def test_apply_hidden_fields_stamps_hidden_keys_without_changing_values() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"version": ("updated_at",)})
    summary = _FakeSummary(id=1, name="v1.0", updated_at="2026-01-01")
    stamped = hidden_fields.apply_hidden_fields("version", summary, settings=settings)
    assert stamped.updated_at == "2026-01-01"  # masking never changes field values
    assert stamped._hidden_keys == frozenset({"updated_at"})


def test_apply_hidden_fields_no_stamp_when_nothing_hidden() -> None:
    settings = make_settings()
    summary = _FakeSummary(id=1, name="v1.0", updated_at="2026-01-01")
    stamped = hidden_fields.apply_hidden_fields("version", summary, settings=settings)
    assert not hasattr(stamped, "_hidden_keys")


def test_apply_hidden_fields_passthrough_for_non_dataclass() -> None:
    settings = make_settings()
    assert hidden_fields.apply_hidden_fields("version", "not a dataclass", settings=settings) == "not a dataclass"
