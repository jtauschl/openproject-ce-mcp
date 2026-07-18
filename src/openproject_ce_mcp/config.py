from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when environment configuration is missing or invalid."""


# Scope strings are internal literals written by this codebase, never user
# input — an unrecognized one is always a programming error (typo, or a new
# client.py call site whose scope was never wired up here) and must fail
# loud via ConfigError, not silently resolve to allow-all or deny-all.
# "admin" is a normal scope like any other here: instance-wide (not gated by
# OPENPROJECT_READ_PROJECTS/WRITE_PROJECTS), but otherwise following the same
# independent read/write axes as every other scope.
_READ_SCOPE_SETTINGS: dict[str, str] = {
    "project": "enable_project_read",
    "work_package": "enable_work_package_read",
    "membership": "enable_membership_read",
    "role": "enable_membership_read",
    "principal": "enable_membership_read",
    "version": "enable_version_read",
    "board": "enable_board_read",
    "personal": "enable_personal_read",
    "admin": "enable_admin_read",
    "extended": "enable_metadata_tools",
}
_WRITE_SCOPE_SETTINGS: dict[str, str] = {
    "project": "enable_project_write",
    "work_package": "enable_work_package_write",
    "membership": "enable_membership_write",
    "version": "enable_version_write",
    "board": "enable_board_write",
    "personal": "enable_personal_write",
    "admin": "enable_admin_write",
}

# attr name -> the individual boolean env var that controls it. Single source
# of truth for client.py's error messages (READ_SCOPE_ENV_VAR below) so the
# env var name is never hardcoded a second time.
_READ_ATTR_ENV_VAR: dict[str, str] = {
    "enable_project_read": "OPENPROJECT_ENABLE_PROJECT_READ",
    "enable_work_package_read": "OPENPROJECT_ENABLE_WORK_PACKAGE_READ",
    "enable_membership_read": "OPENPROJECT_ENABLE_MEMBERSHIP_READ",
    "enable_version_read": "OPENPROJECT_ENABLE_VERSION_READ",
    "enable_board_read": "OPENPROJECT_ENABLE_BOARD_READ",
    "enable_personal_read": "OPENPROJECT_ENABLE_PERSONAL_READ",
    "enable_admin_read": "OPENPROJECT_ENABLE_ADMIN_READ",
    "enable_metadata_tools": "OPENPROJECT_ENABLE_EXTENDED_READ",
}
READ_SCOPE_ENV_VAR: dict[str, str] = {scope: _READ_ATTR_ENV_VAR[attr] for scope, attr in _READ_SCOPE_SETTINGS.items()}

# (write_flag_key, read_flag_key, write_env_var, read_env_var) tuples: a True
# write flag whose matching read flag is False is a startup-time ConfigError
# (see tool_exposure_violations below). Shared by Settings.from_env's
# validation and setup_cli.py's pre-write wizard reconciliation so the rule
# lives in exactly one place.
WRITE_GROUP_REQUIREMENTS: tuple[tuple[str, str, str, str], ...] = (
    ("project_write", "project_read", "OPENPROJECT_ENABLE_PROJECT_WRITE", "OPENPROJECT_ENABLE_PROJECT_READ"),
    (
        "work_package_write",
        "work_package_read",
        "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE",
        "OPENPROJECT_ENABLE_WORK_PACKAGE_READ",
    ),
    (
        "membership_write",
        "membership_read",
        "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE",
        "OPENPROJECT_ENABLE_MEMBERSHIP_READ",
    ),
    ("version_write", "version_read", "OPENPROJECT_ENABLE_VERSION_WRITE", "OPENPROJECT_ENABLE_VERSION_READ"),
    ("board_write", "board_read", "OPENPROJECT_ENABLE_BOARD_WRITE", "OPENPROJECT_ENABLE_BOARD_READ"),
    ("personal_write", "personal_read", "OPENPROJECT_ENABLE_PERSONAL_WRITE", "OPENPROJECT_ENABLE_PERSONAL_READ"),
    ("admin_write", "admin_read", "OPENPROJECT_ENABLE_ADMIN_WRITE", "OPENPROJECT_ENABLE_ADMIN_READ"),
)


def tool_exposure_violations(
    read_flags: Mapping[str, bool], write_flags: Mapping[str, bool]
) -> list[tuple[str, str, str, str]]:
    """(write_flag_key, read_flag_key, write_env_var, read_env_var) tuples where
    write_flags[write_flag_key] is True but read_flags[read_flag_key] is False.
    Shared by Settings.from_env's startup validation and setup_cli.py's
    pre-write reconciliation."""
    return [entry for entry in WRITE_GROUP_REQUIREMENTS if write_flags.get(entry[0]) and not read_flags.get(entry[1])]


# Old env-var name -> its replacement, or None for a pure removal with no
# replacement variable. Never read for a value — Settings.from_env has zero
# legacy-name handling, by design (fail-closed rename: an unset or renamed
# legacy variable denies access rather than defaulting to allow); this map
# exists only to WARN, once per detected old name, from every entry point
# that inspects raw env (doctor.py and server.py's real startup path, so the
# warning fires whether the server is inspected or actually running). Order is
# deterministic (dict insertion order) so warning output is stable across
# calls.
_LEGACY_ENV_VAR_MAP: dict[str, str | None] = {
    "OPENPROJECT_ALLOWED_PROJECTS": "OPENPROJECT_READ_PROJECTS",
    "OPENPROJECT_ALLOWED_PROJECTS_READ": "OPENPROJECT_READ_PROJECTS",
    "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "OPENPROJECT_WRITE_PROJECTS",
    "OPENPROJECT_ENABLE_METADATA_TOOLS": "OPENPROJECT_ENABLE_EXTENDED_READ",
    "OPENPROJECT_TOOLS": "the individual OPENPROJECT_ENABLE_<GROUP>_READ variables",
    "OPENPROJECT_PERSONAL_WRITE": "OPENPROJECT_ENABLE_PERSONAL_WRITE",
    "OPENPROJECT_AUTO_CONFIRM_WRITE": None,
    "OPENPROJECT_AUTO_CONFIRM_DELETE": None,
}


def legacy_env_warnings(env: Mapping[str, str]) -> list[str]:
    """One warning line per detected legacy env-var name, naming both the old
    name and its replacement — never a single generic message per category, so
    the operator knows exactly which variable to rename. Presence alone
    triggers a warning (matching prior behavior): a legacy var sitting
    alongside its already-correct replacement still warns, since its value is
    silently ignored either way and that's worth flagging as dead config. A
    `None` replacement (a pure removal, e.g. the old auto-confirm flags) gets
    its own message shape instead of a misleading "use None instead."
    """
    warnings = []
    for old, new in _LEGACY_ENV_VAR_MAP.items():
        if old not in env:
            continue
        if new is None:
            warnings.append(
                f"{old} is deprecated and ignored — it was removed with no "
                "replacement; every write now unconditionally requires confirm=true."
            )
        else:
            warnings.append(f"{old} is deprecated and ignored (fail-closed defaults still apply) — use {new} instead.")
    return warnings


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
    "watcher": "OPENPROJECT_HIDE_WATCHER_FIELDS",
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
    enable_admin_read: bool = False
    hide_project_fields: tuple[str, ...] = ()
    hide_work_package_fields: tuple[str, ...] = ()
    hide_activity_fields: tuple[str, ...] = ()
    hide_custom_fields: tuple[str, ...] = ()
    hidden_fields: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    enable_work_package_write: bool = True
    enable_project_write: bool = True
    enable_membership_write: bool = True
    enable_version_write: bool = True
    enable_board_write: bool = True
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
        enable_project_read = _bool_env(env, "OPENPROJECT_ENABLE_PROJECT_READ", default=True)
        enable_work_package_read = _bool_env(env, "OPENPROJECT_ENABLE_WORK_PACKAGE_READ", default=True)
        enable_membership_read = _bool_env(env, "OPENPROJECT_ENABLE_MEMBERSHIP_READ", default=True)
        enable_version_read = _bool_env(env, "OPENPROJECT_ENABLE_VERSION_READ", default=True)
        enable_board_read = _bool_env(env, "OPENPROJECT_ENABLE_BOARD_READ", default=True)
        enable_personal_read = _bool_env(env, "OPENPROJECT_ENABLE_PERSONAL_READ", default=False)
        enable_admin_read = _bool_env(env, "OPENPROJECT_ENABLE_ADMIN_READ", default=False)
        enable_metadata_tools = _bool_env(env, "OPENPROJECT_ENABLE_EXTENDED_READ", default=False)
        hidden_fields = {
            entity: patterns
            for entity, env_name in HIDE_FIELD_ENV_BY_ENTITY.items()
            if (patterns := _parse_csv(env.get(env_name)))
        }
        hide_project_fields = hidden_fields.get("project", ())
        hide_work_package_fields = hidden_fields.get("work_package", ())
        hide_activity_fields = hidden_fields.get("activity", ())
        hide_custom_fields = _parse_csv(env.get("OPENPROJECT_HIDE_CUSTOM_FIELDS"))
        enable_project_write = _bool_env(env, "OPENPROJECT_ENABLE_PROJECT_WRITE", default=True)
        enable_work_package_write = _bool_env(env, "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE", default=True)
        enable_membership_write = _bool_env(env, "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE", default=True)
        enable_version_write = _bool_env(env, "OPENPROJECT_ENABLE_VERSION_WRITE", default=True)
        enable_board_write = _bool_env(env, "OPENPROJECT_ENABLE_BOARD_WRITE", default=True)
        enable_personal_write = _bool_env(env, "OPENPROJECT_ENABLE_PERSONAL_WRITE", default=False)
        enable_admin_write = _bool_env(env, "OPENPROJECT_ENABLE_ADMIN_WRITE", default=False)
        timeout = _float_env(env, "OPENPROJECT_TIMEOUT", default=12.0, minimum=1.0)
        verify_ssl = _bool_env(env, "OPENPROJECT_VERIFY_SSL", default=True)
        default_page_size = _int_env(
            env,
            "OPENPROJECT_DEFAULT_PAGE_SIZE",
            # 10, not 20: measured OPM lists are ~44% description bytes, so page size
            # is the strongest lever on list context. 10 halves it while still showing
            # a useful chunk on one call; raise OPENPROJECT_DEFAULT_PAGE_SIZE if needed.
            default=10,
            minimum=1,
        )
        max_page_size = _int_env(env, "OPENPROJECT_MAX_PAGE_SIZE", default=50, minimum=1)
        max_results = _int_env(env, "OPENPROJECT_MAX_RESULTS", default=100, minimum=1)
        log_level = _parse_log_level(env.get("OPENPROJECT_LOG_LEVEL"), "OPENPROJECT_LOG_LEVEL", default="WARNING")
        text_limit = _int_env(env, "OPENPROJECT_TEXT_LIMIT", default=DEFAULT_TEXT_LIMIT, minimum=1)
        if text_limit > TEXT_LIMIT_MAX:
            raise ConfigError(f"OPENPROJECT_TEXT_LIMIT must not exceed {TEXT_LIMIT_MAX}.")
        attachment_root = (env.get("OPENPROJECT_ATTACHMENT_ROOT") or "").strip()
        if attachment_root and not Path(attachment_root).expanduser().is_absolute():
            raise ConfigError(
                "OPENPROJECT_ATTACHMENT_ROOT must be an absolute path (e.g. /home/user/uploads "
                "or ~/uploads) — a relative path would resolve against the server's current "
                "working directory, which this phase removes as an implicit fallback."
            )
        max_retries = _int_env(env, "OPENPROJECT_MAX_RETRIES", default=3, minimum=0)
        if max_retries > 10:
            raise ConfigError("OPENPROJECT_MAX_RETRIES must not exceed 10.")
        retry_base_delay = _float_env(env, "OPENPROJECT_RETRY_BASE_DELAY", default=1.0, minimum=0.0)
        retry_max_delay = _float_env(env, "OPENPROJECT_RETRY_MAX_DELAY", default=60.0, minimum=0.0)
        if retry_max_delay < retry_base_delay:
            raise ConfigError("OPENPROJECT_RETRY_MAX_DELAY must be >= OPENPROJECT_RETRY_BASE_DELAY.")

        if default_page_size > max_page_size:
            raise ConfigError("OPENPROJECT_DEFAULT_PAGE_SIZE must not exceed OPENPROJECT_MAX_PAGE_SIZE.")
        if max_page_size > max_results:
            raise ConfigError("OPENPROJECT_MAX_PAGE_SIZE must not exceed OPENPROJECT_MAX_RESULTS.")

        read_flags = {
            "project_read": enable_project_read,
            "work_package_read": enable_work_package_read,
            "membership_read": enable_membership_read,
            "version_read": enable_version_read,
            "board_read": enable_board_read,
            "personal_read": enable_personal_read,
            "admin_read": enable_admin_read,
        }
        write_flags = {
            "project_write": enable_project_write,
            "work_package_write": enable_work_package_write,
            "membership_write": enable_membership_write,
            "version_write": enable_version_write,
            "board_write": enable_board_write,
            "personal_write": enable_personal_write,
            "admin_write": enable_admin_write,
        }
        violations = tool_exposure_violations(read_flags, write_flags)
        if violations:
            _, _, write_env_var, read_env_var = violations[0]
            raise ConfigError(f"{write_env_var}=true requires {read_env_var}=true.")

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
            enable_work_package_read=enable_work_package_read,
            enable_membership_read=enable_membership_read,
            enable_version_read=enable_version_read,
            enable_board_read=enable_board_read,
            enable_personal_read=enable_personal_read,
            enable_admin_read=enable_admin_read,
            hide_project_fields=hide_project_fields,
            hide_work_package_fields=hide_work_package_fields,
            hide_activity_fields=hide_activity_fields,
            hide_custom_fields=hide_custom_fields,
            hidden_fields=hidden_fields,
            enable_project_write=enable_project_write,
            enable_work_package_write=enable_work_package_write,
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
    # so set the level explicitly to make it actually take effect.
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


def _bool_env(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    """`_parse_bool(env.get(name), name, ...)` -- every call site otherwise repeats
    the env var name once to look it up and again for the error message."""
    return _parse_bool(env.get(name), name, default=default)


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


def _int_env(env: Mapping[str, str], name: str, *, default: int, minimum: int) -> int:
    return _parse_int(env.get(name), name, default=default, minimum=minimum)


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


def _float_env(env: Mapping[str, str], name: str, *, default: float, minimum: float) -> float:
    return _parse_float(env.get(name), name, default=default, minimum=minimum)


def _parse_log_level(value: str | None, name: str, *, default: str) -> str:
    if value is None or not value.strip():
        return default
    normalized = value.strip().upper()
    allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    if normalized not in allowed:
        raise ConfigError(f"{name} must be one of: {', '.join(sorted(allowed))}.")
    return normalized
