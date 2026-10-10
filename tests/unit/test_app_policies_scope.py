from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError, ProjectLinkPrefixError
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
    link = {"href": "/api/v3/projects/7", "title": "Demo Project"}
    candidates = scope.project_candidates(settings=make_settings(), project_id_to_identifier={7: "DEMO"}, link=link)
    assert "demo" in candidates
    assert "7" in candidates
    assert "demo project" in candidates
    assert "demo-project" in candidates


def test_project_candidates_from_link_without_cache_entry_lacks_identifier() -> None:
    link = {"href": "/api/v3/projects/7", "title": "Demo Project"}
    candidates = scope.project_candidates(settings=make_settings(), project_id_to_identifier={}, link=link)
    assert "demo" not in candidates
    assert "7" in candidates


def test_project_candidates_from_payload_uses_identifier_and_name() -> None:
    payload = {"id": 1, "identifier": "demo", "name": "Demo Project"}
    candidates = scope.project_candidates(settings=make_settings(), project_id_to_identifier={}, payload=payload)
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


# --- classify_project_link ------------------------------------------


def test_classify_project_link_resolved() -> None:
    assert (
        scope.classify_project_link({"href": "/api/v3/projects/7", "title": "Demo"}, settings=make_settings())
        is scope.LinkState.RESOLVED
    )


def test_classify_project_link_undisclosed() -> None:
    link = {"href": scope.URN_UNDISCLOSED, "title": "Undisclosed project"}
    assert scope.classify_project_link(link, settings=make_settings()) is scope.LinkState.UNDISCLOSED


def test_classify_project_link_explicitly_unscoped() -> None:
    assert scope.classify_project_link({"href": None}, settings=make_settings()) is scope.LinkState.EXPLICITLY_UNSCOPED


def test_classify_project_link_missing() -> None:
    assert scope.classify_project_link(None, settings=make_settings()) is scope.LinkState.MISSING


def test_classify_project_link_malformed_not_a_dict() -> None:
    assert scope.classify_project_link("not-a-dict", settings=make_settings()) is scope.LinkState.MALFORMED
    assert scope.classify_project_link(42, settings=make_settings()) is scope.LinkState.MALFORMED
    assert scope.classify_project_link([], settings=make_settings()) is scope.LinkState.MALFORMED


def test_classify_project_link_malformed_no_href_key() -> None:
    """A dict with no "href" key at all (e.g. a typo like {"hreef": ...}, or
    just {"title": "x"}) is never a real representer shape -- distinct from
    {"href": None}, which IS the documented explicit-empty form."""
    assert scope.classify_project_link({}, settings=make_settings()) is scope.LinkState.MALFORMED
    assert scope.classify_project_link({"title": "Demo"}, settings=make_settings()) is scope.LinkState.MALFORMED


def test_classify_project_link_malformed_blank_href() -> None:
    assert scope.classify_project_link({"href": ""}, settings=make_settings()) is scope.LinkState.MALFORMED
    assert scope.classify_project_link({"href": "   "}, settings=make_settings()) is scope.LinkState.MALFORMED


def test_classify_project_link_malformed_non_string_href() -> None:
    assert scope.classify_project_link({"href": 42}, settings=make_settings()) is scope.LinkState.MALFORMED


# --- ensure_project_link_allowed: fail-closed on MISSING/MALFORMED --------------


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


def _instance(base_url: str = "https://op.example.com", read=("*",), write=("*",)):
    return dataclasses.replace(make_settings(), base_url=base_url, read_projects=read, write_projects=write)


