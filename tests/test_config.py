from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openproject_ce_mcp.config import ConfigError, Settings, legacy_env_warnings

# A real absolute path in native format for whichever OS runs the tests
# (e.g. /tmp/uploads on Linux/macOS, C:\Users\...\Temp\uploads on Windows) —
# Path.is_absolute() only recognizes drive-letter/UNC paths as absolute on
# Windows, so a hardcoded POSIX literal like "/tmp/uploads" fails there.
ABSOLUTE_ATTACHMENT_ROOT = str(Path(tempfile.gettempdir()) / "uploads")


def test_settings_from_env_loads_and_normalizes_values() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com/",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_READ_PROJECTS": "mcp-test, openproject-ce-mcp",
            "OPENPROJECT_WRITE_PROJECTS": "mcp-test",
            "OPENPROJECT_TOOLS": "projects,work-packages,versions,boards",
            "OPENPROJECT_HIDE_PROJECT_FIELDS": "description,status_explanation",
            "OPENPROJECT_HIDE_PRINCIPAL_FIELDS": "*mail,login",
            "OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS": "description",
            "OPENPROJECT_HIDE_ACTIVITY_FIELDS": "comment",
            "OPENPROJECT_HIDE_CUSTOM_FIELDS": "budget, internal_notes",
            "OPENPROJECT_ENABLE_PROJECT_WRITE": "true",
            "OPENPROJECT_TIMEOUT": "15",
            "OPENPROJECT_VERIFY_SSL": "false",
            "OPENPROJECT_DEFAULT_PAGE_SIZE": "10",
            "OPENPROJECT_MAX_PAGE_SIZE": "20",
            "OPENPROJECT_MAX_RESULTS": "30",
            "OPENPROJECT_LOG_LEVEL": "info",
        }
    )

    assert settings.base_url == "https://op.example.com"
    assert settings.api_base_url == "https://op.example.com/api/v3"
    assert settings.read_projects == ("mcp-test", "openproject-ce-mcp")
    assert settings.write_projects == ("mcp-test",)
    assert settings.enable_project_read is True
    assert settings.enable_membership_read is False
    assert settings.hide_project_fields == ("description", "status_explanation")
    assert settings.hidden_fields["principal"] == ("*mail", "login")
    assert settings.hide_work_package_fields == ("description",)
    assert settings.hide_activity_fields == ("comment",)
    assert settings.hide_custom_fields == ("budget", "internal_notes")
    assert settings.enable_project_write is True
    assert settings.verify_ssl is False
    assert settings.timeout == 15
    assert settings.default_page_size == 10
    assert settings.max_page_size == 20
    assert settings.max_results == 30
    assert settings.log_level == "INFO"


def test_settings_from_env_rejects_invalid_relationships() -> None:
    with pytest.raises(ConfigError, match="must not exceed"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_DEFAULT_PAGE_SIZE": "60",
                "OPENPROJECT_MAX_PAGE_SIZE": "50",
                "OPENPROJECT_MAX_RESULTS": "100",
            }
        )


def test_settings_from_env_accepts_wildcard_project_scopes() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_READ_PROJECTS": "*",
            "OPENPROJECT_WRITE_PROJECTS": "*",
        }
    )

    assert settings.read_projects == ("*",)
    assert settings.write_projects == ("*",)


def test_settings_from_env_per_scope_read_flag_disables_independently_of_default() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_TOOLS": "projects,work-packages,versions,boards",
        }
    )

    assert settings.read_enabled("project") is True
    assert settings.read_enabled("membership") is False


def test_settings_from_env_scoped_read_flags_disable_chains_independently() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_TOOLS": "memberships",
        }
    )

    assert settings.read_enabled("project") is False
    assert settings.read_enabled("work_package") is False
    assert settings.read_enabled("membership") is True  # not disabled


def test_settings_from_env_scoped_write_flag_enables_one_scope_independently() -> None:
    # writes default to disabled; a scoped flag opts one chain in without affecting others
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "true",
        }
    )

    assert settings.write_enabled("work_package") is True
    assert settings.write_enabled("project") is False
    assert settings.write_enabled("membership") is False


def test_settings_from_env_write_scopes_default_to_disabled() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )

    assert settings.write_enabled("project") is False
    assert settings.write_enabled("work_package") is False
    assert settings.write_enabled("membership") is False


def test_tool_groups_unset_enables_core_five_only() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )

    assert settings.read_enabled("project") is True
    assert settings.read_enabled("work_package") is True
    assert settings.read_enabled("membership") is True
    assert settings.read_enabled("version") is True
    assert settings.read_enabled("board") is True
    assert settings.read_enabled("personal") is False
    assert settings.enable_metadata_tools is False


