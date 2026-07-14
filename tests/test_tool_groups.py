"""Architecture tests for the OPM-123/OPM-126 tool classification in tools.py.

These are structural/name-based invariants over the classification constants
(READ_TOOLS_BY_SCOPE — including the "personal"/"extended" groups added by
OPM-126 — WRITE_TOOLS_BY_SCOPE, PERSONAL_MUTATION_TOOLS, ADMIN_WRITE_TOOLS,
ADDITIONAL_READ_SCOPES_BY_TOOL) and over enabled_tool_names().

Expectations are computed independently from the classification constants,
never by calling enabled_tool_names() as its own oracle — otherwise a bug in
the selection logic could compare itself to itself and stay green.
"""

import inspect

import pytest

from openproject_ce_mcp import tools
from openproject_ce_mcp.config import ConfigError, Settings


def make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
    }
    defaults.update(overrides)
    return Settings(**defaults)


ALL_READ_OFF = {
    "enable_project_read": False,
    "enable_work_package_read": False,
    "enable_membership_read": False,
    "enable_version_read": False,
    "enable_board_read": False,
    "enable_personal_read": False,
}
ALL_READ_ON = {
    "enable_project_read": True,
    "enable_work_package_read": True,
    "enable_membership_read": True,
    "enable_version_read": True,
    "enable_board_read": True,
    "enable_personal_read": True,
}
# The 5 project-scoped write flags now default True on the Settings dataclass
# itself (direct Settings(**kwargs) construction, unlike Settings.from_env,
# never validates that combination) — write-delta tests need an explicit
# all-off baseline to observe a real delta.
ALL_WRITE_OFF = {
    "enable_project_write": False,
    "enable_work_package_write": False,
    "enable_membership_write": False,
    "enable_version_write": False,
    "enable_board_write": False,
}


# ── Structural invariants over the raw constants (no Settings involved) ────


def test_classification_tuples_are_duplicate_free() -> None:
    for scope, names in tools.READ_TOOLS_BY_SCOPE.items():
        assert len(names) == len(set(names)), f"duplicate in READ_TOOLS_BY_SCOPE[{scope!r}]"
    for scope, names in tools.WRITE_TOOLS_BY_SCOPE.items():
        assert len(names) == len(set(names)), f"duplicate in WRITE_TOOLS_BY_SCOPE[{scope!r}]"
    assert len(tools.PERSONAL_MUTATION_TOOLS) == len(set(tools.PERSONAL_MUTATION_TOOLS))
    assert len(tools.ADMIN_WRITE_TOOLS) == len(set(tools.ADMIN_WRITE_TOOLS))


def test_no_tool_in_two_different_read_scopes() -> None:
    seen: dict[str, str] = {}
    for scope, names in tools.READ_TOOLS_BY_SCOPE.items():
        for name in names:
            assert name not in seen, f"{name} is in both {seen.get(name)!r} and {scope!r}"
            seen[name] = scope


def test_no_tool_in_two_different_write_scopes() -> None:
    seen: dict[str, str] = {}
    for scope, names in tools.WRITE_TOOLS_BY_SCOPE.items():
        for name in names:
            assert name not in seen, f"{name} is in both {seen.get(name)!r} and {scope!r}"
            seen[name] = scope


def test_read_and_write_classifications_are_disjoint() -> None:
    # Formal invariant: every tool has exactly one registration direction
    # (read XOR write), never both. READ_TOOLS_BY_SCOPE now includes
    # "personal" and "extended" as ordinary groups, so no separate union is
    # needed for their former, now-deleted dedicated read-only constants.
    read_classified = set().union(*tools.READ_TOOLS_BY_SCOPE.values())
    write_classified = (
        set().union(*tools.WRITE_TOOLS_BY_SCOPE.values())
        | set(tools.ADMIN_WRITE_TOOLS)
        | set(tools.PERSONAL_MUTATION_TOOLS)
        | set(tools.ATTACHMENT_UPLOAD_TOOLS)
    )
    assert read_classified.isdisjoint(write_classified), read_classified & write_classified


