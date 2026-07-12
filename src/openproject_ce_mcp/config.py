from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when environment configuration is missing or invalid."""


# Scope strings are internal literals written by this codebase, never user
# input — an unrecognized one is always a programming error (typo, or a new
# client.py call site whose scope was never wired up here) and must fail
# loud via ConfigError, not silently resolve to allow-all or deny-all.
# "admin" is deliberately NOT a key of _WRITE_SCOPE_SETTINGS: it is handled
# separately (instance-wide, not a per-scope Settings attribute) by
# client.py::_ensure_write_enabled and by the tool registration gate.
_READ_SCOPE_SETTINGS: dict[str, str] = {
    "work_package": "enable_work_package_read",
    "project": "enable_project_read",
    "membership": "enable_membership_read",
    "role": "enable_membership_read",
    "principal": "enable_membership_read",
    "version": "enable_version_read",
    "board": "enable_board_read",
    "personal": "enable_personal_read",
    "extended": "enable_metadata_tools",
}
_WRITE_SCOPE_SETTINGS: dict[str, str] = {
    "work_package": "enable_work_package_write",
    "project": "enable_project_write",
    "membership": "enable_membership_write",
    "version": "enable_version_write",
    "board": "enable_board_write",
    "personal": "enable_personal_write",
}


# OPENPROJECT_TOOLS group name -> read/write scope string used above. "personal"
# and "extended" are scopes in their own right (see Settings.enable_personal_*
# and enable_metadata_tools); "extended" has no write counterpart because every
# METADATA_TOOLS client.py method is a pure read.
_TOOL_GROUP_TO_SCOPE: dict[str, str] = {
    "projects": "project",
    "work-packages": "work_package",
    "memberships": "membership",
    "versions": "version",
    "boards": "board",
    "personal": "personal",
    "extended": "extended",
}

# Compatible core-5 default when OPENPROJECT_TOOLS is unset entirely — "personal"
# and "extended" are opt-in only, never part of the unset default (see OPM-126).
_DEFAULT_TOOL_GROUPS: frozenset[str] = frozenset({"projects", "work-packages", "memberships", "versions", "boards"})

# (flag_key, tool group, env var) triples: a True write flag whose group is not
# in OPENPROJECT_TOOLS is a startup-time ConfigError (see tool_exposure_violations
# below). Shared by Settings.from_env's validation and setup_cli.py's pre-write
# wizard reconciliation so the rule lives in exactly one place.
WRITE_GROUP_REQUIREMENTS: tuple[tuple[str, str, str], ...] = (
    ("project_write", "projects", "OPENPROJECT_ENABLE_PROJECT_WRITE"),
    ("work_package_write", "work-packages", "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE"),
    ("membership_write", "memberships", "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE"),
    ("version_write", "versions", "OPENPROJECT_ENABLE_VERSION_WRITE"),
    ("board_write", "boards", "OPENPROJECT_ENABLE_BOARD_WRITE"),
    ("personal_write", "personal", "OPENPROJECT_PERSONAL_WRITE"),
)


def tool_exposure_violations(tool_groups: frozenset[str], **write_flags: bool) -> list[tuple[str, str, str]]:
    """(flag_key, group, env_var) triples where write_flags[flag_key] is True but
    group is absent from tool_groups. Shared by Settings.from_env's startup
    validation and setup_cli.py's pre-write reconciliation."""
    return [
        (key, group, env_var)
        for key, group, env_var in WRITE_GROUP_REQUIREMENTS
        if write_flags.get(key) and group not in tool_groups
    ]


def parse_tool_groups_csv(raw: str) -> frozenset[str]:
    """Parse + validate a raw OPENPROJECT_TOOLS CSV value (no unset-handling —
    that is _parse_tool_groups's job). Raises ConfigError on any unknown group
    name. Public so setup_cli.py can validate the wizard's free-text prompt
    with the exact same rule the runtime enforces."""
    raw_groups = _parse_csv(raw)
    unknown = sorted(set(raw_groups) - set(_TOOL_GROUP_TO_SCOPE))
    if unknown:
        raise ConfigError(
            f"OPENPROJECT_TOOLS has unknown tool group(s): {', '.join(unknown)}. "
            f"Known groups: {', '.join(sorted(_TOOL_GROUP_TO_SCOPE))}."
        )
    return frozenset(raw_groups)


