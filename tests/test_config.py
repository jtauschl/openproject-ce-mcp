from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

import pytest

from openproject_ce_mcp.config import (
    READ_SCOPE_ENV_VAR,
    TOOL_GROUPS,
    ConfigConsistencyError,
    ConfigError,
    Settings,
)

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
            "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "false",
            "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": "false",
            "OPENPROJECT_HIDE_PROJECT_FIELDS": "description,status_explanation",
            "OPENPROJECT_HIDE_PRINCIPAL_FIELDS": "*mail,login",
            "OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS": "description",
            "OPENPROJECT_HIDE_ACTIVITY_FIELDS": "comment",
            "OPENPROJECT_HIDE_WATCHER_FIELDS": "login",
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
    assert settings.hidden_fields["watcher"] == ("login",)
    assert settings.hide_custom_fields == ("budget", "internal_notes")
    assert settings.enable_project_write is True
    assert settings.verify_ssl is False
    assert settings.timeout == 15
    assert settings.default_page_size == 10
    assert settings.max_page_size == 20
    assert settings.max_results == 30
    assert settings.log_level == "INFO"


def test_settings_from_env_loads_priority_notification_file_link_emoji_reaction_hidden_fields() -> None:
    # Regression test for four real hidden-field-masking gaps found during the
    # Statuses/Priorities/Types migration: "priority"/"notification"/
    # "emoji_reaction" had no HIDE_FIELD_ENV_BY_ENTITY entry at all, and
    # "file_link" had an entry but was never exercised end-to-end through the
    # real env-var path by any existing test (every test_hidden_fields.py test
    # constructs Settings directly with hidden_fields={...} pre-populated,
    # bypassing HIDE_FIELD_ENV_BY_ENTITY entirely). This test goes through
    # Settings.from_env with the real env var names, the only way to actually
    # prove OPENPROJECT_HIDE_<X>_FIELDS works for a user.
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com/",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_HIDE_PRIORITY_FIELDS": "color",
            "OPENPROJECT_HIDE_NOTIFICATION_FIELDS": "project_name",
            "OPENPROJECT_HIDE_FILE_LINK_FIELDS": "storage_name",
            "OPENPROJECT_HIDE_EMOJI_REACTION_FIELDS": "users",
            "OPENPROJECT_HIDE_POST_FIELDS": "subject",
        }
    )

    assert settings.hidden_fields["priority"] == ("color",)
    assert settings.hidden_fields["notification"] == ("project_name",)
    assert settings.hidden_fields["file_link"] == ("storage_name",)
    assert settings.hidden_fields["emoji_reaction"] == ("users",)
    assert settings.hidden_fields["post"] == ("subject",)


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
            "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": "false",
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
            "OPENPROJECT_ENABLE_PROJECT_WRITE": "false",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": "false",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "false",
        }
    )

    assert settings.read_enabled("project") is False
    assert settings.read_enabled("work_package") is False
    assert settings.read_enabled("membership") is True  # not disabled


def test_settings_from_env_scoped_write_flag_disables_one_scope_independently() -> None:
    # project-scoped writes default to enabled; a scoped flag opts one chain
    # out without affecting others
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "false",
        }
    )

    assert settings.write_enabled("work_package") is False
    assert settings.write_enabled("project") is True
    assert settings.write_enabled("membership") is True


def test_settings_from_env_project_scoped_write_defaults_to_enabled() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )

    assert settings.write_enabled("project") is True
    assert settings.write_enabled("work_package") is True
    assert settings.write_enabled("membership") is True
    assert settings.write_enabled("version") is True
    assert settings.write_enabled("board") is True
    assert settings.write_enabled("meeting") is True


def test_settings_from_env_personal_admin_and_user_schedule_write_default_to_disabled() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )

    assert settings.write_enabled("personal") is False
    assert settings.write_enabled("admin") is False
    assert settings.write_enabled("user_schedule") is False


def test_read_defaults_core_true_opt_in_groups_false() -> None:
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
    assert settings.read_enabled("meeting") is True
    assert settings.read_enabled("personal") is False
    assert settings.enable_metadata_tools is False
    assert settings.read_enabled("admin") is False
    assert settings.read_enabled("user_schedule") is False


