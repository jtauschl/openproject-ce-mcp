"""Cleanup helpers for the live integration suite.

A cleanup that fails leaves data on the instance, so it must say so. ``delete_all`` keeps going after a failure,
tolerates only a resource that is already gone, and reports everything else at the end. ``ClientRegistry`` closes
every client a test opened, including one whose ``initialize`` failed. A client that may write outside the test
project exists to create disposable projects, and only an admin token can delete them again, so the registry refuses
to open one for any other token.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol, TypeVar

import httpx
import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

T = TypeVar("T")


class LiveCleanupFailed(AssertionError):
    pass


class _Closable(Protocol):
    async def initialize(self) -> Any: ...

    async def aclose(self) -> None: ...


async def delete_all(label: str, items: Iterable[T], delete: Callable[[T], Awaitable[object]]) -> None:
    leaked = []
    for item in items:
        try:
            await delete(item)
        except NotFoundError:
            continue
        except Exception as exc:
            leaked.append(f"{label} {item!r}: {type(exc).__name__}: {exc}")
    if leaked:
        raise LiveCleanupFailed("Cleanup left data behind:\n" + "\n".join(leaked))


def writes_outside(test_project: str, settings: Any) -> bool:
    return any(pattern.casefold() != test_project.casefold() for pattern in settings.write_projects)


async def token_is_admin(settings: Any) -> bool:
    """OpenProject adds `admin` to `users/me` for an admin only, so its absence means the token is not one."""
    async with httpx.AsyncClient(auth=("apikey", settings.api_token), timeout=settings.timeout) as http:
        response = await http.get(f"{settings.base_url.rstrip('/')}/api/v3/users/me")
    response.raise_for_status()
    return bool(response.json().get("admin"))


def require_admin_for_wide_writes(
    test_project: str, is_admin: Callable[[Any], Awaitable[bool]] = token_is_admin
) -> Callable[[Any], Awaitable[None]]:
    async def check(settings: Any) -> None:
        if writes_outside(test_project, settings) and not await is_admin(settings):
            pytest.skip(
                "The token is not an admin: a client that may write outside the test project creates disposable "
                "projects, and only an admin can delete them, so they would stay on the instance."
            )

    return check


class ClientRegistry:
    def __init__(
        self,
        factory: Callable[[Any], _Closable] = OpenProjectClient,
        *,
        before_open: Callable[[Any], Awaitable[None]] | None = None,
    ) -> None:
        self._factory = factory
        self._before_open = before_open
        self._clients: list[_Closable] = []

    async def open(self, settings: Any) -> Any:
        if self._before_open is not None:
            await self._before_open(settings)
        client = self._factory(settings)
        self._clients.append(client)
        await client.initialize()
        return client

    async def close(self) -> None:
        failures = []
        while self._clients:
            client = self._clients.pop()
            try:
                await client.aclose()
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
        if failures:
            raise LiveCleanupFailed("A live client did not close:\n" + "\n".join(failures))