def _parse_tool_groups(env: Mapping[str, str]) -> frozenset[str]:
    if "OPENPROJECT_TOOLS" not in env:
        return _DEFAULT_TOOL_GROUPS
    return parse_tool_groups_csv(env.get("OPENPROJECT_TOOLS", ""))


# Cap for a work-package description shown in list/summary results — a per-row
# preview so a multi-row list stays scannable without flooding the agent's context
# window. Single-item reads (get_work_package, get_work_package_activities) are NOT
# capped by default. ``OPENPROJECT_TEXT_LIMIT`` overrides this default; a per-call
# ``text_limit`` overrides that. TEXT_LIMIT_MAX is an absolute sanity ceiling that
# no explicit ``text_limit`` may exceed.
DEFAULT_TEXT_LIMIT = 500
TEXT_LIMIT_MAX = 50_000


HIDE_FIELD_ENV_BY_ENTITY: dict[str, str] = {
    "project": "OPENPROJECT_HIDE_PROJECT_FIELDS",
    "membership": "OPENPROJECT_HIDE_MEMBERSHIP_FIELDS",
    "role": "OPENPROJECT_HIDE_ROLE_FIELDS",
    "principal": "OPENPROJECT_HIDE_PRINCIPAL_FIELDS",
    "user": "OPENPROJECT_HIDE_USER_FIELDS",
    "group": "OPENPROJECT_HIDE_GROUP_FIELDS",
    "project_access": "OPENPROJECT_HIDE_PROJECT_ACCESS_FIELDS",
    "project_admin_context": "OPENPROJECT_HIDE_PROJECT_ADMIN_CONTEXT_FIELDS",
    "project_configuration": "OPENPROJECT_HIDE_PROJECT_CONFIGURATION_FIELDS",
    "action": "OPENPROJECT_HIDE_ACTION_FIELDS",
    "capability": "OPENPROJECT_HIDE_CAPABILITY_FIELDS",
    "job_status": "OPENPROJECT_HIDE_JOB_STATUS_FIELDS",
    "project_phase_definition": "OPENPROJECT_HIDE_PROJECT_PHASE_DEFINITION_FIELDS",
    "project_phase": "OPENPROJECT_HIDE_PROJECT_PHASE_FIELDS",
    "view": "OPENPROJECT_HIDE_VIEW_FIELDS",
    "query_filter": "OPENPROJECT_HIDE_QUERY_FILTER_FIELDS",
    "query_column": "OPENPROJECT_HIDE_QUERY_COLUMN_FIELDS",
    "query_operator": "OPENPROJECT_HIDE_QUERY_OPERATOR_FIELDS",
    "query_sort_by": "OPENPROJECT_HIDE_QUERY_SORT_BY_FIELDS",
    "query_filter_instance_schema": "OPENPROJECT_HIDE_QUERY_FILTER_INSTANCE_SCHEMA_FIELDS",
    "document": "OPENPROJECT_HIDE_DOCUMENT_FIELDS",
    "news": "OPENPROJECT_HIDE_NEWS_FIELDS",
    "wiki_page": "OPENPROJECT_HIDE_WIKI_PAGE_FIELDS",
    "category": "OPENPROJECT_HIDE_CATEGORY_FIELDS",
    "attachment": "OPENPROJECT_HIDE_ATTACHMENT_FIELDS",
    "time_entry_activity": "OPENPROJECT_HIDE_TIME_ENTRY_ACTIVITY_FIELDS",
    "time_entry": "OPENPROJECT_HIDE_TIME_ENTRY_FIELDS",
    "work_package": "OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS",
    "relation": "OPENPROJECT_HIDE_RELATION_FIELDS",
    "activity": "OPENPROJECT_HIDE_ACTIVITY_FIELDS",
    "reminder": "OPENPROJECT_HIDE_REMINDER_FIELDS",
    "version": "OPENPROJECT_HIDE_VERSION_FIELDS",
    "sprint": "OPENPROJECT_HIDE_SPRINT_FIELDS",
    "board": "OPENPROJECT_HIDE_BOARD_FIELDS",
    "current_user": "OPENPROJECT_HIDE_CURRENT_USER_FIELDS",
    "instance_configuration": "OPENPROJECT_HIDE_INSTANCE_CONFIGURATION_FIELDS",
    "status": "OPENPROJECT_HIDE_STATUS_FIELDS",
    "type": "OPENPROJECT_HIDE_TYPE_FIELDS",
}