def test_read_flags_all_explicitly_false() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_PROJECT_READ": "false",
            "OPENPROJECT_ENABLE_PROJECT_WRITE": "false",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": "false",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "false",
            "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "false",
            "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": "false",
            "OPENPROJECT_ENABLE_VERSION_READ": "false",
            "OPENPROJECT_ENABLE_VERSION_WRITE": "false",
            "OPENPROJECT_ENABLE_BOARD_READ": "false",
            "OPENPROJECT_ENABLE_BOARD_WRITE": "false",
        }
    )

    assert settings.read_enabled("project") is False
    assert settings.read_enabled("work_package") is False
    assert settings.read_enabled("membership") is False
    assert settings.read_enabled("version") is False
    assert settings.read_enabled("board") is False
    assert settings.read_enabled("personal") is False
    assert settings.enable_metadata_tools is False
    assert settings.read_enabled("admin") is False


@pytest.mark.parametrize(
    ("write_var", "read_var"),
    [
        ("OPENPROJECT_ENABLE_PROJECT_WRITE", "OPENPROJECT_ENABLE_PROJECT_READ"),
        ("OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE", "OPENPROJECT_ENABLE_WORK_PACKAGE_READ"),
        ("OPENPROJECT_ENABLE_MEMBERSHIP_WRITE", "OPENPROJECT_ENABLE_MEMBERSHIP_READ"),
        ("OPENPROJECT_ENABLE_VERSION_WRITE", "OPENPROJECT_ENABLE_VERSION_READ"),
        ("OPENPROJECT_ENABLE_BOARD_WRITE", "OPENPROJECT_ENABLE_BOARD_READ"),
        ("OPENPROJECT_ENABLE_PERSONAL_WRITE", "OPENPROJECT_ENABLE_PERSONAL_READ"),
        ("OPENPROJECT_ENABLE_ADMIN_WRITE", "OPENPROJECT_ENABLE_ADMIN_READ"),
    ],
)
def test_write_flag_without_matching_read_rejected(write_var: str, read_var: str) -> None:
    # Covers the review-flagged scenario explicitly: a manually-set READ=false
    # combined with the new implicit WRITE=true (project-scoped) default must
    # still fail loudly via Settings.from_env, exactly like an explicit
    # WRITE=true typed alongside READ=false.
    with pytest.raises(ConfigError, match="requires"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                read_var: "false",
                write_var: "true",
            }
        )


def test_write_flag_with_read_enabled_accepted() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_PERSONAL_READ": "true",
            "OPENPROJECT_ENABLE_PROJECT_WRITE": "true",
            "OPENPROJECT_ENABLE_PERSONAL_WRITE": "true",
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


def test_write_enabled_treats_admin_as_a_normal_scope() -> None:
    # "admin" is a normal scope like any other (unlike the old special-cased
    # design where client.py checked settings.enable_admin_write directly) —
    # write_enabled("admin")/read_enabled("admin") work like every other
    # scope, and the write flag requires its own read flag exactly the same
    # way as the other 6 pairs.
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ENABLE_ADMIN_READ": "true",
            "OPENPROJECT_ENABLE_ADMIN_WRITE": "true",
        }
    )

    assert settings.read_enabled("admin") is True
    assert settings.write_enabled("admin") is True


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
                "OPENPROJECT_ENABLE_PERSONAL_WRITE": "ja",
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


def test_settings_from_env_accepts_debug_log_level() -> None:
    # DEBUG is a real Python logging level and is part of MCPServer's accepted
    # log_level Literal, so this validator's allowed set must include it.
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_LOG_LEVEL": "debug",
        }
    )
    assert settings.log_level == "DEBUG"


def test_settings_from_env_defaults_log_format_to_text() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )
    assert settings.log_format == "text"


def test_settings_from_env_accepts_json_log_format_case_insensitively() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_LOG_FORMAT": "JSON",
        }
    )
    assert settings.log_format == "json"


def test_settings_from_env_rejects_invalid_log_format() -> None:
    with pytest.raises(ConfigError, match="OPENPROJECT_LOG_FORMAT"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_LOG_FORMAT": "xml",
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


_TLS_ENV = {"OPENPROJECT_API_TOKEN": "token-value"}


def test_disabled_tls_verification_warns_and_names_the_host_but_not_the_token(caplog) -> None:
    with caplog.at_level("WARNING"):
        Settings.from_env(
            {**_TLS_ENV, "OPENPROJECT_BASE_URL": "https://op.example.com:8443", "OPENPROJECT_VERIFY_SSL": "false"}
        )
    messages = [record.getMessage() for record in caplog.records if "VERIFY_SSL" in record.getMessage()]
    assert len(messages) == 1
    assert "op.example.com" in messages[0]
    assert "SSL_CERT_FILE" in messages[0]
    assert "token-value" not in " ".join(record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "env",
    [
        {"OPENPROJECT_BASE_URL": "https://op.example.com"},
        {"OPENPROJECT_BASE_URL": "https://op.example.com", "OPENPROJECT_VERIFY_SSL": "true"},
        {"OPENPROJECT_BASE_URL": "http://localhost:8080", "OPENPROJECT_VERIFY_SSL": "false"},
    ],
    ids=["default", "explicitly-on", "plain-http-has-no-certificate"],
)
def test_tls_verification_warning_is_absent_when_it_does_not_apply(env, caplog) -> None:
    with caplog.at_level("WARNING"):
        Settings.from_env({**_TLS_ENV, **env})
    assert not any("VERIFY_SSL" in record.getMessage() for record in caplog.records)


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
    # "uploads disabled" enforcement happens later, in
    # app/services/attachment_service.py (runtime path check) and tools.py
    # (registration gate), not here.
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
        }
    )
    assert settings.attachment_root == ""


