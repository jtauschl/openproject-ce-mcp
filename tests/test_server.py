"""Tests for dynamic tool registration in create_app()."""

import pytest

import openproject_ce_mcp.server as server
from openproject_ce_mcp import __version__
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app


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


def _tool_names(mcp) -> set[str]:
    return {t.name for t in mcp._tool_manager.list_tools()}


def test_defaults_contain_read_tools() -> None:
    mcp = create_app(make_settings())
    names = _tool_names(mcp)
    assert "list_projects" in names
    assert "list_work_packages" in names
    assert "list_boards" in names
    assert "list_versions" in names
    assert "list_project_memberships" in names


def test_defaults_no_write_tools() -> None:
    mcp = create_app(make_settings())
    names = _tool_names(mcp)
    assert "create_project" not in names
    assert "update_work_package" not in names
    assert "delete_board" not in names
    assert "create_user" not in names
    assert "mark_notification_read" not in names


def test_update_my_preferences_always_available() -> None:
    """update_my_preferences is in the read block — available without any write flag."""
    mcp = create_app(make_settings())
    names = _tool_names(mcp)
    assert "update_my_preferences" in names


def test_enable_project_read_false_removes_project_tools() -> None:
    mcp = create_app(make_settings(enable_project_read=False))
    names = _tool_names(mcp)
    assert "list_projects" not in names
    assert "get_project" not in names
    # Other scopes remain active
    assert "list_work_packages" in names
    assert "list_boards" in names


def test_enable_work_package_read_false_removes_wp_tools() -> None:
    mcp = create_app(make_settings(enable_work_package_read=False))
    names = _tool_names(mcp)
    assert "list_work_packages" not in names
    assert "get_work_package" not in names
    assert "search_work_packages" not in names
    # Other scopes remain active
    assert "list_projects" in names


def test_enable_board_read_false_removes_board_read_tools() -> None:
    mcp = create_app(make_settings(enable_board_read=False))
    names = _tool_names(mcp)
    assert "list_boards" not in names
    assert "get_board" not in names


def test_enable_version_read_false_removes_version_read_tools() -> None:
    mcp = create_app(make_settings(enable_version_read=False))
    names = _tool_names(mcp)
    assert "list_versions" not in names
    assert "get_version" not in names


def test_enable_membership_read_false_removes_membership_tools() -> None:
    mcp = create_app(make_settings(enable_membership_read=False))
    names = _tool_names(mcp)
    assert "list_project_memberships" not in names
    assert "list_roles" not in names
    assert "list_users" not in names


def test_enable_work_package_write_adds_wp_write_tools() -> None:
    mcp = create_app(make_settings(enable_work_package_write=True))
    names = _tool_names(mcp)
    assert "create_work_package" in names
    assert "update_work_package" in names
    assert "delete_work_package" in names
    assert "create_time_entry" in names
    assert "mark_notification_read" in names
    assert "update_relation" in names
    assert "delete_file_link" in names
    # Other write scopes remain locked
    assert "create_project" not in names
    assert "create_board" not in names
    assert "create_news" not in names


def test_enable_board_write_adds_board_write_tools() -> None:
    mcp = create_app(make_settings(enable_board_write=True))
    names = _tool_names(mcp)
    assert "create_board" in names
    assert "update_board" in names
    assert "delete_board" in names
    assert "create_work_package" not in names


def test_enable_project_write_adds_project_write_tools() -> None:
    mcp = create_app(make_settings(enable_project_write=True))
    names = _tool_names(mcp)
    assert "create_project" in names
    assert "create_news" in names
    assert "update_document" in names
    assert "create_grid" in names
    assert "create_time_entry" not in names
    assert "create_user" not in names


def test_enable_admin_write_adds_user_group_tools() -> None:
    mcp = create_app(make_settings(enable_admin_write=True))
    names = _tool_names(mcp)
    assert "create_user" in names
    assert "update_user" in names
    assert "delete_user" in names
    assert "lock_user" in names
    assert "unlock_user" in names
    assert "create_group" in names
    assert "update_group" in names
    assert "delete_group" in names


