"""Per-tool-call HTTP request counter (the `http_requests` log field).

A `contextvars.ContextVar`, not an instance attribute on `HttpxTransport` or
`OpenProjectClient`: `CountingTransport.handle_async_request`
(`counting_transport.py`) -- the one place every real wire-level HTTP attempt
actually happens, including each individual retry attempt when
`RetryTransport` is layered on top, not just each logical `client.request()`
call -- has no reference to "the current tool call" to attribute a count to.
A contextvar is this codebase's own established idiom for this shape of
request-scoped state.

Counting in its own dedicated `CountingTransport`, installed unconditionally
(not inside `RetryTransport`, which is only installed when
`OPENPROJECT_MAX_RETRIES > 0`), is deliberate: a retried request is a REAL
HTTP request that reached the network, and undercounting it as "1" per
logical operation would misreport the actual request volume a tool call
generated -- and MAX_RETRIES=0 is a valid configuration that must still
count every request it makes.

A plain ContextVar write is invisible across `asyncio.gather`/`create_task`,
since each new Task gets its own COPY of the context, not a shared
reference -- a write inside a gathered coroutine never reaches the caller
that awaited it. Any code path that increments this counter (or writes
`policy_observation`) inside a `gather`-ed coroutine must go through
`context_gather.gather_in_current_context` instead of `asyncio.gather`
directly, or the count silently comes back wrong (typically too low, never
an error) for that tool call. See `context_gather.py`'s own docstring.

Work that outlives or is shared between tool calls (a cache load, the project
directory's scan and lookups) runs in a task that other calls may wait for.
The call that starts such a task owns its requests: `start_owned` runs it in a
copy of the starter's context and hands back the function that takes the
count over, which the starter runs once it stops waiting. A call that only
waits for a task it did not start counts nothing for it, so a request is
counted by exactly one call and never leaks into a concurrent one.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Callable, Coroutine
from contextvars import Context, ContextVar
from functools import partial
from typing import Any, TypeVar

_T = TypeVar("_T")

_count: ContextVar[int] = ContextVar("http_request_count", default=0)


def reset() -> None:
    _count.set(0)


def increment() -> None:
    _count.set(_count.get() + 1)


def current() -> int:
    return _count.get()


def adopt(context: Context, *, since: int) -> None:
    """Add the requests a task counted in its own copy of the context to the caller's count.

    The copy was taken when the caller's count was `since`; only what the task added is taken over,
    so siblings sharing the caller's context keep what they counted."""
    _count.set(_count.get() + context.get(_count, since) - since)


def start_owned(coroutine: Coroutine[Any, Any, _T]) -> tuple[asyncio.Task[_T], Callable[[], None]]:
    """Start a task whose requests belong to the caller that starts it, even when others wait for it.

    The task counts in a copy of the caller's context; the returned callable, run by the caller once it
    has its value (or stopped waiting), takes the count over. A caller that only joins a task somebody
    else started counts nothing for it."""
    context = contextvars.copy_context()
    since = current()
    return asyncio.create_task(coroutine, context=context), partial(adopt, context, since=since)
