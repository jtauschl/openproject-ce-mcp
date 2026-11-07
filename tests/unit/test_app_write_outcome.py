from __future__ import annotations

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.services._write_outcome import _finalize_write


async def _noop_ensure_write_enabled() -> None:
    return None


async def _commit(payload: dict) -> str:
    return "committed-detail"


def _committed_identity(detail: object) -> dict:
    return {"detail": detail}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("confirm", "validation_errors", "expected_state", "expected_ready"),
    [
        (False, {"name": "is required"}, "rejected", False),
        (True, {"name": "is required"}, "invalid", False),
        (False, {}, "preview", True),
        (True, {}, "confirmed", True),
    ],
)
async def test_finalize_write_state_transitions(
    confirm: bool,
    validation_errors: dict[str, str],
    expected_state: str,
    expected_ready: bool,
) -> None:
    outcome = await _finalize_write(
        confirm=confirm,
        entity="project",
        settings=make_settings(),
        payload={"name": "value"},
        validation_errors=validation_errors,
        identity={"id": None},
        ensure_write_enabled=lambda: None,
        commit=_commit,
        committed_identity=_committed_identity,
        rejected_message="rejected",
        preview_message="preview",
        success_message="success",
    )
    assert outcome.state == expected_state
    assert outcome.ready is expected_ready


@pytest.mark.asyncio
async def test_finalize_write_only_commits_on_confirmed_valid_payload() -> None:
    calls: list[dict] = []

    async def commit(payload: dict) -> str:
        calls.append(payload)
        return "detail"

    for confirm, validation_errors in [(False, {}), (False, {"x": "bad"}), (True, {"x": "bad"})]:
        await _finalize_write(
            confirm=confirm,
            entity="project",
            settings=make_settings(),
            payload={"x": "value"},
            validation_errors=validation_errors,
            identity={},
            ensure_write_enabled=lambda: None,
            commit=commit,
            committed_identity=lambda d: {},
            rejected_message="rejected",
            preview_message="preview",
            success_message="success",
        )
    assert calls == []

    await _finalize_write(
        confirm=True,
        entity="project",
        settings=make_settings(),
        payload={"x": "value"},
        validation_errors={},
        identity={},
        ensure_write_enabled=lambda: None,
        commit=commit,
        committed_identity=lambda d: {},
        rejected_message="rejected",
        preview_message="preview",
        success_message="success",
    )
    assert calls == [{"x": "value"}]


@pytest.mark.asyncio
async def test_finalize_write_detail_and_identity_only_set_on_commit() -> None:
    for confirm, validation_errors in [(False, {}), (True, {"x": "bad"})]:
        outcome = await _finalize_write(
            confirm=confirm,
            entity="project",
            settings=make_settings(),
            payload={"x": "value"},
            validation_errors=validation_errors,
            identity={"id": 1},
            ensure_write_enabled=lambda: None,
            commit=_commit,
            committed_identity=_committed_identity,
            rejected_message="rejected",
            preview_message="preview",
            success_message="success",
        )
        assert outcome.detail is None
        assert outcome.identity == {"id": 1}

    committed = await _finalize_write(
        confirm=True,
        entity="project",
        settings=make_settings(),
        payload={"x": "value"},
        validation_errors={},
        identity={"id": 1},
        ensure_write_enabled=lambda: None,
        commit=_commit,
        committed_identity=_committed_identity,
        rejected_message="rejected",
        preview_message="preview",
        success_message="success",
    )
    assert committed.detail == "committed-detail"
    assert committed.identity == {"detail": "committed-detail"}


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", ["version", "time_entry", "project", "work_package", "membership"])
@pytest.mark.parametrize("confirm", [False, True])
async def test_every_entity_shows_a_payload_without_the_hidden_custom_fields_the_form_echoes(
    entity: str, confirm: bool
) -> None:
    import dataclasses

    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField4",))
    payload = {"name": "x", "customField4": "SECRET", "customField5": "visible", "_links": {"customField4": {}}}

    for errors in ({}, {"customField4": "Secret can't be blank", "name": "is required"}):
        outcome = await _finalize_write(
            confirm=confirm,
            entity=entity,
            settings=settings,
            payload=payload,
            validation_errors=errors,
            identity={},
            ensure_write_enabled=lambda: None,
            commit=_commit,
            committed_identity=_committed_identity,
            rejected_message="rejected",
            preview_message="preview",
            success_message="success",
        )
        assert outcome.payload == {"name": "x", "customField5": "visible", "_links": {}}
        if errors:
            assert outcome.validation_errors["name"] == "is required"
            assert "Secret" not in outcome.validation_errors["customField4"]


_ENTITIES = ["version", "time_entry", "project", "work_package", "membership", "meeting", "grid", "board"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", _ENTITIES)
async def test_an_entity_level_custom_fields_hide_applies_to_that_entity_only(entity: str) -> None:
    import dataclasses

    payload = {"name": "x", "customField5": "visible", "customComment5": "note", "_links": {"customField5": {}}}
    errors = {"customField5": "Visible can't be blank"}

    async def shown(settings_entity: str) -> tuple[dict[str, object], dict[str, str]]:
        settings = dataclasses.replace(make_settings(), hidden_fields={settings_entity: ("custom_fields",)})
        outcome = await _finalize_write(
            confirm=False,
            entity=entity,
            settings=settings,
            payload=payload,
            validation_errors=errors,
            identity={},
            ensure_write_enabled=lambda: None,
            commit=_commit,
            committed_identity=_committed_identity,
            rejected_message="rejected",
            preview_message="preview",
            success_message="success",
        )
        return outcome.payload, outcome.validation_errors

    own_payload, own_errors = await shown(entity)
    other_payload, other_errors = await shown("news" if entity != "news" else "project")

    assert own_payload == {"name": "x", "_links": {}}
    assert own_errors["customField5"] != errors["customField5"]
    assert other_payload == payload
    assert other_errors == errors


_HIDE_CALLS = {"_finalize_write", "without_hidden_custom_fields", "redacted_validation_errors"}


def test_each_service_redacts_a_write_under_its_own_entity() -> None:
    import ast
    import pathlib

    import openproject_ce_mcp.app.services as services

    checked: set[str] = set()
    for path in sorted(pathlib.Path(services.__file__).parent.glob("*_service.py")):
        expected = path.stem.removesuffix("_service")
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name not in _HIDE_CALLS:
                continue
            entity = next(kw.value for kw in node.keywords if kw.arg == "entity")
            assert isinstance(entity, ast.Constant), (path.name, node.lineno)
            assert entity.value == expected, (path.name, node.lineno, entity.value)
            checked.add(expected)
    assert checked == {
        "board",
        "grid",
        "meeting",
        "membership",
        "project",
        "time_entry",
        "user",
        "version",
        "work_package",
    }
