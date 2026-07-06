from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when environment configuration is missing or invalid."""


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
    "board": "OPENPROJECT_HIDE_BOARD_FIELDS",
    "current_user": "OPENPROJECT_HIDE_CURRENT_USER_FIELDS",
    "instance_configuration": "OPENPROJECT_HIDE_INSTANCE_CONFIGURATION_FIELDS",
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
    allowed_projects: tuple[str, ...] = ()
    allowed_write_projects: tuple[str, ...] = ()
    allowed_write_projects_configured: bool = False
    enable_work_package_read: bool = True
    enable_project_read: bool = True
    enable_membership_read: bool = True
    enable_version_read: bool = True
    enable_board_read: bool = True
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
    enable_admin_write: bool = False
    auto_confirm_write: bool = False
    auto_confirm_delete: bool = False
    attachment_root: str = ""

    def read_enabled(self, scope: str) -> bool:
        return {
            "work_package": self.enable_work_package_read,
            "project": self.enable_project_read,
            "membership": self.enable_membership_read,
            "role": self.enable_membership_read,
            "principal": self.enable_membership_read,
            "version": self.enable_version_read,
            "board": self.enable_board_read,
        }.get(scope, True)

    def write_enabled(self, scope: str) -> bool:
        return {
            "work_package": self.enable_work_package_write,
            "project": self.enable_project_write,
            "membership": self.enable_membership_write,
            "version": self.enable_version_write,
            "board": self.enable_board_write,
        }.get(scope, False)

    @property
    def project_write_scope_configured(self) -> bool:
        return self.allowed_write_projects_configured or bool(self.allowed_write_projects)

    @property
    def project_write_scope_allows_none(self) -> bool:
        return self.allowed_write_projects_configured and not self.allowed_write_projects

    @property
    def api_base_url(self) -> str:
        return f"{self.base_url}/api/v3"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = environ or os.environ
        base_url = _parse_base_url(env.get("OPENPROJECT_BASE_URL"))
        api_token = _require_non_empty(env.get("OPENPROJECT_API_TOKEN"), "OPENPROJECT_API_TOKEN")
        allowed_projects = _parse_csv(
            env.get("OPENPROJECT_ALLOWED_PROJECTS_READ") or env.get("OPENPROJECT_ALLOWED_PROJECTS")
        )
        allowed_write_projects_configured = "OPENPROJECT_ALLOWED_PROJECTS_WRITE" in env
        allowed_write_projects = _parse_csv(env.get("OPENPROJECT_ALLOWED_PROJECTS_WRITE"))
        enable_work_package_read = _parse_bool(
            env.get("OPENPROJECT_ENABLE_WORK_PACKAGE_READ"),
            "OPENPROJECT_ENABLE_WORK_PACKAGE_READ",
            default=True,
        )
        enable_project_read = _parse_bool(
            env.get("OPENPROJECT_ENABLE_PROJECT_READ"),
            "OPENPROJECT_ENABLE_PROJECT_READ",
            default=True,
        )
        enable_membership_read = _parse_bool(
            env.get("OPENPROJECT_ENABLE_MEMBERSHIP_READ"),
            "OPENPROJECT_ENABLE_MEMBERSHIP_READ",
            default=True,
        )
        enable_version_read = _parse_bool(
            env.get("OPENPROJECT_ENABLE_VERSION_READ"),
            "OPENPROJECT_ENABLE_VERSION_READ",
            default=True,
        )
        enable_board_read = _parse_bool(
            env.get("OPENPROJECT_ENABLE_BOARD_READ"),
            "OPENPROJECT_ENABLE_BOARD_READ",
            default=True,
        )
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
        enable_admin_write = _parse_bool(
            env.get("OPENPROJECT_ENABLE_ADMIN_WRITE"),
            "OPENPROJECT_ENABLE_ADMIN_WRITE",
            default=False,
        )
        auto_confirm_write = _parse_bool(
            env.get("OPENPROJECT_AUTO_CONFIRM_WRITE"),
            "OPENPROJECT_AUTO_CONFIRM_WRITE",
            default=False,
        )
        auto_confirm_delete = _parse_bool(
            env.get("OPENPROJECT_AUTO_CONFIRM_DELETE"),
            "OPENPROJECT_AUTO_CONFIRM_DELETE",
            default=auto_confirm_write,  # inherit from auto_confirm_write if not set
        )
        timeout = _parse_float(env.get("OPENPROJECT_TIMEOUT"), "OPENPROJECT_TIMEOUT", default=12.0, minimum=1.0)
        verify_ssl = _parse_bool(env.get("OPENPROJECT_VERIFY_SSL"), "OPENPROJECT_VERIFY_SSL", default=True)
        default_page_size = _parse_int(
            env.get("OPENPROJECT_DEFAULT_PAGE_SIZE"),
            "OPENPROJECT_DEFAULT_PAGE_SIZE",
            default=20,
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
        attachment_root = (env.get("OPENPROJECT_ATTACHMENT_ROOT") or "").strip()

        if default_page_size > max_page_size:
            raise ConfigError("OPENPROJECT_DEFAULT_PAGE_SIZE must not exceed OPENPROJECT_MAX_PAGE_SIZE.")
        if max_page_size > max_results:
            raise ConfigError("OPENPROJECT_MAX_PAGE_SIZE must not exceed OPENPROJECT_MAX_RESULTS.")

        return cls(
            base_url=base_url,
            api_token=api_token,
            timeout=timeout,
            verify_ssl=verify_ssl,
            default_page_size=default_page_size,
            max_page_size=max_page_size,
            max_results=max_results,
            log_level=log_level,
            allowed_projects=allowed_projects,
            allowed_write_projects=allowed_write_projects,
            allowed_write_projects_configured=allowed_write_projects_configured,
            enable_project_read=enable_project_read,
            enable_membership_read=enable_membership_read,
            enable_work_package_read=enable_work_package_read,
            enable_version_read=enable_version_read,
            enable_board_read=enable_board_read,
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
            enable_admin_write=enable_admin_write,
            auto_confirm_write=auto_confirm_write,
            auto_confirm_delete=auto_confirm_delete,
            attachment_root=attachment_root,
        )


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.WARNING)
    logging.basicConfig(
        level=numeric_level,
        format="%(levelname)s %(name)s %(message)s",
    )


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
