"""Shared exception vocabulary.

Package-root shared kernel: importable from every layer (policies, transport, ports,
adapters, resolvers, services) without creating a layering violation, since it sits
outside the layer hierarchy entirely, like `config.py`/`models.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

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


class AuthenticationError(OpenProjectError):
    """Authentication failed."""


class PermissionDeniedError(OpenProjectError):
    """Access to the resource was denied."""


class NotFoundError(OpenProjectError):
    """The requested resource does not exist."""


class InvalidInputError(OpenProjectError):
    """A provided tool or request input is invalid."""


class OpenProjectServerError(OpenProjectError):
    """OpenProject returned an unexpected failure."""


class TransportError(OpenProjectError):
    """The request could not reach OpenProject safely."""


class ProjectLinkPrefixError(OpenProjectError):
    """OpenProject links its projects under a different path than the configured base URL."""
