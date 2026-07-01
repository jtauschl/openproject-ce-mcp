from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from .client import OpenProjectClient
from .config import Settings, configure_logging
from .tools import register_tools


@dataclass(slots=True)
class AppContext:
    settings: Settings
    client: OpenProjectClient


def create_app(settings: Settings) -> FastMCP:
    @asynccontextmanager
    async def app_lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
        configure_logging(settings.log_level)
        client = OpenProjectClient(settings)
        await client.initialize()
        try:
            yield AppContext(settings=settings, client=client)
        finally:
            await client.aclose()

    mcp = FastMCP("OpenProject MCP", json_response=True, lifespan=app_lifespan)
    register_tools(mcp, settings)
    return mcp


def main() -> None:
    settings = Settings.from_env()
    create_app(settings).run(transport="stdio")


if __name__ == "__main__":
    main()