def test_additional_read_scopes_never_repeat_the_tools_own_home_scope() -> None:
    home_scope_by_tool: dict[str, str] = {}
    for scope, names in tools.READ_TOOLS_BY_SCOPE.items():
        for name in names:
            home_scope_by_tool[name] = scope
    for name, extra_scopes in tools.ADDITIONAL_READ_SCOPES_BY_TOOL.items():
        home = home_scope_by_tool.get(name)
        if home is not None:
            assert home not in extra_scopes, f"{name}: additional scope {home!r} duplicates its own read home"


def test_every_classified_scope_string_is_known_to_settings() -> None:
    settings = make_settings()
    for scope in tools.READ_TOOLS_BY_SCOPE:
        settings.read_enabled(scope)  # must not raise ConfigError
    for scope in tools.WRITE_TOOLS_BY_SCOPE:
        settings.write_enabled(scope)  # must not raise ConfigError
    for extra_scopes in tools.ADDITIONAL_READ_SCOPES_BY_TOOL.values():
        for scope in extra_scopes:
            settings.read_enabled(scope)  # must not raise ConfigError


def test_every_classified_name_resolves_to_a_real_function() -> None:
    # _TOOL_FUNCTIONS is built via globals()[name] over the classification
    # constants at import time — if this test file can import `tools` at
    # all, every classified name already resolved (a bad name would have
    # raised KeyError at module load). This test locks that invariant in
    # explicitly rather than relying on import success alone.
    all_classified = (
        set(tools.PERSONAL_MUTATION_TOOLS)
        | set(tools.ATTACHMENT_UPLOAD_TOOLS)
        | set().union(*tools.READ_TOOLS_BY_SCOPE.values())
        | set().union(*tools.WRITE_TOOLS_BY_SCOPE.values())
        | set(tools.ADMIN_WRITE_TOOLS)
    )
    assert all_classified == set(tools._TOOL_FUNCTIONS)


def test_every_write_tool_requires_confirm() -> None:
    """Signature invariant: every write tool must take a confirm parameter that
    defaults to False. Does NOT prove confirm is passed through to the client or
    that confirm=False actually withholds the mutation — those are covered by the
    targeted wrapper/client behavior tests instead."""
    write_tool_names = (
        set().union(*tools.WRITE_TOOLS_BY_SCOPE.values())
        | set(tools.ADMIN_WRITE_TOOLS)
        | set(tools.PERSONAL_MUTATION_TOOLS)
        | set(tools.ATTACHMENT_UPLOAD_TOOLS)
    )
    for name in write_tool_names:
        sig = inspect.signature(tools._TOOL_FUNCTIONS[name])
        assert "confirm" in sig.parameters, f"{name} has no confirm parameter"
        assert sig.parameters["confirm"].default is False, f"{name}'s confirm must default to False"


# ── enabled_tool_names() behavior ───────────────────────────────────────────


def test_enabled_tool_names_is_duplicate_free_and_ordered() -> None:
    names = tools.enabled_tool_names(make_settings())
    assert len(names) == len(set(names))
    assert isinstance(names, tuple)


def test_default_settings_exclude_personal_tools() -> None:
    # OPM-126: "personal" is opt-in only, not part of the compatible unset
    # default — unlike OPM-123, where get_my_preferences was unconditional.
    names = set(tools.enabled_tool_names(make_settings()))
    assert "get_my_preferences" not in names
    assert "list_notifications" not in names
    assert "update_my_preferences" not in names


def test_personal_group_and_write_flag_expose_personal_tools() -> None:
    names = set(tools.enabled_tool_names(make_settings(enable_personal_read=True, enable_personal_write=True)))
    assert "get_my_preferences" in names
    assert "list_notifications" in names
    assert "update_my_preferences" in names
    assert "mark_notification_read" in names
    assert "mark_all_notifications_read" in names


def test_all_reads_off_removes_every_read_classified_tool() -> None:
    names = set(tools.enabled_tool_names(make_settings(**ALL_READ_OFF)))
    read_classified = set().union(*tools.READ_TOOLS_BY_SCOPE.values())
    assert read_classified.isdisjoint(names)


def test_membership_read_false_removes_home_group_plus_dependent_tools() -> None:
    """The delta is NOT just READ_TOOLS_BY_SCOPE['membership'] — tools whose
    home group is elsewhere but that additionally require membership read
    (e.g. get_my_project_access, home: project) disappear too, while tools
    with no such dependency stay untouched."""
    default = set(tools.enabled_tool_names(make_settings()))
    without_membership = set(tools.enabled_tool_names(make_settings(enable_membership_read=False)))
    removed = default - without_membership

    assert set(tools.READ_TOOLS_BY_SCOPE["membership"]) <= removed
    assert "get_my_project_access" in removed  # project-home, but needs membership too

    assert "list_projects" not in removed
    assert "list_work_packages" not in removed
    assert "list_versions" not in removed
    assert "list_boards" not in removed


