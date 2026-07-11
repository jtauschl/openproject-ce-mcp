"""Architecture tests for the OPM-123 tool classification in tools.py.

These are structural/name-based invariants over the classification constants
(READ_TOOLS_BY_SCOPE, WRITE_TOOLS_BY_SCOPE, PERSONAL_*, ADMIN_WRITE_TOOLS,
METADATA_TOOLS, ADDITIONAL_READ_SCOPES_BY_TOOL) and over enabled_tool_names().

Expectations are computed independently from the classification constants,
never by calling enabled_tool_names() as its own oracle — otherwise a bug in
the selection logic could compare itself to itself and stay green.
"""

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
}
ALL_READ_ON = {
    "enable_project_read": True,
    "enable_work_package_read": True,
    "enable_membership_read": True,
    "enable_version_read": True,
    "enable_board_read": True,
}


# ── Structural invariants over the raw constants (no Settings involved) ────


def test_classification_tuples_are_duplicate_free() -> None:
    for scope, names in tools.READ_TOOLS_BY_SCOPE.items():
        assert len(names) == len(set(names)), f"duplicate in READ_TOOLS_BY_SCOPE[{scope!r}]"
    for scope, names in tools.WRITE_TOOLS_BY_SCOPE.items():
        assert len(names) == len(set(names)), f"duplicate in WRITE_TOOLS_BY_SCOPE[{scope!r}]"
    assert len(tools.PERSONAL_READ_TOOLS) == len(set(tools.PERSONAL_READ_TOOLS))
    assert len(tools.PERSONAL_MUTATION_TOOLS) == len(set(tools.PERSONAL_MUTATION_TOOLS))
    assert len(tools.ADMIN_WRITE_TOOLS) == len(set(tools.ADMIN_WRITE_TOOLS))
    assert len(tools.METADATA_TOOLS) == len(set(tools.METADATA_TOOLS))


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
    # (read XOR write), never both.
    read_classified = (
        set().union(*tools.READ_TOOLS_BY_SCOPE.values()) | set(tools.PERSONAL_READ_TOOLS) | set(tools.METADATA_TOOLS)
    )
    write_classified = (
        set().union(*tools.WRITE_TOOLS_BY_SCOPE.values())
        | set(tools.ADMIN_WRITE_TOOLS)
        | set(tools.PERSONAL_MUTATION_TOOLS)
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
        set(tools.PERSONAL_READ_TOOLS)
        | set(tools.PERSONAL_MUTATION_TOOLS)
        | set().union(*tools.READ_TOOLS_BY_SCOPE.values())
        | set().union(*tools.WRITE_TOOLS_BY_SCOPE.values())
        | set(tools.ADMIN_WRITE_TOOLS)
        | set(tools.METADATA_TOOLS)
    )
    assert all_classified == set(tools._TOOL_FUNCTIONS)


# ── enabled_tool_names() behavior ───────────────────────────────────────────


def test_enabled_tool_names_is_duplicate_free_and_ordered() -> None:
    names = tools.enabled_tool_names(make_settings())
    assert len(names) == len(set(names))
    assert isinstance(names, tuple)


def test_default_settings_include_get_my_preferences_and_update_my_preferences() -> None:
    names = set(tools.enabled_tool_names(make_settings()))
    assert "get_my_preferences" in names
    assert "update_my_preferences" in names


def test_all_reads_off_removes_every_read_classified_tool() -> None:
    names = set(tools.enabled_tool_names(make_settings(**ALL_READ_OFF)))
    read_classified = set().union(*tools.READ_TOOLS_BY_SCOPE.values())
    assert read_classified.isdisjoint(names)
    # Personal read tool is unaffected by any scope flag.
    assert "get_my_preferences" in names


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


def test_write_delta_uses_all_reads_on_baseline() -> None:
    """Write-group delta tests must start from all reads ON, all writes OFF —
    otherwise tools with an additional read requirement (e.g. create_membership)
    would make the observed delta smaller than WRITE_TOOLS_BY_SCOPE[scope]."""
    baseline = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON)))
    with_membership_write = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON, enable_membership_write=True)))
    delta = with_membership_write - baseline
    assert delta == set(tools.WRITE_TOOLS_BY_SCOPE["membership"])


def test_admin_write_toggle_is_independent() -> None:
    without = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON)))
    with_admin = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON, enable_admin_write=True)))
    assert with_admin - without == set(tools.ADMIN_WRITE_TOOLS)


def test_metadata_tools_need_their_additional_read_scopes_too() -> None:
    # All reads on: all 12 metadata tools appear.
    full = set(tools.enabled_tool_names(make_settings(**ALL_READ_ON, enable_metadata_tools=True)))
    assert set(tools.METADATA_TOOLS) <= full

    # Board+work_package read off: the 7 dependent metadata tools disappear,
    # the other 5 (no additional scope) remain.
    partial = set(
        tools.enabled_tool_names(
            make_settings(
                **{**ALL_READ_ON, "enable_board_read": False, "enable_work_package_read": False},
                enable_metadata_tools=True,
            )
        )
    )
    dependent = {name for name in tools.METADATA_TOOLS if name in tools.ADDITIONAL_READ_SCOPES_BY_TOOL}
    independent = set(tools.METADATA_TOOLS) - dependent
    assert dependent.isdisjoint(partial)
    assert independent <= partial


def test_read_enabled_unknown_scope_raises_not_silently_allows() -> None:
    # Guards the fail-closed contract this whole classification depends on.
    settings = make_settings()
    try:
        settings.read_enabled("not-a-real-scope")
    except ConfigError:
        pass
    else:
        raise AssertionError("expected ConfigError for an unknown scope")
