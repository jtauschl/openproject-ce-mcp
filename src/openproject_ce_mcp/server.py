from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from . import __version__
from .client import OpenProjectClient
from .config import Settings, configure_logging
from .tools import register_tools

# Server instructions surfaced to the connecting agent in the MCP `initialize`
# response. This is the canonical, spec-standard channel (optional since protocol
# 2024-11-05) for telling the agent up front what this server is and where its
# hard limits are — so it does not waste turns attempting operations the API
# structurally cannot do. Kept as Markdown, short and actionable.
CE_INSTRUCTIONS = """\
# OpenProject Community Edition MCP

This server wraps a single **OpenProject Community Edition (CE)** instance over its
REST API v3. Community Edition, not Enterprise — plan accordingly.

## Not creatable or modifiable via the API (do not attempt)

Work-package **types**, **statuses**, **workflows**, enabled **modules**, and
custom-field **definitions** are configured only in the OpenProject web admin UI.
The REST API exposes no writable endpoint for them (`POST /api/v3/types` → 404),
and this is not a permission issue — an admin token gets 404 too. Read them with
`list_types` / `list_statuses`, but do not try to create or change them here.

## Enterprise-only features are absent

Portfolios, Programs, Placeholder Users, Budgets, Custom Actions, and Baseline
Comparisons are Enterprise Edition features and are not available on this instance.

## Capabilities: what the tools say, not what `list_capabilities` says

`list_capabilities` / `get_instance_configuration` report OpenProject's own
per-user *action grants* and feature flags — they are informational and are **not**
the source of truth for what you can do here. A missing capability does **not** mean
an operation is impossible: e.g. deleting a work package is not listed as a
capability yet the `delete_work_package` tool works. **The registered MCP tools are
the authority** — if a tool exists it is allowed; if it does not, it is not.

## Trimmed responses and field selection

List and write results are trimmed for context economy: list results omit the
derivable `count`/`truncated` fields, and a confirmed write omits the echoed
request `payload` (its normalized `result` carries the same information). To read
only the fields you need, pass `select` (a list of field names) to
`list_work_packages` / `search_work_packages` / `list_projects` / `list_users`;
an invalid name returns the allowed set.

## Clearing an assigned field

On `update_work_package` and `update_project`, pass the string `"none"` to unassign
a nullable association rather than change it: work-package `assignee`, `responsible`,
`version`, `parent`, `category`, `project_phase`, and project `parent`. Omitting a
field leaves it unchanged; `"none"` explicitly clears it. Required fields (type,
status, subject, project) cannot be cleared.

## Some metadata tools are opt-in

A set of rarely-needed metadata/reference tools (the `get_query_*` schema tools,
`render_text`, `get_custom_option`, `list_help_texts` / `get_help_text`,
`list_working_days` / `list_non_working_days`) is gated behind
`OPENPROJECT_ENABLE_METADATA_TOOLS=true` to keep them out of the default tool set.
If one is not registered, it is intentionally disabled here, not missing — enabling
that flag exposes them.
"""


def _fetch_active_feature_flags(settings: Settings) -> list[str] | None:
    """Best-effort, one-shot fetch of the instance's active feature flags.

    Returns the flags, or ``None`` if the instance cannot be reached / read. Must
    never block or crash server start — same fault-tolerant philosophy as
    ``OpenProjectClient.initialize`` (which swallows startup errors).
    """

    async def _run() -> list[str] | None:
        client = OpenProjectClient(settings)
        try:
            config = await client.get_instance_configuration()
            return list(config.active_feature_flags)
        finally:
            await client.aclose()

    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001 — never let handshake enrichment break startup
        logging.getLogger(__name__).debug("instance configuration fetch failed", exc_info=True)
        return None


def _build_instructions(settings: Settings) -> str:
    """Static CE guidance, enriched with the instance's live feature flags when reachable."""
    flags = _fetch_active_feature_flags(settings)
    if not flags:
        return CE_INSTRUCTIONS
    flag_list = ", ".join(sorted(flags))
    return f"{CE_INSTRUCTIONS}\n## Active feature flags on this instance\n\n{flag_list}\n"


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

    # The feature-flag fetch must happen before FastMCP construction: `instructions`
    # is passed to the constructor and injected into the initialize response, while
    # `app_lifespan` only runs later on client connect — too late to shape it.
    instructions = _build_instructions(settings)

    # log_level MUST be passed here: FastMCP.__init__ runs configure_logging() with
    # its own default (INFO) and installs a stderr handler, so omitting it lets the
    # SDK win the race and our OPENPROJECT_LOG_LEVEL never takes effect (OPM-62).
    mcp = FastMCP(
        "OpenProject CE MCP",
        instructions=instructions,
        json_response=True,
        lifespan=app_lifespan,
        log_level=settings.log_level,
    )
    # serverInfo.version (MCP MUST): FastMCP has no `version` constructor kwarg, so
    # set it on the low-level server. Without this the handshake reports the SDK's
    # own version instead of ours. Read at `initialize`, so setting it here is early
    # enough.
    mcp._mcp_server.version = __version__
    # Force the root logger level explicitly. basicConfig (used by both FastMCP and
    # our configure_logging) is a no-op once a handler exists, so an explicit
    # setLevel is what actually holds the configured level regardless of install
    # order — this is the real fix for OPM-62.
    logging.getLogger().setLevel(getattr(logging, settings.log_level))
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
