from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from . import __version__
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

    mcp = FastMCP("OpenProject CE MCP", json_response=True, lifespan=app_lifespan)
    register_tools(mcp, settings)
    return mcp


def _run_server() -> None:
    settings = Settings.from_env()
    create_app(settings).run(transport="stdio")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openproject-ce-mcp",
        description=(
            "OpenProject Community Edition MCP server. Run with no arguments to "
            "start the MCP stdio server — this is how MCP clients launch it. It "
            "reads its configuration from OPENPROJECT_* environment variables "
            "(see the README)."
        ),
        epilog="Run 'openproject-ce-mcp configure --help' for setup options.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"openproject-ce-mcp {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="{configure}")
    sub.add_parser(
        "configure",
        add_help=False,  # forwarded verbatim to the setup CLI, which owns --help
        help="Register the server with your MCP clients and write .mcp.json.",
    )
    return parser


def _cli_tokens(parser: argparse.ArgumentParser) -> frozenset[str]:
    """Tokens that mean "this is a CLI invocation" — derived from the parser itself.

    A single source of truth: the parser's subcommand names plus its top-level
    option strings. Adding a subcommand or flag to _build_parser() automatically
    updates dispatch, so the two can't drift. Any first arg NOT in this set
    (including no args, or an unexpected flag a client passes) starts the server
    so existing client launches are never intercepted.
    """
    tokens: set[str] = set()
    for action in parser._actions:
        tokens.update(action.option_strings)  # -h/--help, -V/--version
        if action.choices:  # the subparsers action → {configure}
            tokens.update(action.choices)
    return frozenset(tokens)


def main() -> None:
    """Console entry point.

    With no arguments (how MCP clients launch it) this runs the stdio server —
    unchanged behaviour. ``configure`` hands off to the interactive setup CLI;
    ``--help``/``--version`` print top-level info via argparse. Anything else is
    treated as a server launch so a client passing an unexpected flag still starts
    the server rather than erroring out.
    """
    parser = _build_parser()
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg not in _cli_tokens(parser):
        _run_server()
        return

    if arg == "configure":
        from .setup_cli import main as setup_main

        setup_main(sys.argv[2:])
        return

    # --help / --version: let argparse render and exit.
    parser.parse_args(sys.argv[1:])


if __name__ == "__main__":
    main()
