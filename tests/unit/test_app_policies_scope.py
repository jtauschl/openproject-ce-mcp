from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.policies import scope


def test_scope_allows_all_recognizes_wildcard() -> None:
    assert scope.scope_allows_all(("*",)) is True
    assert scope.scope_allows_all((" * ",)) is True
    assert scope.scope_allows_all(("demo",)) is False
    assert scope.scope_allows_all(()) is False


def test_scope_matches_candidates_glob_and_case_insensitive() -> None:
    assert scope.scope_matches_candidates(("demo-*",), {"demo-project"}) is True
    assert scope.scope_matches_candidates(("DEMO-*",), {"demo-project"}) is True
    assert scope.scope_matches_candidates(("other",), {"demo-project"}) is False
    # empty candidate set always fails closed, even under a wildcard scope
    assert scope.scope_matches_candidates(("*",), set()) is False


def test_project_candidates_from_link_recovers_identifier_via_cache() -> None:
    link = {"href": "/api/v3/projects/7", "title": "OPM OpenProject CE MCP"}
    candidates = scope.project_candidates(project_id_to_identifier={7: "OPM"}, link=link)
    assert "opm" in candidates
    assert "7" in candidates
    assert "opm openproject ce mcp" in candidates
    assert "opm-openproject-ce-mcp" in candidates


def test_project_candidates_from_link_without_cache_entry_lacks_identifier() -> None:
    link = {"href": "/api/v3/projects/7", "title": "OPM OpenProject CE MCP"}
    candidates = scope.project_candidates(project_id_to_identifier={}, link=link)
    assert "opm" not in candidates
    assert "7" in candidates


def test_project_candidates_from_payload_uses_identifier_and_name() -> None:
    payload = {"id": 1, "identifier": "demo", "name": "Demo Project"}
    candidates = scope.project_candidates(project_id_to_identifier={}, payload=payload)
    assert candidates == {"1", "demo", "demo project"}


def test_ensure_project_link_allowed_raises_when_no_candidate_matches() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        scope.ensure_project_link_allowed(
            {"href": "/api/v3/projects/7", "title": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_link_allowed_noop_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    scope.ensure_project_link_allowed(
        {"href": "/api/v3/projects/7", "title": "Demo"}, settings=settings, project_id_to_identifier={}
    )  # must not raise


def test_ensure_project_write_link_allowed_checks_read_before_write() -> None:
    # read_projects excludes it -> must fail on the read check, not the write one
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("*",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        scope.ensure_project_write_link_allowed(
            {"href": "/api/v3/projects/7", "title": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_write_link_allowed_raises_for_write_restricted_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        scope.ensure_project_write_link_allowed(
            {"href": "/api/v3/projects/7", "title": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_payload_allowed_converts_permission_denied_to_false() -> None:
    def ensure_ok() -> None:
        return None

    def ensure_denied() -> None:
        raise PermissionDeniedError("no")

    assert scope.payload_allowed(ensure_ok) is True
    assert scope.payload_allowed(ensure_denied) is False
