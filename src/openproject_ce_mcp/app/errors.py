"""Shared exception vocabulary.

Package-root shared kernel: importable from every layer (policies, transport, ports,
adapters, resolvers, services) without creating a layering violation, since it sits
outside the layer hierarchy entirely, like `config.py`/`models.py`.

Every leaf exception carries its own `code`/`layer` class attributes -- the
single source of truth for the agent-facing error codes and the
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

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import ClassVar

GENERIC_REJECTION = "OpenProject rejected the request."
GENERIC_HIDDEN_FIELD = "A field hidden by the hide settings is invalid."
# Error classes whose text names no field, judged by code, so they stay readable while the text of every other
# server error is generic: a stale `lockVersion` (`UpdateConflict`, a constant sentence; the server's other `Conflict`
# call sites pass static texts that name no field either).
VERBATIM_CODES = frozenset({"UpdateConflict"})


@dataclass(frozen=True)
class ServerErrorEntry:
    """One error the server answered: the API attribute it names (`_embedded.details.attribute`), its error
    identifier and its message (localized and free text, so only the attribute can be judged)."""

    attribute: str | None
    code: str | None
    message: str


def render_entries(
    entries: Iterable[ServerErrorEntry], *, top: str = "", hidden: Callable[[ServerErrorEntry], bool] | None = None
) -> str:
    """The text of a server error, `Top (m1; m2)` for several entries and the message alone for one, as the
    transport has always built it. An entry `hidden` judges is replaced: an attributed one by a fixed sentence
    that names no field, an attribute-less one by the generic rejection."""
    shown = [
        (GENERIC_HIDDEN_FIELD if entry.attribute else GENERIC_REJECTION)
        if hidden is not None and hidden(entry)
        else entry.message
        for entry in entries
    ]
    shown = [message for message in (item.strip() for item in shown) if message]
    if not shown:
        return top
    details = "; ".join(shown)
    return f"{top} ({details})" if top else details


class OpenProjectError(Exception):
    """Base error for safe OpenProject failures.

    A server error carries what the server named: `entries` (one per error object) and the wrapper message
    `top` of a MultipleErrors answer. `compose` maps the server's text to the full message (our own words
    around it: the 403 sentence, the version gate hint), so the text is `compose(render_entries(entries, top))`
    and a service that knows the entity can render it again without the entries of a hidden field.
    `rendered` marks an error a service already rendered, so an outer service does not render it again."""

    def __init__(
        self,
        *args: object,
        entries: tuple[ServerErrorEntry, ...] = (),
        top: str = "",
        compose: Callable[[str], str] | None = None,
        rendered: bool = False,
    ) -> None:
        super().__init__(*args)
        self.entries = entries
        self.top = top
        self.compose = compose
        self.rendered = rendered

    def message_for(self, server_text: str) -> str:
        return self.compose(server_text) if self.compose is not None else server_text

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
