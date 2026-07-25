from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.policies.grid_policy import (
    ensure_grid_read_allowed,
    ensure_grid_write_allowed,
    grid_read_allowed,
)


def test_ensure_grid_read_allowed_permits_my_page_under_restrictive_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    ensure_grid_read_allowed({"href": "/my/page"}, settings=settings, project_id_to_identifier={})


def test_ensure_grid_read_allowed_denies_project_scope_outside_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        ensure_grid_read_allowed({"href": "/projects/6"}, settings=settings, project_id_to_identifier={})


def test_ensure_grid_read_allowed_permits_project_scope_when_allowed() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    ensure_grid_read_allowed({"href": "/projects/6"}, settings=settings, project_id_to_identifier={6: "demo"})


def test_grid_read_allowed_returns_bool_instead_of_raising() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    assert grid_read_allowed({"href": "/projects/6"}, settings=settings, project_id_to_identifier={}) is False
    assert grid_read_allowed({"href": "/my/page"}, settings=settings, project_id_to_identifier={}) is True


def test_ensure_grid_write_allowed_permits_my_page_under_restrictive_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("other",))
    ensure_grid_write_allowed("/my/page", settings=settings, project_id_to_identifier={})


def test_ensure_grid_write_allowed_permits_no_scope_when_both_scopes_wide_open() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    ensure_grid_write_allowed(None, settings=settings, project_id_to_identifier={})


def test_ensure_grid_write_allowed_denies_missing_scope_when_restrictive() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        ensure_grid_write_allowed(None, settings=settings, project_id_to_identifier={})


def test_ensure_grid_write_allowed_denies_project_scope_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        ensure_grid_write_allowed("/projects/6", settings=settings, project_id_to_identifier={})


def test_ensure_grid_write_allowed_permits_project_scope_when_allowed() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    ensure_grid_write_allowed("/projects/6", settings=settings, project_id_to_identifier={6: "demo"})