def test_single_read_group_active_still_hides_compound_scope_tools() -> None:
    """Only 'project' read active: get_my_project_access (needs membership too) and
    get_project_work_package_context (needs work_package+version too) stay hidden,
    even though their home group is on."""
    names = set(
        tools.enabled_tool_names(
            make_settings(
                enable_project_read=True,
                enable_work_package_read=False,
                enable_membership_read=False,
                enable_version_read=False,
                enable_board_read=False,
            )
        )
    )
    assert "list_projects" in names
    assert "get_my_project_access" not in names
    assert "get_project_work_package_context" not in names


def test_admin_read_default_false_hides_admin_tools() -> None:
    # list_principals/list_users/get_user/list_groups/get_group moved out of
    # "membership" (default true) into "admin" (default false) — instance-wide
    # PII (name/login/email) must not be visible without explicit opt-in.
    names = set(tools.enabled_tool_names(make_settings()))
    assert set(tools.READ_TOOLS_BY_SCOPE["admin"]).isdisjoint(names)
    # get_current_user/get_my_project_access are unaffected — they stay under
    # "membership" and remain visible by default.
    assert "get_current_user" in names


def test_admin_read_true_exposes_admin_tools() -> None:
    names = set(tools.enabled_tool_names(make_settings(enable_admin_read=True)))
    assert set(tools.READ_TOOLS_BY_SCOPE["admin"]) <= names


def test_write_delta_uses_all_reads_on_baseline() -> None:
    """Write-group delta tests must start from all reads ON, all writes OFF —
    otherwise tools with an additional read requirement (e.g. create_membership)
    would make the observed delta smaller than WRITE_TOOLS_BY_SCOPE[scope]."""
    # Project-scoped write tools also require both project allowlists non-empty
    # to be registered at all (see _PROJECT_SCOPED_WRITE_SCOPES in tools.py).
    baseline = set(
        tools.enabled_tool_names(
            make_settings(**ALL_READ_ON, **ALL_WRITE_OFF, read_projects=("*",), write_projects=("*",))
        )
    )
    with_membership_write = set(
        tools.enabled_tool_names(
            make_settings(
                **ALL_READ_ON,
                **{**ALL_WRITE_OFF, "enable_membership_write": True},
                read_projects=("*",),
                write_projects=("*",),
            )
        )
    )
    delta = with_membership_write - baseline
    assert delta == set(tools.WRITE_TOOLS_BY_SCOPE["membership"])


def test_admin_write_toggle_is_independent() -> None:
    # admin_write requires its own admin_read (like every other write flag
    # requires its matching read) — pass it explicitly on both sides so this
    # doesn't codify a combination Settings.from_env would reject at startup.
    without = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON, enable_admin_read=True)))
    with_admin = set(
        tools.enabled_tool_names(make_settings(**ALL_READ_ON, enable_admin_read=True, enable_admin_write=True))
    )
    assert with_admin - without == set(tools.ADMIN_WRITE_TOOLS)


def test_metadata_tools_need_their_additional_read_scopes_too() -> None:
    extended_tools = tools.READ_TOOLS_BY_SCOPE["extended"]

    # All reads on: all 12 extended-group tools appear.
    full = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON, enable_metadata_tools=True)))
    assert set(extended_tools) <= full

    # Board+work_package read off: the 7 dependent tools disappear, the other
    # 5 (no additional scope) remain.
    partial = set(
        tools.enabled_tool_names(
            make_settings(
                **{**ALL_READ_ON, "enable_board_read": False, "enable_work_package_read": False},
                enable_metadata_tools=True,
            )
        )
    )
    dependent = {name for name in extended_tools if name in tools.ADDITIONAL_READ_SCOPES_BY_TOOL}
    independent = set(extended_tools) - dependent
    assert dependent.isdisjoint(partial)
    assert independent <= partial


