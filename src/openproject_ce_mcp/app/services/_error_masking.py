"""A server error as shown to the caller, rendered by the entity of the service that raised it.

The transport already made the text generic while any hide setting is active (`transport/errors.py`); it kept the
entries the server named. A service knows its entity, so it renders them again here: an entry that names a hidden
field is replaced by a fixed sentence, every other entry keeps its message, so the caller still learns the
visible reason (`policies/error_fields.py` judges an entry).

Functions and a class decorator only, in an underscore-prefixed module: every public class under app/services/
must be named `*Service`/`*Resolver`.
"""

from __future__ import annotations

import dataclasses
import functools
import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from ...config import Settings
from ..errors import GENERIC_HIDDEN_FIELD, OpenProjectError, ServerErrorEntry, render_entries
from ..form_result import ValidationFailure
from ..policies import hidden_fields
from ..policies.error_fields import error_entry_hidden

_ServiceT = TypeVar("_ServiceT", bound=type)


def redacted_server_error(
    exc: OpenProjectError, *, entity: str, settings: Settings, names: Mapping[str, str] | None = None
) -> OpenProjectError:
    """`exc` rendered without the entries of `entity` that name a hidden field, as a new error of the same class
    (`from` chain, entries and composition kept). Nothing happens while no hide is active, for an error without
    entries and for one a service already rendered: the innermost render, which had the schema `names`, wins."""
    if exc.rendered or not exc.entries or not hidden_fields.any_hide_active(settings):
        return exc
    text = render_entries(
        exc.entries,
        top=exc.top,
        hidden=lambda entry: error_entry_hidden(entry, entity=entity, settings=settings, names=names),
    )
    rendered = type(exc)(exc.message_for(text), entries=exc.entries, top=exc.top, compose=exc.compose, rendered=True)
    rendered.__cause__ = exc.__cause__
    rendered.__traceback__ = exc.__traceback__
    return rendered


def redacted_validation_errors(
    errors: dict[str, ValidationFailure], *, entity: str, settings: Settings, names: Mapping[str, str] | None = None
) -> dict[str, ValidationFailure]:
    """The `validation_errors` of a rejected form as shown: an error whose attribute names a hidden field keeps its
    key and error classes, so the write stays explainable, but not its text, which names the field
    (`Secret can't be blank`). The rule is the one of a server error entry (`policies/error_fields.py`)."""
    if not errors or not hidden_fields.any_hide_active(settings):
        return errors
    return {
        key: dataclasses.replace(failure, message=GENERIC_HIDDEN_FIELD)
        if error_entry_hidden(
            ServerErrorEntry(attribute=key, code=None, message=failure.message),
            entity=entity,
            settings=settings,
            names=names,
        )
        else failure
        for key, failure in errors.items()
    }


def redacted_server_errors(entity: str) -> Callable[[_ServiceT], _ServiceT]:
    """Class decorator: every public async method of the service renders a server error that propagates out of it
    by `entity` (the service's own), so a method written later is covered too."""

    def decorate(cls: _ServiceT) -> _ServiceT:
        def wrap(method: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            @functools.wraps(method)
            async def rendered(self: Any, *args: Any, **kwargs: Any) -> Any:
                try:
                    return await method(self, *args, **kwargs)
                except OpenProjectError as exc:
                    redacted = redacted_server_error(exc, entity=entity, settings=self._settings)
                    if redacted is exc:
                        raise
                    raise redacted from exc.__cause__

            return rendered

        for name, member in list(vars(cls).items()):
            if not name.startswith("_") and inspect.iscoroutinefunction(member):
                setattr(cls, name, wrap(member))
        return cls

    return decorate