@dataclass(frozen=True, slots=True)
class Settings:
    base_url: str
    api_token: str
    timeout: float
    verify_ssl: bool
    default_page_size: int
    max_page_size: int
    max_results: int
    log_level: str
    text_limit: int = DEFAULT_TEXT_LIMIT
    read_projects: tuple[str, ...] = ()
    write_projects: tuple[str, ...] = ()
    enable_work_package_read: bool = True
    enable_project_read: bool = True
    enable_membership_read: bool = True
    enable_version_read: bool = True
    enable_board_read: bool = True
    enable_personal_read: bool = False
    hide_project_fields: tuple[str, ...] = ()
    hide_work_package_fields: tuple[str, ...] = ()
    hide_activity_fields: tuple[str, ...] = ()
    hide_custom_fields: tuple[str, ...] = ()
    hidden_fields: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    enable_work_package_write: bool = False
    enable_project_write: bool = False
    enable_membership_write: bool = False
    enable_version_write: bool = False
    enable_board_write: bool = False
    enable_personal_write: bool = False
    enable_admin_write: bool = False
    enable_metadata_tools: bool = False
    attachment_root: str = ""
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0

    def read_enabled(self, scope: str) -> bool:
        try:
            attr = _READ_SCOPE_SETTINGS[scope]
        except KeyError:
            raise ConfigError(f"Unknown read scope {scope!r}.") from None
        return bool(getattr(self, attr))

    def write_enabled(self, scope: str) -> bool:
        try:
            attr = _WRITE_SCOPE_SETTINGS[scope]
        except KeyError:
            raise ConfigError(f"Unknown write scope {scope!r}.") from None
        return bool(getattr(self, attr))

    @property
    def api_base_url(self) -> str:
        return f"{self.base_url}/api/v3"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = environ or os.environ
        base_url = _parse_base_url(env.get("OPENPROJECT_BASE_URL"))
        api_token = _require_non_empty(env.get("OPENPROJECT_API_TOKEN"), "OPENPROJECT_API_TOKEN")
        read_projects = _parse_csv(env.get("OPENPROJECT_READ_PROJECTS"))
        write_projects = _parse_csv(env.get("OPENPROJECT_WRITE_PROJECTS"))
        tool_groups = _parse_tool_groups(env)
        enable_project_read = "projects" in tool_groups
        enable_work_package_read = "work-packages" in tool_groups
        enable_membership_read = "memberships" in tool_groups
        enable_version_read = "versions" in tool_groups
        enable_board_read = "boards" in tool_groups
        enable_personal_read = "personal" in tool_groups
        enable_metadata_tools = "extended" in tool_groups
        hidden_fields = {
            entity: patterns
            for entity, env_name in HIDE_FIELD_ENV_BY_ENTITY.items()
            if (patterns := _parse_csv(env.get(env_name)))
        }
        hide_project_fields = hidden_fields.get("project", ())
        hide_work_package_fields = hidden_fields.get("work_package", ())
        hide_activity_fields = hidden_fields.get("activity", ())
        hide_custom_fields = _parse_csv(env.get("OPENPROJECT_HIDE_CUSTOM_FIELDS"))
        enable_work_package_write = _parse_bool(
            env.get("OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE"),
            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE",
            default=False,
        )
        enable_project_write = _parse_bool(
            env.get("OPENPROJECT_ENABLE_PROJECT_WRITE"),
            "OPENPROJECT_ENABLE_PROJECT_WRITE",
            default=False,
        )
        enable_membership_write = _parse_bool(
            env.get("OPENPROJECT_ENABLE_MEMBERSHIP_WRITE"),
            "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE",
            default=False,
        )
        enable_version_write = _parse_bool(
            env.get("OPENPROJECT_ENABLE_VERSION_WRITE"),
            "OPENPROJECT_ENABLE_VERSION_WRITE",
            default=False,
        )
        enable_board_write = _parse_bool(
            env.get("OPENPROJECT_ENABLE_BOARD_WRITE"),
            "OPENPROJECT_ENABLE_BOARD_WRITE",
            default=False,
        )
        enable_personal_write = _parse_bool(
            env.get("OPENPROJECT_PERSONAL_WRITE"),
            "OPENPROJECT_PERSONAL_WRITE",
            default=False,
        )
        enable_admin_write = _parse_bool(
            env.get("OPENPROJECT_ENABLE_ADMIN_WRITE"),
            "OPENPROJECT_ENABLE_ADMIN_WRITE",
            default=False,
        )
        timeout = _parse_float(env.get("OPENPROJECT_TIMEOUT"), "OPENPROJECT_TIMEOUT", default=12.0, minimum=1.0)
        verify_ssl = _parse_bool(env.get("OPENPROJECT_VERIFY_SSL"), "OPENPROJECT_VERIFY_SSL", default=True)
        default_page_size = _parse_int(
            env.get("OPENPROJECT_DEFAULT_PAGE_SIZE"),
            "OPENPROJECT_DEFAULT_PAGE_SIZE",
            # 10, not 20: measured OPM lists are ~44% description bytes, so page size
            # is the strongest lever on list context. 10 halves it while still showing
            # a useful chunk on one call; raise OPENPROJECT_DEFAULT_PAGE_SIZE if needed.
            default=10,
            minimum=1,
        )
        max_page_size = _parse_int(
            env.get("OPENPROJECT_MAX_PAGE_SIZE"),
            "OPENPROJECT_MAX_PAGE_SIZE",
            default=50,
            minimum=1,
        )
        max_results = _parse_int(
            env.get("OPENPROJECT_MAX_RESULTS"),
            "OPENPROJECT_MAX_RESULTS",
            default=100,
            minimum=1,
        )
        log_level = _parse_log_level(env.get("OPENPROJECT_LOG_LEVEL"), "OPENPROJECT_LOG_LEVEL", default="WARNING")
        text_limit = _parse_int(
            env.get("OPENPROJECT_TEXT_LIMIT"),
            "OPENPROJECT_TEXT_LIMIT",
            default=DEFAULT_TEXT_LIMIT,
            minimum=1,
        )
        if text_limit > TEXT_LIMIT_MAX:
            raise ConfigError(f"OPENPROJECT_TEXT_LIMIT must not exceed {TEXT_LIMIT_MAX}.")
        attachment_root = (env.get("OPENPROJECT_ATTACHMENT_ROOT") or "").strip()
        max_retries = _parse_int(
            env.get("OPENPROJECT_MAX_RETRIES"),
            "OPENPROJECT_MAX_RETRIES",
            default=3,
            minimum=0,
        )
        if max_retries > 10:
            raise ConfigError("OPENPROJECT_MAX_RETRIES must not exceed 10.")
        retry_base_delay = _parse_float(
            env.get("OPENPROJECT_RETRY_BASE_DELAY"),
            "OPENPROJECT_RETRY_BASE_DELAY",
            default=1.0,
            minimum=0.0,
        )
        retry_max_delay = _parse_float(
            env.get("OPENPROJECT_RETRY_MAX_DELAY"),
            "OPENPROJECT_RETRY_MAX_DELAY",
            default=60.0,
            minimum=0.0,
        )
        if retry_max_delay < retry_base_delay:
            raise ConfigError("OPENPROJECT_RETRY_MAX_DELAY must be >= OPENPROJECT_RETRY_BASE_DELAY.")

        if default_page_size > max_page_size:
            raise ConfigError("OPENPROJECT_DEFAULT_PAGE_SIZE must not exceed OPENPROJECT_MAX_PAGE_SIZE.")
        if max_page_size > max_results:
            raise ConfigError("OPENPROJECT_MAX_PAGE_SIZE must not exceed OPENPROJECT_MAX_RESULTS.")

        violations = tool_exposure_violations(
            tool_groups,
            project_write=enable_project_write,
            work_package_write=enable_work_package_write,
            membership_write=enable_membership_write,
            version_write=enable_version_write,
            board_write=enable_board_write,
            personal_write=enable_personal_write,
        )
        if violations:
            _, group, env_var = violations[0]
            raise ConfigError(f"{env_var}=true requires '{group}' to be present in OPENPROJECT_TOOLS.")

        return cls(
            base_url=base_url,
            api_token=api_token,
            timeout=timeout,
            verify_ssl=verify_ssl,
            default_page_size=default_page_size,
            max_page_size=max_page_size,
            max_results=max_results,
            log_level=log_level,
            text_limit=text_limit,
            read_projects=read_projects,
            write_projects=write_projects,
            enable_project_read=enable_project_read,
            enable_membership_read=enable_membership_read,
            enable_work_package_read=enable_work_package_read,
            enable_version_read=enable_version_read,
            enable_board_read=enable_board_read,
            enable_personal_read=enable_personal_read,
            hide_project_fields=hide_project_fields,
            hide_work_package_fields=hide_work_package_fields,
            hide_activity_fields=hide_activity_fields,
            hide_custom_fields=hide_custom_fields,
            hidden_fields=hidden_fields,
            enable_work_package_write=enable_work_package_write,
            enable_project_write=enable_project_write,
            enable_membership_write=enable_membership_write,
            enable_version_write=enable_version_write,
            enable_board_write=enable_board_write,
            enable_personal_write=enable_personal_write,
            enable_admin_write=enable_admin_write,
            enable_metadata_tools=enable_metadata_tools,
            attachment_root=attachment_root,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
        )


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.WARNING)
    logging.basicConfig(
        level=numeric_level,
        format="%(levelname)s %(name)s %(message)s",
    )
    # basicConfig is a no-op once a handler is already installed (e.g. by FastMCP),
    # so set the level explicitly to make it actually take effect (OPM-62).
    logging.getLogger().setLevel(numeric_level)