def test_admin_tools_absent_without_enable_admin_write() -> None:
    """All project-scoped write flags enabled — admin tools must still be absent."""
    mcp = create_app(
        make_settings(
            enable_project_write=True,
            enable_work_package_write=True,
            enable_membership_write=True,
            enable_version_write=True,
            enable_board_write=True,
        )
    )
    names = _tool_names(mcp)
    assert "create_user" not in names
    assert "delete_user" not in names
    assert "create_group" not in names
    assert "delete_group" not in names


_METADATA_TOOLS = {
    "get_query_filter",
    "get_query_column",
    "get_query_operator",
    "get_query_sort_by",
    "list_query_filter_instance_schemas",
    "get_query_filter_instance_schema",
    "render_text",
    "list_help_texts",
    "get_help_text",
    "list_working_days",
    "list_non_working_days",
    "get_custom_option",
}


def test_metadata_tools_absent_by_default() -> None:
    """Rarely-used metadata tools stay out of the default set to save context."""
    mcp = create_app(make_settings())
    names = _tool_names(mcp)
    assert _METADATA_TOOLS.isdisjoint(names), _METADATA_TOOLS & names


def test_enable_metadata_tools_adds_them() -> None:
    mcp = create_app(make_settings(enable_metadata_tools=True))
    names = _tool_names(mcp)
    assert _METADATA_TOOLS <= names, _METADATA_TOOLS - names


def test_all_scoped_writes_independent() -> None:
    """Each scoped write flag activates exactly its own tools."""
    for flag, expected_tool in [
        ("enable_project_write", "create_project"),
        ("enable_work_package_write", "create_work_package"),
        ("enable_membership_write", "create_membership"),
        ("enable_version_write", "create_version"),
        ("enable_board_write", "create_board"),
        ("enable_admin_write", "create_user"),
    ]:
        mcp = create_app(make_settings(**{flag: True}))
        names = _tool_names(mcp)
        assert expected_tool in names, f"{expected_tool} missing when {flag}=True"


# ── server instructions & handshake metadata ──────────────────────────────────


def test_instructions_state_ce_reality() -> None:
    """The initialize handshake carries the CE guidance the agent needs up front."""
    mcp = create_app(make_settings())
    instructions = mcp._mcp_server.instructions or ""
    assert "Community Edition" in instructions
    # The two hard limits we most want the agent to know:
    assert "do not attempt" in instructions.lower() or "not creatable" in instructions.lower()
    assert "list_capabilities" in instructions


def test_serverinfo_version_is_our_version() -> None:
    """serverInfo.version (MCP MUST) reports our package version, not the SDK default."""
    mcp = create_app(make_settings())
    assert mcp._mcp_server.version == __version__


def test_create_app_applies_log_level(monkeypatch) -> None:
    """OPENPROJECT_LOG_LEVEL takes effect: create_app forces the root level so
    FastMCP's default INFO does not leak SDK request logs (OPM-62)."""
    import logging

    root = logging.getLogger()
    original_level = root.level
    # Simulate a handler already installed at INFO (as FastMCP does on construction),
    # which makes basicConfig a no-op — the exact condition of the bug.
    root.setLevel(logging.INFO)
    try:
        create_app(make_settings(log_level="WARNING"))
        assert root.getEffectiveLevel() == logging.WARNING
        assert not logging.getLogger("mcp.server.lowlevel.server").isEnabledFor(logging.INFO)
    finally:
        root.setLevel(original_level)


@pytest.mark.allow_feature_flag_fetch
def test_fetch_active_feature_flags_swallows_errors(monkeypatch) -> None:
    """A failing instance fetch returns None instead of raising — startup stays safe."""

    async def _boom(self):
        raise RuntimeError("instance unreachable")

    monkeypatch.setattr(server.OpenProjectClient, "get_instance_configuration", _boom)
    assert server._fetch_active_feature_flags(make_settings()) is None


