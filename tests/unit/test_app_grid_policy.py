from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.policies.grid_policy import (
    MyPageScope,
    ProjectScope,
    ResolvedProject,
    ensure_grid_allowed,
    parse_grid_scope,
)
from openproject_ce_mcp.app.policies.scope import PrefixMismatch

DEMO = ResolvedProject(6, "demo", "Demo Project")


def _settings(
    read: tuple[str, ...] = ("*",), write: tuple[str, ...] = ("*",), base_url: str = "https://op.example.com"
):
    return dataclasses.replace(make_settings(), read_projects=read, write_projects=write, base_url=base_url)


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("/my/page", MyPageScope()),
        ("/projects/demo", ProjectScope("demo")),
        ("/projects/demo/boards", ProjectScope("demo")),
        ("/projects/DEMO_2", ProjectScope("DEMO_2")),
        ("/projects/6", ProjectScope("6")),
    ],
)
def test_parse_grid_scope_accepts_the_shapes_openproject_uses(href: str, expected: object) -> None:
    assert parse_grid_scope(href, settings=_settings()) == expected


def test_parse_grid_scope_honours_the_root_path_of_a_subpath_install() -> None:
    settings = _settings(base_url="https://op.example.com/openproject")

    assert parse_grid_scope("/openproject/projects/demo/boards", settings=settings) == ProjectScope("demo")
    assert parse_grid_scope("/openproject/my/page", settings=settings) == MyPageScope()


@pytest.mark.parametrize(
    ("base_url", "href", "emitted"),
    [
        ("https://op.example.com/openproject", "/projects/demo", "/api/v3/"),
        ("https://op.example.com", "/openproject/projects/demo", "/openproject/api/v3/"),
        ("https://op.example.com", "/openproject/my/page", "/openproject/api/v3/"),
        ("https://op.example.com", "/api/projects/demo", "/api/api/v3/"),
    ],
)
def test_parse_grid_scope_reports_a_scope_under_another_root_path(base_url: str, href: str, emitted: str) -> None:
    assert parse_grid_scope(href, settings=_settings(base_url=base_url)) == PrefixMismatch(emitted)


@pytest.mark.parametrize(
    "href",
    [
        None,
        42,
        "",
        "/projects",
        "/projects/",
        "/projects/demo/settings",
        "/projects/demo/boards/1",
        "/my/page/x",
        "projects/demo",
        "//evil.example.com/projects/demo",
        "https://op.example.com/projects/demo",
        "/projects/demo?x=1",
        "/projects/demo#x",
        "/projects/demo;x",
        "/projects/de%6Do",
        "/projects/../my/page",
        "/projects/./demo",
        "/projects/de mo",
        "/projects/demo\n",
        "/projects/demö",
        "/projects/" + "a" * 101,
    ],
)
def test_parse_grid_scope_rejects_every_other_shape(href: object) -> None:
    assert parse_grid_scope(href, settings=_settings()) is None


def test_my_page_is_allowed_under_any_scope() -> None:
    ensure_grid_allowed(
        MyPageScope(),
        project_link=None,
        resolved=None,
        write=True,
        settings=_settings(read=("other",), write=("other",)),
        project_id_to_identifier={},
    )


def test_a_project_scope_needs_no_resolution_when_wide_open() -> None:
    ensure_grid_allowed(
        ProjectScope("demo"),
        project_link=None,
        resolved=None,
        write=True,
        settings=_settings(),
        project_id_to_identifier={},
    )


@pytest.mark.parametrize("allowlist", [("demo",), ("6",), ("Demo Project",), ("dem*",)])
def test_a_resolved_project_is_matched_by_id_identifier_or_name(allowlist: tuple[str, ...]) -> None:
    ensure_grid_allowed(
        ProjectScope("old-demo"),
        project_link=None,
        resolved=DEMO,
        write=True,
        settings=_settings(read=allowlist, write=allowlist),
        project_id_to_identifier={},
    )


