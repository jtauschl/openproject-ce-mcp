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


# --- classify_project_link (OPM-359) ------------------------------------------


def test_classify_project_link_resolved() -> None:
    assert scope.classify_project_link({"href": "/api/v3/projects/7", "title": "Demo"}) is scope.LinkState.RESOLVED


def test_classify_project_link_undisclosed() -> None:
    link = {"href": scope.URN_UNDISCLOSED, "title": "Undisclosed project"}
    assert scope.classify_project_link(link) is scope.LinkState.UNDISCLOSED


def test_classify_project_link_explicitly_unscoped() -> None:
    assert scope.classify_project_link({"href": None}) is scope.LinkState.EXPLICITLY_UNSCOPED


def test_classify_project_link_missing() -> None:
    assert scope.classify_project_link(None) is scope.LinkState.MISSING


def test_classify_project_link_malformed_not_a_dict() -> None:
    assert scope.classify_project_link("not-a-dict") is scope.LinkState.MALFORMED
    assert scope.classify_project_link(42) is scope.LinkState.MALFORMED
    assert scope.classify_project_link([]) is scope.LinkState.MALFORMED


def test_classify_project_link_malformed_no_href_key() -> None:
    """A dict with no "href" key at all (e.g. a typo like {"hreef": ...}, or
    just {"title": "x"}) is never a real representer shape -- distinct from
    {"href": None}, which IS the documented explicit-empty form."""
    assert scope.classify_project_link({}) is scope.LinkState.MALFORMED
    assert scope.classify_project_link({"title": "Demo"}) is scope.LinkState.MALFORMED


def test_classify_project_link_malformed_blank_href() -> None:
    assert scope.classify_project_link({"href": ""}) is scope.LinkState.MALFORMED
    assert scope.classify_project_link({"href": "   "}) is scope.LinkState.MALFORMED


def test_classify_project_link_malformed_non_string_href() -> None:
    assert scope.classify_project_link({"href": 42}) is scope.LinkState.MALFORMED


# --- ensure_project_link_allowed: now fail-closed on MISSING/MALFORMED (OPM-359) --


def test_ensure_project_link_allowed_denies_missing_link_even_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        scope.ensure_project_link_allowed(None, settings=settings, project_id_to_identifier={})


def test_ensure_project_link_allowed_denies_malformed_link_even_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        scope.ensure_project_link_allowed({"title": "Demo"}, settings=settings, project_id_to_identifier={})


def test_ensure_project_link_allowed_denies_explicitly_unscoped_link_under_wildcard_scope() -> None:
    """A required-project-link resource never legitimately sees {"href":
    None} -- treat it as anomalous (deny), not as an accepted optional state."""
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        scope.ensure_project_link_allowed({"href": None}, settings=settings, project_id_to_identifier={})


def test_ensure_project_link_allowed_treats_undisclosed_like_resolved_under_wildcard() -> None:
    link = {"href": scope.URN_UNDISCLOSED, "title": "Undisclosed project"}
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    scope.ensure_project_link_allowed(link, settings=settings, project_id_to_identifier={})  # must not raise


def test_ensure_project_link_allowed_denies_undisclosed_under_restrictive_scope() -> None:
    """A restrictive scope can never confirm an undisclosed project's real
    identity is on the allowlist -- always deny, not candidate-match against
    the meaningless placeholder title/URN."""
    link = {"href": scope.URN_UNDISCLOSED, "title": "Undisclosed project"}
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        scope.ensure_project_link_allowed(link, settings=settings, project_id_to_identifier={})


# --- ensure_project_link_allowed_if_present: preserves the pre-fix optional contract --


def test_ensure_project_link_allowed_if_present_allows_missing_link_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    scope.ensure_project_link_allowed_if_present(None, settings=settings, project_id_to_identifier={})  # no raise
    scope.ensure_project_link_allowed_if_present(
        {"href": None}, settings=settings, project_id_to_identifier={}
    )  # no raise


def test_ensure_project_link_allowed_if_present_denies_missing_link_under_restrictive_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        scope.ensure_project_link_allowed_if_present(None, settings=settings, project_id_to_identifier={})


def test_ensure_project_link_allowed_if_present_denies_malformed_link_even_under_wildcard_scope() -> None:
    """Unlike missing/explicitly-empty, MALFORMED is newly always denied here
    too -- a structurally broken link is never the same as "deliberately none"."""
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        scope.ensure_project_link_allowed_if_present({"title": "Demo"}, settings=settings, project_id_to_identifier={})


def test_ensure_project_write_link_allowed_if_present_denies_malformed_link_even_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    with pytest.raises(PermissionDeniedError):
        scope.ensure_project_write_link_allowed_if_present(
            {"title": "Demo"}, settings=settings, project_id_to_identifier={}
        )
