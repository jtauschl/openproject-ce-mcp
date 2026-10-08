"""Errors a tool reports to the calling agent.

The MCP SDK passes a ToolError's text through to the agent and logs it as an
anticipated failure; since mcp 2.1 any other exception reaches the agent only
as "Error executing tool <name>" and is logged as a crash. The builtin bases
keep the Python-side contract: ValueError for rejected input, RuntimeError for
a failed call.
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError


class ToolInputError(ToolError, ValueError):
    """Tool input rejected before or by OpenProject, tagged with its category."""


class ToolCallError(ToolError, RuntimeError):
    """OpenProject call that failed, tagged with its category."""