def test_instructions_fall_back_to_static_without_flags() -> None:
    """With no reachable flags (autouse offline stub) instructions are exactly the static text."""
    mcp = create_app(make_settings())
    assert mcp._mcp_server.instructions == server.CE_INSTRUCTIONS


@pytest.mark.allow_feature_flag_fetch
def test_instructions_include_live_feature_flags(monkeypatch) -> None:
    """When the instance is reachable, its active feature flags are appended."""
    monkeypatch.setattr(
        server,
        "_fetch_active_feature_flags",
        lambda settings: ["boardView", "teamPlannerModuleActive"],
    )
    mcp = create_app(make_settings())
    instructions = mcp._mcp_server.instructions or ""
    assert "Active feature flags on this instance" in instructions
    assert "boardView" in instructions
    assert "teamPlannerModuleActive" in instructions


# ── console entry-point dispatch ───────────────────────────────────────────────


def test_main_no_args_runs_server(monkeypatch) -> None:
    import openproject_ce_mcp.server as srv

    ran = []
    monkeypatch.setattr(srv, "_run_server", lambda: ran.append(True))
    monkeypatch.setattr(srv.sys, "argv", ["openproject-ce-mcp"])
    srv.main()
    assert ran == [True]


def test_main_configure_dispatches_to_setup(monkeypatch) -> None:
    import openproject_ce_mcp.server as srv
    import openproject_ce_mcp.setup_cli as setup_cli

    forwarded = []
    monkeypatch.setattr(setup_cli, "main", lambda argv: forwarded.append(argv))
    monkeypatch.setattr(srv, "_run_server", lambda: forwarded.append("SERVER"))
    monkeypatch.setattr(srv.sys, "argv", ["openproject-ce-mcp", "configure", "--uninstall"])
    srv.main()
    assert forwarded == [["--uninstall"]]


def test_main_unexpected_flag_still_runs_server(monkeypatch) -> None:
    # A client passing an unknown flag must start the server, not error out.
    import openproject_ce_mcp.server as srv

    ran = []
    monkeypatch.setattr(srv, "_run_server", lambda: ran.append(True))
    monkeypatch.setattr(srv.sys, "argv", ["openproject-ce-mcp", "--some-client-flag"])
    srv.main()
    assert ran == [True]


def test_main_help_exits_without_server(monkeypatch, capsys) -> None:
    import openproject_ce_mcp.server as srv

    monkeypatch.setattr(srv, "_run_server", lambda: (_ for _ in ()).throw(AssertionError("server ran")))
    monkeypatch.setattr(srv.sys, "argv", ["openproject-ce-mcp", "--help"])
    try:
        srv.main()
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert "configure" in out and "usage:" in out


def test_main_version_prints_version(monkeypatch, capsys) -> None:
    import openproject_ce_mcp.server as srv
    from openproject_ce_mcp import __version__

    monkeypatch.setattr(srv.sys, "argv", ["openproject-ce-mcp", "--version"])
    try:
        srv.main()
    except SystemExit as exc:
        assert exc.code == 0
    assert __version__ in capsys.readouterr().out


def test_main_doctor_help_prints_help_not_runs_checks(monkeypatch, capsys) -> None:
    """Regression test: doctor --help should show help, not run diagnostics."""
    import openproject_ce_mcp.server as srv

    monkeypatch.setattr(srv.sys, "argv", ["openproject-ce-mcp", "doctor", "--help"])
    try:
        srv.main()
    except SystemExit as exc:
        assert exc.code == 0

    out = capsys.readouterr().out
    # Should show argparse help for doctor subcommand
    assert "usage:" in out
    assert "doctor" in out
    # Should NOT run actual diagnostics
    assert "Running OpenProject MCP diagnostics" not in out
    assert "[OK]" not in out
    assert "[FAIL]" not in out
