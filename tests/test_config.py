from __future__ import annotations

import pytest

from openproject_ce_mcp.config import ConfigError, Settings


def test_settings_from_env_loads_and_normalizes_values() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com/",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_READ_PROJECTS": "mcp-test, openproject-ce-mcp",
            "OPENPROJECT_WRITE_PROJECTS": "mcp-test",
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
