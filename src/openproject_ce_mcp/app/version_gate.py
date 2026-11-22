"""Shared version-gate error translation.

Package-root shared kernel: pure, dependency-free wrapper used by any app/ Service whose underlying
endpoint only exists from some OpenProject version onward, without creating a layering violation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from .errors import InvalidInputError, NotFoundError

_T = TypeVar("_T")


async def call_version_gated(call: Callable[[], Awaitable[_T]], *, feature: str, floor: str) -> _T:
    """Await `call()`; on `NotFoundError`, say that either the resource or the feature is missing.

    A 404 does not tell a missing resource from a route the instance lacks, so the message names
    both possibilities and the floor. `feature` names what the caller was trying to do (e.g.
    "Meeting sections"); `floor` is the first release that has the endpoint.
    """
    try:
        return await call()
    except NotFoundError as exc:
        raise NotFoundError(
            f"{feature}: not found, or not available on this instance (it requires OpenProject {floor} or newer)."
        ) from exc


async def call_query_version_gated(call: Callable[[], Awaitable[_T]], *, feature: str, floor: str) -> _T:
    """Await `call()`; on `InvalidInputError`, add the version floor to OpenProject's own message.

    For a query filter operator the server does not know yet, OpenProject
    answers 400 InvalidQuery, not 404, and on a new enough instance that same
    error also reports any other invalid filter or sort of the request. The
    server's reason therefore comes first and the floor is only offered as a
    condition, never as the diagnosis.
    """
    try:
        return await call()
    except InvalidInputError as exc:
        hint = f" If this instance is older than OpenProject {floor}, {feature} is the cause: it requires {floor} or newer."
        inner = exc

        def compose(server_text: str) -> str:
            return f"{inner.message_for(server_text)}{hint}"

        raise InvalidInputError(
            f"{exc}{hint}", entries=exc.entries, top=exc.top, compose=compose, rendered=exc.rendered
        ) from exc
