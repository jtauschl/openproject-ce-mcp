"""Caches for responses that the server can change but rarely does.

Every cache here lives on one client, so it holds what one configured token may see. Nothing is
cached forever: an administrator who edits statuses, priorities or the configuration, or a project
that is renamed, is noticed within `FRESHNESS_SECONDS` without a restart. A failed load is never
remembered; a load that finds nothing is, when the loader returns `None` for it.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Generic, TypeVar

from .. import http_request_counter

FRESHNESS_SECONDS = 300.0

K = TypeVar("K")
V = TypeVar("V")


class TtlCache(Generic[K, V]):
    """A bounded memory of lookups that expires, for values the server can change but rarely does.
    Reads and writes are not locked: the event loop is the only caller, and a lost write costs one
    repeated request."""

    def __init__(self, *, ttl_seconds: float, max_entries: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K) -> tuple[V] | None:
        """The remembered value in a one-tuple (a remembered None is not a miss), or None when the
        key is unknown or its entry has expired."""
        entry = self._entries.get(key)
        if entry is None or self._clock() - entry[0] > self._ttl_seconds:
            return None
        self._entries.move_to_end(key)
        return (entry[1],)

    def put(self, key: K, value: V) -> None:
        self._entries[key] = (self._clock(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)


class LoadingCache(Generic[K, V]):
    """A `TtlCache` that also loads: callers that ask for a key while its load is in flight share
    that one load, and at most `max_concurrent` loads run at once."""

    def __init__(
        self,
        *,
        ttl_seconds: float = FRESHNESS_SECONDS,
        max_entries: int,
        max_concurrent: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cache: TtlCache[K, V] = TtlCache(ttl_seconds=ttl_seconds, max_entries=max_entries, clock=clock)
        self._slots = asyncio.Semaphore(max_concurrent) if max_concurrent else None
        self._in_flight: dict[K, asyncio.Task[V]] = {}

    async def get(self, key: K, load: Callable[[], Awaitable[V]]) -> V:
        """The remembered value, or the result of `load()`, which is remembered when it returns. A
        failure reaches every caller that waited for it and is not remembered."""
        remembered = self._cache.get(key)
        if remembered is not None:
            return remembered[0]
        task = self._in_flight.get(key)
        if task is not None:
            return await asyncio.shield(task)
        task, adopt_requests = http_request_counter.start_owned(self._load(key, load))
        self._in_flight[key] = task
        task.add_done_callback(partial(self._settled, key))
        try:
            return await asyncio.shield(task)
        finally:
            adopt_requests()

    async def _load(self, key: K, load: Callable[[], Awaitable[V]]) -> V:
        if self._slots is None:
            value = await load()
        else:
            async with self._slots:
                value = await load()
        self._cache.put(key, value)
        return value

    def _settled(self, key: K, task: asyncio.Task[V]) -> None:
        if self._in_flight.get(key) is task:
            del self._in_flight[key]
        if not task.cancelled():
            task.exception()  # read here too, so a failure no caller is left to await is not reported as lost

    def __len__(self) -> int:
        return len(self._cache)


class CachedValue(Generic[V]):
    """One remembered value, such as the list of statuses."""

    def __init__(self, *, ttl_seconds: float = FRESHNESS_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._cache: LoadingCache[None, V] = LoadingCache(ttl_seconds=ttl_seconds, max_entries=1, clock=clock)

    async def get(self, load: Callable[[], Awaitable[V]]) -> V:
        return await self._cache.get(None, load)