@pytest.mark.parametrize(
    ("href", "project_id"),
    [
        ("/api/v3/projects/7", 7),
        ("/api/v3/programs/7", 7),
        ("/api/v3/portfolios/7", 7),
        ("/api/v3/workspaces/7", 7),
        ("https://op.example.com/api/v3/projects/7", 7),
        ("https://OP.EXAMPLE.COM:443/api/v3/projects/7", 7),
        ("/api/v3/projects/9223372036854775807", 9223372036854775807),
    ],
)
def test_parse_project_href_accepts_what_openproject_emits(href: str, project_id: int) -> None:
    assert scope.parse_project_href(href, settings=_instance()) == scope.LinkedProject(project_id)


def test_parse_project_href_honours_the_root_path_of_a_subpath_install() -> None:
    settings = _instance(base_url="https://op.example.com/openproject")

    assert scope.parse_project_href("/openproject/api/v3/projects/7", settings=settings) == scope.LinkedProject(7)


@pytest.mark.parametrize(
    "href",
    [
        None,
        7,
        "",
        "https://evil.example.com/api/v3/projects/7",
        "http://op.example.com/api/v3/projects/7",
        "https://op.example.com:8443/api/v3/projects/7",
        "https://[::1]/api/v3/projects/7",
        "https://[::1/api/v3/projects/7",
        "//evil.example.com/api/v3/projects/7",
        "https://user@op.example.com/api/v3/projects/7",
        "/api/v3/projects/7;x",
        "/api/v3/projects/7?x=1",
        "/api/v3/projects/7?",
        "/api/v3/projects/7#x",
        "/api/v3/projects/7/",
        "/api/v3/projects/7/versions",
        "/api/v3/projects/../users/7",
        "/api/v3/./projects/7",
        "/x/../api/v3/projects/7",
        "/./api/v3/projects/7",
        "/API/v3/projects/7",
        "/api/v3/users/7",
        "/api/v3/projects/demo",
        "/api/v3/projects/007",
        "/api/v3/projects/0",
        "/api/v3/projects/٧",
        "/api/v3/projects/9223372036854775808",
        "/api/v3/projects/%37",
        "/api/v3/proj\tects/7",
        "/api/v3/projects/7\n",
        "\x01/api/v3/projects/7",
        "api/v3/projects/7",
        "urn:openproject-org:api:v3:undisclosed",
    ],
)
def test_parse_project_href_rejects_everything_else(href: object) -> None:
    assert scope.parse_project_href(href, settings=_instance()) is None


@pytest.mark.parametrize(
    ("base_url", "href", "emitted"),
    [
        ("https://op.example.com/openproject", "/api/v3/projects/7", "/api/v3/"),
        ("https://op.example.com", "/openproject/api/v3/projects/7", "/openproject/api/v3/"),
        ("https://op.example.com", "https://op.example.com/op/api/v3/projects/7", "/op/api/v3/"),
        ("https://op.example.com", "/api/api/v3/projects/7", "/api/api/v3/"),
    ],
)
def test_parse_project_href_reports_a_project_link_under_another_root_path(
    base_url: str, href: str, emitted: str
) -> None:
    assert scope.parse_project_href(href, settings=_instance(base_url=base_url)) == scope.PrefixMismatch(emitted)


def test_a_foreign_origin_is_malformed_not_a_prefix_mismatch() -> None:
    settings = _instance()
    link = {"href": "https://evil.example.com/openproject/api/v3/projects/7"}

    assert scope.classify_project_link(link, settings=settings) is scope.LinkState.MALFORMED


_CONTRACTS = [
    (scope.ensure_project_link_allowed, "read"),
    (scope.ensure_project_write_link_allowed, "write"),
    (scope.ensure_project_link_allowed_if_present, "read"),
    (scope.ensure_project_write_link_allowed_if_present, "write"),
]


@pytest.mark.parametrize(("ensure", "kind"), _CONTRACTS)
@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example.com/api/v3/projects/7",
        "/api/v3/users/7",
        "/api/v3/projects/7/versions",
        "/api/v3/projects/demo",
    ],
)
@pytest.mark.parametrize("allowlist", [("*",), ("7",), ("demo",)])
def test_every_contract_denies_a_link_that_is_no_project_link_of_this_instance(
    ensure, kind: str, href: str, allowlist: tuple[str, ...]
) -> None:
    settings = _instance(read=allowlist, write=allowlist)

    with pytest.raises(PermissionDeniedError):
        ensure({"href": href, "title": "demo"}, settings=settings, project_id_to_identifier={7: "demo"})