@pytest.mark.parametrize(
    ("read", "write", "is_write", "message"),
    [
        (("other",), ("*",), False, "OPENPROJECT_READ_PROJECTS"),
        (("demo",), ("other",), True, "OPENPROJECT_WRITE_PROJECTS"),
        (("other",), ("demo",), True, "OPENPROJECT_READ_PROJECTS"),
    ],
)
def test_a_resolved_project_outside_the_allowlist_is_denied(read, write, is_write: bool, message: str) -> None:
    with pytest.raises(PermissionDeniedError, match=message):
        ensure_grid_allowed(
            ProjectScope("demo"),
            project_link=None,
            resolved=DEMO,
            write=is_write,
            settings=_settings(read=read, write=write),
            project_id_to_identifier={},
        )


def test_an_unresolved_project_scope_is_denied_under_a_restrictive_scope() -> None:
    with pytest.raises(PermissionDeniedError):
        ensure_grid_allowed(
            ProjectScope("gone"),
            project_link=None,
            resolved=None,
            write=False,
            settings=_settings(read=("*gone*",)),
            project_id_to_identifier={},
        )


@pytest.mark.parametrize(
    "project_link",
    [
        {"href": "https://evil.example.com/api/v3/projects/6"},
        {"href": "/api/v3/users/6"},
        {"href": None},
        "not-a-link",
    ],
)
def test_a_grid_project_link_must_be_a_project_link_of_this_instance_even_when_wide_open(project_link) -> None:
    with pytest.raises(PermissionDeniedError):
        ensure_grid_allowed(
            ProjectScope("demo"),
            project_link=project_link,
            resolved=None,
            write=False,
            settings=_settings(),
            project_id_to_identifier={},
        )


def test_an_allowed_project_link_does_not_mask_a_disallowed_scope_project() -> None:
    with pytest.raises(PermissionDeniedError):
        ensure_grid_allowed(
            ProjectScope("secret"),
            project_link={"href": "/api/v3/projects/6", "title": "Demo Project"},
            resolved=ResolvedProject(9, "secret", "Secret"),
            write=False,
            settings=_settings(read=("demo", "Demo Project")),
            project_id_to_identifier={6: "demo"},
        )


def test_an_allowed_scope_project_does_not_mask_a_disallowed_project_link() -> None:
    with pytest.raises(PermissionDeniedError):
        ensure_grid_allowed(
            ProjectScope("demo"),
            project_link={"href": "/api/v3/projects/9", "title": "Secret"},
            resolved=DEMO,
            write=False,
            settings=_settings(read=("demo",)),
            project_id_to_identifier={9: "secret"},
        )


def test_a_grid_whose_scope_and_project_link_agree_is_allowed() -> None:
    ensure_grid_allowed(
        ProjectScope("demo"),
        project_link={"href": "/api/v3/projects/6", "title": "Demo Project"},
        resolved=DEMO,
        write=True,
        settings=_settings(read=("demo",), write=("demo",)),
        project_id_to_identifier={6: "demo"},
    )


def test_a_scope_and_project_link_naming_two_allowed_projects_are_denied() -> None:
    with pytest.raises(PermissionDeniedError):
        ensure_grid_allowed(
            ProjectScope("demo-two"),
            project_link={"href": "/api/v3/projects/6", "title": "Demo Project"},
            resolved=ResolvedProject(7, "demo-two", "Demo Two"),
            write=False,
            settings=_settings(read=("demo*",)),
            project_id_to_identifier={6: "demo"},
        )


@pytest.mark.parametrize(
    ("base_url", "href", "ref"),
    [
        ("https://op.example.com", "/projects/projects", "projects"),
        ("https://op.example.com", "/projects/projects/boards", "projects"),
        ("https://op.example.com/openproject", "/openproject/projects/projects/boards", "projects"),
        ("https://op.example.com/projects", "/projects/projects/projects/boards", "projects"),
        ("https://op.example.com/projects", "/projects/projects/boards", "boards"),
    ],
)
def test_a_project_called_projects_is_read_under_the_instances_own_root(base_url: str, href: str, ref: str) -> None:
    assert parse_grid_scope(href, settings=_settings(base_url=base_url)) == ProjectScope(ref)
