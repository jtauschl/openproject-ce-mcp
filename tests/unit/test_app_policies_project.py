from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.policies import project_policy


def test_ensure_project_read_allowed_raises_when_no_candidate_matches() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        project_policy.ensure_project_read_allowed(
            {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_read_allowed_noop_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    project_policy.ensure_project_read_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
    )  # must not raise


def test_ensure_project_write_allowed_checks_read_before_write() -> None:
    # read_projects excludes it -> must fail on the read check, not the write one
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("*",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        project_policy.ensure_project_write_allowed(
            {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_write_allowed_raises_for_write_restricted_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        project_policy.ensure_project_write_allowed(
            {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_write_allowed_noop_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    project_policy.ensure_project_write_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
    )  # must not raise


def test_ensure_project_create_target_allowed_rejects_when_read_scope_excludes_it() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("*",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        project_policy.ensure_project_create_target_allowed(
            identifier="demo", name="Demo", settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_create_target_allowed_rejects_when_write_scope_excludes_it() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        project_policy.ensure_project_create_target_allowed(
            identifier="demo", name="Demo", settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_create_target_allowed_noop_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    project_policy.ensure_project_create_target_allowed(
        identifier="demo", name="Demo", settings=settings, project_id_to_identifier={}
    )  # must not raise


def test_ensure_project_read_allowed_matches_via_project_ref_not_present_in_payload() -> None:
    # payload's own fields don't match the scope, but the ref used to resolve it does
    # -- client.py's _ensure_project_allowed always includes project_ref as a candidate.
    settings = dataclasses.replace(make_settings(), read_projects=("legacy-ref",))
    project_policy.ensure_project_read_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"},
        project_ref="legacy-ref",
        settings=settings,
        project_id_to_identifier={},
    )  # must not raise


def test_ensure_project_write_allowed_matches_via_project_ref_not_present_in_payload() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("legacy-ref",), write_projects=("legacy-ref",))
    project_policy.ensure_project_write_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"},
        project_ref="legacy-ref",
        settings=settings,
        project_id_to_identifier={},
    )  # must not raise