@pytest.mark.parametrize(("ensure", "kind"), _CONTRACTS)
@pytest.mark.parametrize("allowlist", [("*",), ("7",), ("demo",)])
def test_every_contract_allows_a_project_link_of_this_instance(ensure, kind: str, allowlist: tuple[str, ...]) -> None:
    settings = _instance(read=allowlist, write=allowlist)

    ensure({"href": "/api/v3/projects/7", "title": "Demo"}, settings=settings, project_id_to_identifier={7: "demo"})


@pytest.mark.parametrize(("ensure", "kind"), _CONTRACTS)
def test_every_contract_denies_a_project_link_outside_a_restrictive_allowlist(ensure, kind: str) -> None:
    settings = _instance(read=("other",), write=("other",))

    with pytest.raises(PermissionDeniedError):
        ensure({"href": "/api/v3/projects/7", "title": "Demo"}, settings=settings, project_id_to_identifier={7: "demo"})


@pytest.mark.parametrize(("ensure", "kind"), _CONTRACTS)
def test_every_contract_raises_a_configuration_error_for_a_link_under_another_root_path(ensure, kind: str) -> None:
    settings = _instance(base_url="https://op.example.com/openproject")

    with pytest.raises(ProjectLinkPrefixError, match="/api/v3/.*/openproject/api/v3/"):
        ensure({"href": "/api/v3/projects/7"}, settings=settings, project_id_to_identifier={})


def test_payload_allowed_lets_a_configuration_error_through() -> None:
    settings = _instance(base_url="https://op.example.com/openproject")

    with pytest.raises(ProjectLinkPrefixError):
        scope.payload_allowed(
            lambda: scope.ensure_project_link_allowed(
                {"href": "/api/v3/projects/7"}, settings=settings, project_id_to_identifier={}
            )
        )


def test_project_candidates_take_the_id_from_the_parser_only() -> None:
    candidates = scope.project_candidates(
        settings=_instance(), project_id_to_identifier={}, link={"href": "https://evil.example.com/api/v3/users/7"}
    )

    assert candidates == set()


def _embedded(project_id: int, self_href: object) -> dict:
    return {"id": project_id, "identifier": "demo", "name": "Demo", "_links": {"self": {"href": self_href}}}


def test_an_embedded_project_naming_its_own_id_is_consistent() -> None:
    scope.ensure_embedded_project_consistent(
        _embedded(7, "/api/v3/projects/7"), link={"href": "/api/v3/projects/7"}, settings=_instance()
    )


@pytest.mark.parametrize(
    ("self_href", "link"),
    [
        ("/api/v3/projects/8", None),
        ("https://evil.example.com/api/v3/projects/7", None),
        (None, None),
        ("/api/v3/projects/7", {"href": "/api/v3/projects/8"}),
        ("/api/v3/projects/7", {"href": "https://evil.example.com/api/v3/projects/7"}),
    ],
)
def test_an_embedded_project_whose_links_name_another_project_is_denied(self_href, link) -> None:
    with pytest.raises(PermissionDeniedError):
        scope.ensure_embedded_project_consistent(_embedded(7, self_href), link=link, settings=_instance())


def test_a_project_link_is_read_under_the_instances_own_prefix_first() -> None:
    settings = _instance(base_url="https://op.example.com/api")

    assert scope.parse_project_href("/api/api/v3/projects/7", settings=settings) == scope.LinkedProject(7)
    assert scope.parse_project_href("/api/v3/projects/7", settings=settings) == scope.PrefixMismatch("/api/v3/")