# ── legacy env-var names (removed) ──────────────────────────────────────────


def test_legacy_env_var_names_have_no_effect_on_settings() -> None:
    # Removed names are unrecognized env vars like any other, silently ignored by
    # Settings.from_env with no warning and no special-cased adoption.
    env = {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "token-value",
        "OPENPROJECT_ALLOWED_PROJECTS_READ": "DEMO",
        "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "DEMO",
        "OPENPROJECT_ENABLE_PERSONAL_READ": "true",
        "OPENPROJECT_PERSONAL_WRITE": "true",
        "OPENPROJECT_TOOLS": "projects,work-packages",
        "OPENPROJECT_ENABLE_METADATA_TOOLS": "true",
        "OPENPROJECT_AUTO_CONFIRM_WRITE": "true",
        "OPENPROJECT_AUTO_CONFIRM_DELETE": "true",
    }
    settings = Settings.from_env(env)
    assert settings.read_projects == ()
    assert settings.write_projects == ()
    assert settings.write_enabled("personal") is False
    assert settings.read_enabled("extended") is False


def test_core_group_flags_are_current_not_legacy() -> None:
    # The individual group booleans are current, not legacy.
    env = {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "token-value",
        "OPENPROJECT_ENABLE_PROJECT_READ": "false",
        "OPENPROJECT_ENABLE_PROJECT_WRITE": "false",
        "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": "false",
        "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "false",
        "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "false",
        "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": "false",
        "OPENPROJECT_ENABLE_VERSION_READ": "false",
        "OPENPROJECT_ENABLE_VERSION_WRITE": "false",
        "OPENPROJECT_ENABLE_BOARD_READ": "false",
        "OPENPROJECT_ENABLE_BOARD_WRITE": "false",
    }
    settings = Settings.from_env(env)
    assert settings.read_enabled("project") is False
    assert settings.read_enabled("work_package") is False
    assert settings.read_enabled("membership") is False
    assert settings.read_enabled("version") is False
    assert settings.read_enabled("board") is False


def test_attachment_content_max_bytes_defaults_to_5_mib() -> None:
    settings = Settings.from_env(
        {"OPENPROJECT_BASE_URL": "https://op.example.com", "OPENPROJECT_API_TOKEN": "token-value"}
    )
    assert settings.attachment_content_max_bytes == 5 * 1024 * 1024


def test_attachment_content_max_bytes_is_configurable() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token-value",
            "OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES": "1048576",
        }
    )
    assert settings.attachment_content_max_bytes == 1_048_576


def test_attachment_content_max_bytes_exceeds_ceiling() -> None:
    with pytest.raises(ConfigError, match="OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES must not exceed 26214400"):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES": str(25 * 1024 * 1024 + 1),
            }
        )


def test_attachment_content_max_bytes_rejects_zero() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(
            {
                "OPENPROJECT_BASE_URL": "https://op.example.com",
                "OPENPROJECT_API_TOKEN": "token-value",
                "OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES": "0",
            }
        )


def test_tool_groups_registry_matches_settings_fields_both_ways() -> None:
    group_fields = {f.name: f.default for f in dataclasses.fields(Settings) if f.name.startswith("enable_")}
    registry = {group.read_attr: group.read_default for group in TOOL_GROUPS}
    registry |= {group.write.attr: group.write.default for group in TOOL_GROUPS if group.write is not None}

    assert group_fields == registry


def test_membership_scope_aliases_share_the_membership_read_flag() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "t",
            "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "false",
            "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": "false",
        }
    )

    assert [settings.read_enabled(scope) for scope in ("membership", "role", "principal")] == [False, False, False]
    assert READ_SCOPE_ENV_VAR["principal"] == "OPENPROJECT_ENABLE_MEMBERSHIP_READ"


