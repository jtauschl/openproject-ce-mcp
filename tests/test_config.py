from __future__ import annotations

import pytest

from openproject_mcp.config import ConfigError, Settings


def test_settings_from_env_loads_and_normalizes_values() -> None:
    settings = Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com/",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_ALLOWED_PROJECTS_READ": "mcp-test, openproject-mcp",
                "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "mcp-test",
                "OPENPROJECT_ENABLE_PROJECT_READ": "true",
                "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "false",
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
    assert settings.allowed_projects == ("mcp-test", "openproject-mcp")
    assert settings.allowed_write_projects == ("mcp-test",)
    assert settings.allowed_write_projects_configured is True
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


def test_settings_from_env_keeps_legacy_allowed_projects_as_read_alias() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ALLOWED_PROJECTS": "demo",
        }
    )

    assert settings.allowed_projects == ("demo",)
    assert settings.allowed_write_projects == ()
    assert settings.allowed_write_projects_configured is False


def test_settings_from_env_accepts_wildcard_project_scopes() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ALLOWED_PROJECTS_READ": "*",
            "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "*",
        }
    )

    assert settings.allowed_projects == ("*",)
    assert settings.allowed_write_projects == ("*",)
    assert settings.allowed_write_projects_configured is True


def test_settings_from_env_treats_explicit_empty_write_scope_as_configured() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "",
        }
    )

    assert settings.allowed_write_projects == ()
    assert settings.allowed_write_projects_configured is True
    assert settings.project_write_scope_allows_none is True


def test_settings_from_env_per_scope_read_flags_restrict_when_global_read_enabled() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_READ": "true",
            "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "false",
        }
    )

    assert settings.read_enabled("project") is True
    assert settings.read_enabled("membership") is False


def test_settings_from_env_scoped_read_flags_disable_chains_independently() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_PROJECT_READ": "false",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": "false",
        }
    )

    assert settings.read_enabled("project") is False
    assert settings.read_enabled("work_package") is False
    assert settings.read_enabled("membership") is True  # not disabled


def test_settings_from_env_scoped_write_flag_enables_chain_when_global_write_disabled() -> None:
    # writes default to disabled; scoped flags selectively opt individual chains in
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_WRITE": "false",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "true",
        }
    )

    assert settings.write_enabled("work_package") is True
    assert settings.write_enabled("project") is False
    assert settings.write_enabled("membership") is False


def test_settings_from_env_global_write_false_disables_all_scopes() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_WRITE": "false",
        }
    )

    assert settings.write_enabled("project") is False
    assert settings.write_enabled("work_package") is False
    assert settings.write_enabled("membership") is False


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
                "OPENPROJECT_ENABLE_PROJECT_READ": "ja",
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


def test_auto_confirm_delete_inherits_write_when_unset() -> None:
    env = {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "token",
        "OPENPROJECT_AUTO_CONFIRM_WRITE": "true",
        # OPENPROJECT_AUTO_CONFIRM_DELETE intentionally unset -> inherits write
    }
    settings = Settings.from_env(env)
    assert settings.auto_confirm_write is True
    assert settings.auto_confirm_delete is True


def test_auto_confirm_delete_can_be_disabled_independently() -> None:
    env = {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "token",
        "OPENPROJECT_AUTO_CONFIRM_WRITE": "true",
        "OPENPROJECT_AUTO_CONFIRM_DELETE": "false",  # keep a preview for deletes
    }
    settings = Settings.from_env(env)
    assert settings.auto_confirm_write is True
    assert settings.auto_confirm_delete is False
