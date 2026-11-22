"""The texts of a server error, one case at a time: what the transport, the version gate and a service show.

The scan (`test_server_error_texts_hide_everything.py`) counts leaks and lost reasons over every write tool; these
cases pin the pieces it cannot see: the exact text with nothing hidden, the constant sentences, the version gate's
composition, the marker that keeps an inner render.
"""

from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.app.errors import (
    GENERIC_HIDDEN_FIELD,
    GENERIC_REJECTION,
    AuthenticationError,
    InvalidInputError,
    PermissionDeniedError,
)
from openproject_ce_mcp.app.services._error_masking import redacted_server_error
from openproject_ce_mcp.app.transport.errors import raise_for_status
from openproject_ce_mcp.app.version_gate import call_query_version_gated

MULTIPLE = {
    "errorIdentifier": "urn:openproject-org:api:v3:errors:MultipleErrors",
    "message": "Several constraints were violated.",
    "_embedded": {
        "errors": [
            {
                "errorIdentifier": "urn:openproject-org:api:v3:errors:PropertyConstraintViolation",
                "message": "Status is invalid",
                "_embedded": {"details": {"attribute": "status"}},
            },
            {
                "errorIdentifier": "urn:openproject-org:api:v3:errors:PropertyConstraintViolation",
                "message": "Subject can't be blank",
                "_embedded": {"details": {"attribute": "subject"}},
            },
        ]
    },
}
HIDE_STATUS = dataclasses.replace(_base_settings(), hidden_fields={"work_package": ("status",)})


def _rejection(payload: dict, *, redact: bool, status: int = 422) -> InvalidInputError:
    with pytest.raises(InvalidInputError) as caught:
        raise_for_status(status, payload, redact_server_text=redact)
    return caught.value


def test_with_nothing_hidden_the_text_is_what_the_server_sent() -> None:
    assert (
        str(_rejection(MULTIPLE, redact=False))
        == "Several constraints were violated. (Status is invalid; Subject can't be blank)"
    )


def test_with_a_hide_active_the_transport_says_only_that_the_request_was_rejected() -> None:
    error = _rejection(MULTIPLE, redact=True)

    assert str(error) == GENERIC_REJECTION
    assert [entry.attribute for entry in error.entries] == ["status", "subject"]


def test_a_service_renders_the_entries_again_and_keeps_the_visible_reason() -> None:
    error = _rejection(MULTIPLE, redact=True)

    shown = redacted_server_error(error, entity="work_package", settings=HIDE_STATUS)

    assert str(shown) == f"Several constraints were violated. ({GENERIC_HIDDEN_FIELD}; Subject can't be blank)"
    assert "Status" not in str(shown)
    assert shown.rendered and shown.__cause__ is error.__cause__


def test_a_render_is_done_once_and_the_inner_one_wins() -> None:
    error = _rejection(MULTIPLE, redact=True)
    inner = redacted_server_error(error, entity="work_package", settings=HIDE_STATUS)

    outer = redacted_server_error(inner, entity="project", settings=HIDE_STATUS)

    assert outer is inner


def test_nothing_is_rendered_while_no_hide_is_active() -> None:
    error = _rejection(MULTIPLE, redact=False)

    assert redacted_server_error(error, entity="work_package", settings=_base_settings()) is error


def test_a_stale_update_stays_readable() -> None:
    payload = {"errorIdentifier": "urn:openproject-org:api:v3:errors:UpdateConflict", "message": "Outdated."}

    assert str(_rejection(payload, redact=True, status=409)) == "Outdated."


def test_a_403_drops_its_detail_but_a_token_complaint_is_still_an_authentication_error() -> None:
    with pytest.raises(PermissionDeniedError) as denied:
        raise_for_status(403, {"message": "File report.pdf is quarantined"}, redact_server_text=True)
    with pytest.raises(AuthenticationError):
        raise_for_status(403, {"message": "You need to authenticate."}, redact_server_text=True)

    assert str(denied.value) == "OpenProject denied access to this resource."