# ── "personal" AND-gate (OPM-126) — NOT the independent read/write pattern ──
#
# Unlike every other scope (see test_write_delta_uses_all_reads_on_baseline /
# test_admin_write_toggle_is_independent, where a write flag alone exposes its
# write tools regardless of the paired read flag), "personal" mutations need
# BOTH enable_personal_read AND enable_personal_write. There is deliberately
# no test_all_scoped_writes_independent-style analogue here — that would
# misrepresent the AND-gate as an independent toggle.


def test_personal_write_alone_does_not_expose_personal_mutations() -> None:
    names = set(tools.enabled_tool_names(make_settings(**ALL_READ_OFF, enable_personal_write=True)))
    assert "update_my_preferences" not in names
    assert "mark_notification_read" not in names
    assert "mark_all_notifications_read" not in names


def test_personal_read_alone_exposes_reads_but_not_mutations() -> None:
    only_personal_read = {**ALL_READ_OFF, "enable_personal_read": True}
    names = set(tools.enabled_tool_names(make_settings(**only_personal_read)))
    assert "get_my_preferences" in names
    assert "list_notifications" in names
    assert "update_my_preferences" not in names
    assert "mark_notification_read" not in names
    assert "mark_all_notifications_read" not in names


def test_work_package_write_no_longer_couples_to_notification_mark_read() -> None:
    baseline = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON)))
    with_wp_write = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON, enable_work_package_write=True)))
    delta = with_wp_write - baseline
    assert "mark_notification_read" not in delta
    assert "mark_all_notifications_read" not in delta


# ── attachment-upload AND-gate (OPM-127) — same bespoke-branch shape as the
# "personal" AND-gate above, but scope-flag AND a non-empty config string,
# not scope-flag AND scope-flag.


def test_work_package_write_alone_does_not_expose_attachment_upload() -> None:
    names = set(tools.enabled_tool_names(make_settings(enable_work_package_write=True)))
    assert "create_work_package_attachment" not in names


def test_attachment_root_alone_does_not_expose_upload_without_write() -> None:
    names = set(tools.enabled_tool_names(make_settings(attachment_root="/tmp/uploads")))
    assert "create_work_package_attachment" not in names


def test_work_package_write_and_attachment_root_expose_upload() -> None:
    names = set(
        tools.enabled_tool_names(
            make_settings(
                enable_work_package_write=True,
                attachment_root="/tmp/uploads",
                read_projects=("*",),
                write_projects=("*",),
            )
        )
    )
    assert "create_work_package_attachment" in names
    assert "create_work_package" in names  # other wp-write tools unaffected


# ── project-scope write-visibility gate — a project-scoped write category is
# registered only when BOTH OPENPROJECT_READ_PROJECTS and
# OPENPROJECT_WRITE_PROJECTS are non-empty, not just OPENPROJECT_WRITE_PROJECTS
# alone (a lone WRITE_PROJECTS would register tools that always fail at
# runtime, since _ensure_project_write_allowed checks READ_PROJECTS first).


@pytest.mark.parametrize("scope", ["project", "work_package", "membership", "version", "board"])
def test_project_scoped_write_tools_need_both_allowlists_non_empty(scope: str) -> None:
    write_flag = f"enable_{scope}_write"

    neither = tools.enabled_tool_names(make_settings(**ALL_READ_ON, **{write_flag: True}))
    only_read = tools.enabled_tool_names(make_settings(**ALL_READ_ON, **{write_flag: True}, read_projects=("*",)))
    only_write = tools.enabled_tool_names(make_settings(**ALL_READ_ON, **{write_flag: True}, write_projects=("*",)))
    both = tools.enabled_tool_names(
        make_settings(**ALL_READ_ON, **{write_flag: True}, read_projects=("*",), write_projects=("*",))
    )

    scoped_tools = set(tools.WRITE_TOOLS_BY_SCOPE[scope])
    assert scoped_tools.isdisjoint(neither)
    assert scoped_tools.isdisjoint(only_read)
    assert scoped_tools.isdisjoint(only_write)
    assert scoped_tools <= set(both)


def test_read_enabled_unknown_scope_raises_not_silently_allows() -> None:
    # Guards the fail-closed contract this whole classification depends on.
    settings = make_settings()
    try:
        settings.read_enabled("not-a-real-scope")
    except ConfigError:
        pass
    else:
        raise AssertionError("expected ConfigError for an unknown scope")
