"""The `core` tool profile only narrows what the scope flags and project allowlists register."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.config import DEFAULT_TOOL_PROFILE, TOOL_GROUPS, TOOL_PROFILES, ConfigError, Settings
from openproject_ce_mcp.tools import (
    CORE_TOOLS,
    READ_TOOLS_BY_SCOPE,
    WRITE_TOOLS_BY_SCOPE,
    enabled_tool_names,
)

# A second, hand-written copy: the independent oracle for the constant under test.
_STARTER = frozenset(
    {
        "list_projects",
        "get_project",
        "get_current_user",
        "list_work_packages",
        "search_work_packages",
        "list_my_open_work_packages",
        "get_work_package",
        "get_work_package_activities",
        "get_work_package_relations",
        "list_statuses",
        "list_types",
        "list_priorities",
        "list_available_assignees",
        "list_versions",
        "create_work_package",
        "update_work_package",
        "add_work_package_comment",
        "create_work_package_relation",
        "delete_relation",
        "create_time_entry",
        "list_time_entries",
    }
)

_BASE = {"OPENPROJECT_BASE_URL": "https://op.example.com", "OPENPROJECT_API_TOKEN": "token"}
_ALL_PROJECTS = {"OPENPROJECT_READ_PROJECTS": "*", "OPENPROJECT_WRITE_PROJECTS": "*"}


def _settings(profile: str | None, **extra: str) -> Settings:
    env = {**_BASE, **extra}
    if profile is not None:
        env["OPENPROJECT_TOOL_PROFILE"] = profile
    return Settings.from_env(env)


def _write_flags_off() -> dict[str, str]:
    return {group.write.env_var: "false" for group in TOOL_GROUPS if group.write is not None}


_ENVIRONMENTS = {
    "fresh install, no project scopes": {},
    "read scope only": {"OPENPROJECT_READ_PROJECTS": "*"},
    "read and write scopes": _ALL_PROJECTS,
    "write scope without read scope": {"OPENPROJECT_WRITE_PROJECTS": "*"},
    "every write flag off": {**_ALL_PROJECTS, **_write_flags_off()},
    "work package write flag off": {**_ALL_PROJECTS, "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "false"},
    "work package read flag off": {
        **_ALL_PROJECTS,
        "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "false",
        "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": "false",
    },
    "opt-in groups on": {
        **_ALL_PROJECTS,
        "OPENPROJECT_ENABLE_EXTENDED_READ": "true",
        "OPENPROJECT_ENABLE_PERSONAL_READ": "true",
        "OPENPROJECT_ENABLE_ADMIN_READ": "true",
        "OPENPROJECT_ENABLE_USER_SCHEDULE_READ": "true",
    },
    "attachment uploads on": {**_ALL_PROJECTS, "OPENPROJECT_ATTACHMENT_ROOT": "/tmp"},
}


def test_the_default_profile_is_full() -> None:
    assert DEFAULT_TOOL_PROFILE == "full"
    assert _settings(None).tool_profile == "full"
    assert TOOL_PROFILES == ("full", "core")


def test_the_core_profile_is_the_pinned_starter_set() -> None:
    assert CORE_TOOLS == _STARTER
    assert len(CORE_TOOLS) == 21


def test_every_core_tool_is_a_classified_tool() -> None:
    classified = {
        name for table in (READ_TOOLS_BY_SCOPE, WRITE_TOOLS_BY_SCOPE) for names in table.values() for name in names
    }
    assert CORE_TOOLS <= classified


@pytest.mark.parametrize("label", sorted(_ENVIRONMENTS))
def test_the_core_profile_registers_exactly_the_starter_tools_the_full_profile_registers(label: str) -> None:
    env = _ENVIRONMENTS[label]
    full = enabled_tool_names(_settings("full", **env))
    core = enabled_tool_names(_settings("core", **env))
    assert core == tuple(name for name in full if name in _STARTER)


def test_an_unset_profile_registers_the_full_tool_set() -> None:
    assert enabled_tool_names(_settings(None, **_ALL_PROJECTS)) == enabled_tool_names(
        _settings("full", **_ALL_PROJECTS)
    )


def test_the_core_profile_registers_all_starter_tools_when_scopes_allow_everything() -> None:
    assert set(enabled_tool_names(_settings("core", **_ALL_PROJECTS))) == _STARTER


def test_a_core_tool_whose_group_gate_is_off_stays_unregistered() -> None:
    env = {**_ALL_PROJECTS, "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "false"}
    core = set(enabled_tool_names(_settings("core", **env)))
    assert "create_work_package" not in core
    assert "list_work_packages" in core


def test_without_project_scopes_the_core_profile_keeps_only_the_project_independent_starter_tools() -> None:
    assert set(enabled_tool_names(_settings("core"))) == {
        "get_current_user",
        "list_priorities",
        "list_statuses",
        "list_types",
    }


@pytest.mark.parametrize("value", ["core", "full", " CORE ", "Full"])
def test_the_profile_value_is_case_and_whitespace_tolerant(value: str) -> None:
    assert _settings(value).tool_profile == value.strip().lower()


def test_an_unknown_profile_is_refused_naming_the_variable_and_the_choices() -> None:
    with pytest.raises(ConfigError, match="OPENPROJECT_TOOL_PROFILE must be one of: core, full"):
        _settings("minimal")


def test_an_empty_profile_value_means_the_default() -> None:
    assert _settings("").tool_profile == "full"


def test_the_profile_is_part_of_settings_equality() -> None:
    assert _settings("core") != _settings("full")
    assert dataclasses.replace(_settings("full"), tool_profile="core") == _settings("core")