def test_tool_groups_explicit_empty_string_disables_every_group() -> None:
    # Explicit empty string is a real three-state distinction from "unset" —
    # it means "no tool groups at all", not "use the compatible default".
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_TOOLS": "",
        }
    )

    assert settings.read_enabled("project") is False
    assert settings.read_enabled("work_package") is False
    assert settings.read_enabled("membership") is False
    assert settings.read_enabled("version") is False
    assert settings.read_enabled("board") is False
    assert settings.read_enabled("personal") is False
    assert settings.enable_metadata_tools is False


def test_tool_groups_unknown_name_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown tool group"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_TOOLS": "bogus",
            }
        )


def test_tool_groups_partially_unknown_list_rejected_not_silently_filtered() -> None:
    with pytest.raises(ConfigError, match="unknown tool group"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_TOOLS": "projects,bogus,boards",
            }
        )


@pytest.mark.parametrize(
    ("write_var", "groups_without"),
    [
        ("OPENPROJECT_ENABLE_PROJECT_WRITE", "work-packages,memberships,versions,boards"),
        ("OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE", "projects,memberships,versions,boards"),
        ("OPENPROJECT_ENABLE_MEMBERSHIP_WRITE", "projects,work-packages,versions,boards"),
        ("OPENPROJECT_ENABLE_VERSION_WRITE", "projects,work-packages,memberships,boards"),
        ("OPENPROJECT_ENABLE_BOARD_WRITE", "projects,work-packages,memberships,versions"),
        ("OPENPROJECT_PERSONAL_WRITE", "projects,work-packages,memberships,versions,boards"),
    ],
)
def test_write_flag_without_visible_group_rejected(write_var: str, groups_without: str) -> None:
    with pytest.raises(ConfigError, match="requires"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_TOOLS": groups_without,
                write_var: "true",
            }
        )


def test_write_flag_with_visible_group_accepted() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_TOOLS": "projects,work-packages,memberships,versions,boards,personal",
            "OPENPROJECT_ENABLE_PROJECT_WRITE": "true",
            "OPENPROJECT_PERSONAL_WRITE": "true",
        }
    )

    assert settings.write_enabled("project") is True
    assert settings.write_enabled("personal") is True


def test_read_enabled_rejects_unknown_scope() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )

    with pytest.raises(ConfigError, match="Unknown read scope"):
        settings.read_enabled("bogus")


def test_write_enabled_rejects_unknown_scope() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )

    with pytest.raises(ConfigError, match="Unknown write scope"):
        settings.write_enabled("bogus")


def test_write_enabled_does_not_special_case_admin() -> None:
    # "admin" is intentionally out-of-band: client.py::_ensure_write_enabled
    # and the tool registration gate check settings.enable_admin_write
    # directly, never via write_enabled("admin"). A future edit that tries
    # to route admin through the normal per-scope dict must fail loudly
    # here rather than silently changing admin's semantics.
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_ADMIN_WRITE": "true",
        }
    )

    with pytest.raises(ConfigError, match="Unknown write scope"):
        settings.write_enabled("admin")


def test_settings_from_env_rejects_max_page_size_exceeding_max_results() -> None:
    with pytest.raises(ConfigError, match="must not exceed"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_DEFAULT_PAGE_SIZE": "10",
                "OPENPROJECT_MAX_PAGE_SIZE": "60",
                "OPENPROJECT_MAX_RESULTS": "50",
            }
        )


def test_settings_from_env_rejects_invalid_base_url_scheme() -> None:
    with pytest.raises(ConfigError, match="http or https"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "ftp://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
            }
        )


def test_settings_from_env_rejects_base_url_without_hostname() -> None:
    with pytest.raises(ConfigError, match="hostname"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://",
                "OPENPROJECT_API_TOKEN": "token-value",
            }
        )


def test_settings_from_env_rejects_base_url_with_query_string() -> None:
    with pytest.raises(ConfigError, match="query parameters"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com?foo=bar",
                "OPENPROJECT_API_TOKEN": "token-value",
            }
        )


def test_settings_from_env_rejects_invalid_bool_value() -> None:
    with pytest.raises(ConfigError, match="boolean"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_PERSONAL_WRITE": "ja",
            }
        )


def test_settings_from_env_rejects_invalid_log_level() -> None:
    with pytest.raises(ConfigError, match="CRITICAL"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_LOG_LEVEL": "VERBOSE",
            }
        )


