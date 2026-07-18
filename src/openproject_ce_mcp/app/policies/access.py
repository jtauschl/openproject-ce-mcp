"""Read/write scope-gate policy (ADR 0001). Pure, no I/O."""

from __future__ import annotations

from ...config import READ_SCOPE_ENV_VAR, Settings
from ..errors import PermissionDeniedError

_WRITE_SCOPE_ENV_VAR = {
    "project": "OPENPROJECT_ENABLE_PROJECT_WRITE",
    "work_package": "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE",
    "membership": "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE",
    "version": "OPENPROJECT_ENABLE_VERSION_WRITE",
    "board": "OPENPROJECT_ENABLE_BOARD_WRITE",
    "personal": "OPENPROJECT_ENABLE_PERSONAL_WRITE",
    "admin": "OPENPROJECT_ENABLE_ADMIN_WRITE",
}


def ensure_write_enabled(scope: str, *, settings: Settings) -> None:
    if settings.write_enabled(scope):
        return
    scope_env = _WRITE_SCOPE_ENV_VAR.get(scope, "the corresponding write-group setting")
    raise PermissionDeniedError(
        f"OpenProject {scope.replace('_', ' ')} write support is disabled. "
        f"Set {scope_env}=true to allow confirmed writes."
    )


def ensure_read_enabled(scope: str, *, settings: Settings) -> None:
    if settings.read_enabled(scope):
        return
    env_var = READ_SCOPE_ENV_VAR.get(scope, "the relevant OPENPROJECT_ENABLE_*_READ setting")
    raise PermissionDeniedError(
        f"OpenProject {scope.replace('_', ' ')} read support is disabled. Set {env_var}=true to allow reads."
    )
