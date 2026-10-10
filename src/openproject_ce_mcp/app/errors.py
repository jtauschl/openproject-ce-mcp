"""Shared exception vocabulary.

Package-root shared kernel: importable from every layer (policies, transport, ports,
adapters, resolvers, services) without creating a layering violation, since it sits
outside the layer hierarchy entirely, like `config.py`/`models.py`.

Every leaf exception carries its own `code`/`layer` class attributes -- the
single source of truth for OPM-2708's agent-facing error codes and OPM-2709's
structured-logging `layer` field. This replaces a separate
type-to-code/type-to-layer lookup table (which `tools_runtime.py` used to
maintain as `_ERROR_CATEGORY`): a new exception class that forgets to declare
`code`/`layer` is caught at class-definition time (by `__init_subclass__`
below), not silently inherited from its parent -- a type checker alone
cannot catch this (a subclass that omits both ClassVars type-checks fine and
just inherits the parent's values, which would be actively misleading rather
than an error), so the check is enforced at runtime, once, when the module
defining the subclass is imported. `layer` values follow ARCH-05's
three-tier translation scheme (transport / HTTP-status-mapper /
business-domain), plus two values for exceptions that never reach that
scheme at all: "validation" (a bare ValueError from a tool-body validator,
never an OpenProjectError) and "internal" (the sanitization backstop for a
genuinely unexpected bug).
"""

from __future__ import annotations

from typing import ClassVar


class OpenProjectError(Exception):
    """Base error for safe OpenProject failures."""

    code: ClassVar[str] = "OPENPROJECT_UNAVAILABLE"
    layer: ClassVar[str] = "http_mapper"

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "code" not in cls.__dict__ or "layer" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must declare its own `code`/`layer` ClassVar "
                "overrides -- inheriting them silently from a parent exception "
                "class is not allowed, since a copy-pasted subclass that forgot "
                "to change them would otherwise type-check and run without error."
            )


class AuthenticationError(OpenProjectError):
    """Authentication failed."""

    code: ClassVar[str] = "AUTHENTICATION_FAILED"
    layer: ClassVar[str] = "http_mapper"


class PermissionDeniedError(OpenProjectError):
    """Access to the resource was denied. Base class -- prefer a subclass
    below at every new raise site; the bare base is only a fallback for
    catch sites written before the subclasses existed."""

    code: ClassVar[str] = "PROJECT_SCOPE_DENIED"
    layer: ClassVar[str] = "policy"


class ProjectScopeDeniedError(PermissionDeniedError):
    """Denied by the OPENPROJECT_READ_PROJECTS/OPENPROJECT_WRITE_PROJECTS
    project allowlist -- the caller is authenticated and this deployment
    allows this kind of operation in general, but not against this
    particular project."""

    code: ClassVar[str] = "PROJECT_SCOPE_DENIED"
    layer: ClassVar[str] = "policy"


class CapabilityDisabledError(PermissionDeniedError):
    """Denied by an OPENPROJECT_ENABLE_*_READ/_WRITE capability flag -- this
    deployment has this entire category of operation turned off, independent
    of which project is targeted."""

    code: ClassVar[str] = "CAPABILITY_DISABLED"
    layer: ClassVar[str] = "policy"


class OpenProjectPermissionDeniedError(PermissionDeniedError):
    """OpenProject itself returned 403 for an authenticated, in-scope
    request -- a permissions problem on the OpenProject side (e.g. the
    underlying API token's role lacks a permission), not something this
    server's own configuration controls."""

    code: ClassVar[str] = "OPENPROJECT_PERMISSION_DENIED"
    layer: ClassVar[str] = "http_mapper"


class NotFoundError(OpenProjectError):
    """The requested resource does not exist."""

    code: ClassVar[str] = "RESOURCE_NOT_FOUND"
    layer: ClassVar[str] = "http_mapper"


class InvalidInputError(OpenProjectError):
    """A provided tool or request input is invalid."""

    code: ClassVar[str] = "VALIDATION_FAILED"
    layer: ClassVar[str] = "http_mapper"


class ConflictError(OpenProjectError):
    """The request conflicts with the resource's current state (e.g. an
    optimistic-locking lockVersion mismatch)."""

    code: ClassVar[str] = "CONFLICT"
    layer: ClassVar[str] = "http_mapper"


class RateLimitedError(OpenProjectError):
    """OpenProject is rate-limiting this client."""

    code: ClassVar[str] = "RATE_LIMITED"
    layer: ClassVar[str] = "http_mapper"


class OpenProjectServerError(OpenProjectError):
    """OpenProject returned an unexpected failure."""

    code: ClassVar[str] = "OPENPROJECT_UNAVAILABLE"
    layer: ClassVar[str] = "http_mapper"


class TransportError(OpenProjectError):
    """The request could not reach OpenProject safely."""

    code: ClassVar[str] = "NETWORK_ERROR"
    layer: ClassVar[str] = "transport"


class ProjectLinkPrefixError(OpenProjectError):
    """OpenProject links its projects under a different path than the configured base URL."""

    code: ClassVar[str] = "CONFIGURATION_ERROR"
    layer: ClassVar[str] = "policy"