def test_http_remote_base_url_warns(caplog) -> None:
    with caplog.at_level("WARNING"):
        settings = Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "http://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
            }
        )
    assert settings.base_url == "http://op.example.com"
    assert any("unencrypted" in record.message for record in caplog.records)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
        "https://op.example.com",
    ],
)
def test_local_or_https_base_url_does_not_warn(base_url, caplog) -> None:
    with caplog.at_level("WARNING"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": base_url,
                "OPENPROJECT_API_TOKEN": "token-value",
            }
        )
    assert not any("unencrypted" in record.message for record in caplog.records)


def test_max_retries_exceeds_limit() -> None:
    with pytest.raises(ConfigError, match="OPENPROJECT_MAX_RETRIES must not exceed 10"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_MAX_RETRIES": "11",
            }
        )


def test_retry_max_delay_less_than_base_delay() -> None:
    with pytest.raises(ConfigError, match="OPENPROJECT_RETRY_MAX_DELAY must be >= OPENPROJECT_RETRY_BASE_DELAY"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_RETRY_BASE_DELAY": "10.0",
                "OPENPROJECT_RETRY_MAX_DELAY": "5.0",
            }
        )


def test_retry_settings_valid_defaults() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )
    assert settings.max_retries == 3
    assert settings.retry_base_delay == 1.0
    assert settings.retry_max_delay == 60.0


def test_relative_attachment_root_is_rejected() -> None:
    with pytest.raises(ConfigError, match="absolute"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_ATTACHMENT_ROOT": "uploads",
            }
        )


def test_absolute_attachment_root_is_accepted() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ATTACHMENT_ROOT": ABSOLUTE_ATTACHMENT_ROOT,
        }
    )
    assert settings.attachment_root == ABSOLUTE_ATTACHMENT_ROOT


def test_tilde_attachment_root_is_accepted() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ATTACHMENT_ROOT": "~/uploads",
        }
    )
    assert settings.attachment_root == "~/uploads"


def test_empty_attachment_root_is_accepted_at_config_time() -> None:
    # The config layer only validates format when a value IS given — the actual
    # "uploads disabled" enforcement happens later, in client.py/tools.py, not here.
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )
    assert settings.attachment_root == ""


# ── legacy_env_warnings (OPM-128) ────────────────────────────────────────────────


def test_legacy_env_warnings_empty_when_no_legacy_vars_present() -> None:
    assert legacy_env_warnings({"OPENPROJECT_BASE_URL": "https://op.example.com"}) == []


def test_legacy_env_warnings_names_both_old_and_new_var() -> None:
    warnings = legacy_env_warnings({"OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM"})
    assert len(warnings) == 1
    assert "OPENPROJECT_ALLOWED_PROJECTS_READ" in warnings[0]
    assert "OPENPROJECT_READ_PROJECTS" in warnings[0]
    assert "deprecated" in warnings[0]
    assert "fail-closed" in warnings[0]


def test_legacy_env_warnings_one_line_per_detected_name_in_map_order() -> None:
    env = {
        "OPENPROJECT_ENABLE_BOARD_READ": "true",
        "OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM",
        "OPENPROJECT_ENABLE_METADATA_TOOLS": "false",
    }
    warnings = legacy_env_warnings(env)
    assert len(warnings) == 3
    # Deterministic order = _LEGACY_ENV_VAR_MAP's own definition order, not the
    # dict-iteration order of the (arbitrarily ordered) input env.
    assert "OPENPROJECT_ALLOWED_PROJECTS_READ" in warnings[0]
    assert "OPENPROJECT_ENABLE_BOARD_READ" in warnings[1]
    assert "OPENPROJECT_ENABLE_METADATA_TOOLS" in warnings[2]


def test_legacy_env_warnings_still_warns_when_replacement_is_also_present() -> None:
    # The old value is never adopted either way, but a legacy var sitting next
    # to its already-correct replacement is still dead config worth flagging.
    env = {"OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM", "OPENPROJECT_READ_PROJECTS": "TST"}
    warnings = legacy_env_warnings(env)
    assert len(warnings) == 1
    assert "OPENPROJECT_ALLOWED_PROJECTS_READ" in warnings[0]


def test_legacy_env_warnings_does_not_resurrect_old_value() -> None:
    # The old value is never adopted — fail-closed defaults apply exactly as if
    # the legacy variable weren't set at all.
    env = {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "tok",
        "OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM",
    }
    assert legacy_env_warnings(env)  # sanity: this env does trigger a warning
    settings = Settings.from_env(env)
    assert settings.read_projects == ()
    assert settings.attachment_root == ""