def _require_non_empty(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise ConfigError(f"{name} is required.")
    return value.strip()


_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _parse_base_url(value: str | None) -> str:
    raw_value = _require_non_empty(value, "OPENPROJECT_BASE_URL").rstrip("/")
    parsed = urlparse(raw_value)
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError("OPENPROJECT_BASE_URL must use http or https.")
    if not parsed.netloc:
        raise ConfigError("OPENPROJECT_BASE_URL must include a hostname.")
    if parsed.query or parsed.fragment:
        raise ConfigError("OPENPROJECT_BASE_URL must not contain query parameters or fragments.")
    # Warn (don't block) when the API token would travel unencrypted to a remote
    # host over plain http. Use .hostname so ports and IPv6 brackets don't defeat
    # the localhost check.
    if parsed.scheme == "http" and (parsed.hostname or "").lower() not in _LOCALHOST_HOSTS:
        logging.getLogger(__name__).warning(
            "OPENPROJECT_BASE_URL uses http:// with a non-local host (%s); the API token "
            "is sent unencrypted. Use https:// unless this is a trusted local network.",
            parsed.hostname,
        )
    return raw_value


def _parse_bool(value: str | None, name: str, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}
    if normalized in truthy:
        return True
    if normalized in falsy:
        return False
    raise ConfigError(f"{name} must be a boolean value.")


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None or not value.strip():
        return ()
    items = [" ".join(part.split()) for part in value.split(",")]
    normalized = tuple(item for item in items if item)
    return normalized


def _parse_int(value: str | None, name: str, *, default: int, minimum: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    if parsed < minimum:
        raise ConfigError(f"{name} must be at least {minimum}.")
    return parsed


def _parse_float(value: str | None, name: str, *, default: float, minimum: float) -> float:
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc
    if parsed < minimum:
        raise ConfigError(f"{name} must be at least {minimum}.")
    return parsed


def _parse_log_level(value: str | None, name: str, *, default: str) -> str:
    if value is None or not value.strip():
        return default
    normalized = value.strip().upper()
    allowed = {"CRITICAL", "ERROR", "WARNING", "INFO"}
    if normalized not in allowed:
        raise ConfigError(f"{name} must be one of: {', '.join(sorted(allowed))}.")
    return normalized