@pytest.mark.asyncio
async def test_the_version_gate_keeps_the_server_reason_first_and_the_hint_after() -> None:
    async def rejected() -> None:
        raise _rejection(MULTIPLE, redact=False)

    with pytest.raises(InvalidInputError) as shown:
        await call_query_version_gated(rejected, feature="Sprint filters", floor="17.4")

    assert str(shown.value).startswith(
        "Several constraints were violated. (Status is invalid; Subject can't be blank) If this"
    )
    assert "requires 17.4 or newer" in str(shown.value)


@pytest.mark.asyncio
async def test_the_version_gate_keeps_the_entries_so_a_service_still_renders_them() -> None:
    async def rejected() -> None:
        raise _rejection(MULTIPLE, redact=True)

    with pytest.raises(InvalidInputError) as gated:
        await call_query_version_gated(rejected, feature="Sprint filters", floor="17.4")
    assert str(gated.value).startswith(f"{GENERIC_REJECTION} If this instance is older")

    shown = redacted_server_error(gated.value, entity="work_package", settings=HIDE_STATUS)

    assert str(shown).startswith(
        f"Several constraints were violated. ({GENERIC_HIDDEN_FIELD}; Subject can't be blank) If this"
    )
    assert "Status" not in str(shown)


@pytest.mark.asyncio
async def test_a_403_keeps_its_denial_sentence_when_a_service_renders_the_entries() -> None:
    """Hidden status only: the entry names a visible field, the denial sentence still opens the text."""
    payload = {
        "errorIdentifier": "urn:openproject-org:api:v3:errors:MissingPermission",
        "message": "You are not authorized to edit.",
        "_embedded": {"details": {"attribute": "subject"}},
    }
    with pytest.raises(PermissionDeniedError) as denied:
        raise_for_status(403, payload, redact_server_text=True)

    shown = redacted_server_error(denied.value, entity="work_package", settings=HIDE_STATUS)

    assert str(shown) == "OpenProject denied access to this resource. (You are not authorized to edit.)"
    assert isinstance(shown, PermissionDeniedError)


def test_only_a_stale_update_is_verbatim_and_a_denial_with_a_file_name_is_not() -> None:
    """The list of classes whose text is a constant sentence is pinned: a permission error can name a file."""
    from openproject_ce_mcp.app.errors import VERBATIM_CODES

    assert VERBATIM_CODES == {"UpdateConflict"}
    payload = {
        "errorIdentifier": "urn:openproject-org:api:v3:errors:MissingPermission",
        "message": "File report.pdf is quarantined",
    }
    with pytest.raises(PermissionDeniedError) as denied:
        raise_for_status(403, payload, redact_server_text=True)

    assert "report.pdf" not in str(denied.value)


def test_an_attribute_less_403_shows_the_denial_sentence_only_after_a_service_rendered_it() -> None:
    payload = {
        "errorIdentifier": "urn:openproject-org:api:v3:errors:MissingPermission",
        "message": "File report.pdf is quarantined",
    }
    with pytest.raises(PermissionDeniedError) as denied:
        raise_for_status(403, payload, redact_server_text=True)

    shown = redacted_server_error(denied.value, entity="work_package", settings=HIDE_STATUS)

    assert str(shown) == "OpenProject denied access to this resource."


WORK_PACKAGE_BASE = ["status", "version", "target_versions", "parent_id", "parent_display_id", "project", "type"]


@pytest.mark.parametrize("field", WORK_PACKAGE_BASE)
def test_a_base_error_of_a_work_package_goes_with_each_field_it_can_describe(field: str) -> None:
    """Written out here, not read from the policy: five of these were once pinned by no test."""
    from openproject_ce_mcp.app.errors import ServerErrorEntry
    from openproject_ce_mcp.app.policies.error_fields import error_entry_hidden

    base = ServerErrorEntry(attribute="base", code="PropertyConstraintViolation", message="Closed version")
    hidden = dataclasses.replace(_base_settings(), hidden_fields={"work_package": (field,)})
    other = dataclasses.replace(_base_settings(), hidden_fields={"work_package": ("subject",)})

    assert error_entry_hidden(base, entity="work_package", settings=hidden)
    assert not error_entry_hidden(base, entity="work_package", settings=other)
