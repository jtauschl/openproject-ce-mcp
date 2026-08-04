from __future__ import annotations

import pytest

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