def test_settings_from_an_empty_mapping_does_not_read_the_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENPROJECT_BASE_URL", "https://op.example.com")
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", "token-value")

    with pytest.raises(ConfigError, match="OPENPROJECT_BASE_URL is required"):
        Settings.from_env({})


_VALID = {"OPENPROJECT_BASE_URL": "https://op.example.com", "OPENPROJECT_API_TOKEN": "token-value"}


@pytest.mark.parametrize(
    "values",
    [
        {"OPENPROJECT_DEFAULT_PAGE_SIZE": "60"},
        {"OPENPROJECT_MAX_PAGE_SIZE": "200"},
        {"OPENPROJECT_RETRY_BASE_DELAY": "90"},
        {"OPENPROJECT_ENABLE_ADMIN_WRITE": "true"},
    ],
)
def test_contradicting_values_raise_the_consistency_error(values) -> None:
    with pytest.raises(ConfigConsistencyError):
        Settings.from_env({**_VALID, **values})


def test_an_invalid_single_value_is_reported_before_any_consistency_rule() -> None:
    with pytest.raises(ConfigError, match="OPENPROJECT_VERIFY_SSL must be a boolean value") as raised:
        Settings.from_env({**_VALID, "OPENPROJECT_DEFAULT_PAGE_SIZE": "60", "OPENPROJECT_VERIFY_SSL": "maybe"})

    assert not isinstance(raised.value, ConfigConsistencyError)


def test_consistency_error_lists_every_broken_rule_with_its_variables() -> None:
    values = {
        **_VALID,
        "OPENPROJECT_RETRY_BASE_DELAY": "90",
        "OPENPROJECT_DEFAULT_PAGE_SIZE": "60",
        "OPENPROJECT_ENABLE_ADMIN_WRITE": "true",
    }
    with pytest.raises(ConfigConsistencyError) as raised:
        Settings.from_env(values)

    assert [keys for _, keys in raised.value.violations] == [
        ("OPENPROJECT_RETRY_MAX_DELAY", "OPENPROJECT_RETRY_BASE_DELAY"),
        ("OPENPROJECT_DEFAULT_PAGE_SIZE", "OPENPROJECT_MAX_PAGE_SIZE"),
        ("OPENPROJECT_ENABLE_ADMIN_WRITE", "OPENPROJECT_ENABLE_ADMIN_READ"),
    ]
    assert str(raised.value) == "OPENPROJECT_RETRY_MAX_DELAY must be >= OPENPROJECT_RETRY_BASE_DELAY."


@pytest.mark.parametrize("name", ["OPENPROJECT_TIMEOUT", "OPENPROJECT_RETRY_BASE_DELAY", "OPENPROJECT_RETRY_MAX_DELAY"])
@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity", "1e999"])
def test_a_number_from_the_environment_must_be_finite(name: str, value: str) -> None:
    env = {"OPENPROJECT_BASE_URL": "https://op.example.com", "OPENPROJECT_API_TOKEN": "token", name: value}

    with pytest.raises(ConfigError, match=f"{name} must be a finite number"):
        Settings.from_env(env)


_SCOPE_ENV = {"OPENPROJECT_BASE_URL": "https://op.example.com", "OPENPROJECT_API_TOKEN": "token"}


@pytest.mark.parametrize("variable", ["OPENPROJECT_READ_PROJECTS", "OPENPROJECT_WRITE_PROJECTS"])
@pytest.mark.parametrize(
    "pattern", ["tst", "TST", "team-*", "my_project", "12", "a?b", "[ab]c", "[!a]x", "[a-c]1", "*", "demo, TST"]
)
def test_project_scope_accepts_identifier_id_and_glob_patterns(variable: str, pattern: str) -> None:
    Settings.from_env({**_SCOPE_ENV, variable: pattern})


@pytest.mark.parametrize("variable", ["OPENPROJECT_READ_PROJECTS", "OPENPROJECT_WRITE_PROJECTS"])
@pytest.mark.parametrize("pattern", ["My Project", "demo, My Project", "a.b", "a/b", "a!b", "[", "[!]", "[a", "naïve"])
def test_project_scope_rejects_a_pattern_that_cannot_match_an_identifier(variable: str, pattern: str) -> None:
    with pytest.raises(ConfigError, match=rf"{variable} pattern .* cannot match a project"):
        Settings.from_env({**_SCOPE_ENV, variable: pattern})
