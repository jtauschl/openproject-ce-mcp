# Cursor

<p align="center">
  <img src="../img/cursor.jpg" alt="Cursor artwork for the Cursor MCP guide." width="960">
</p>

Cursor uses the same MCP config shape as Claude Code (`mcpServers` with
`command` + `env`) — only the file location differs.

## Recommended setup

Use `.cursor/mcp.json` in your project root (project-scoped). This allows
different projects to have different OpenProject access and permissions.

## Automatic setup

Run `openproject-ce-mcp configure`, answer the project-scoped gate, and select
Cursor — it writes `.cursor/mcp.json` for you. See
[Installation](installation.md) for installing the package first.

## Manual setup

Create `.cursor/mcp.json`. The structure is identical to every other client
(root key `mcpServers`):

```json
{
  "mcpServers": {
    "openproject": {
      "command": "openproject-ce-mcp",
      "env": {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "replace-with-your-token",
        "OPENPROJECT_READ_PROJECTS": "my-project,other-project",
        "OPENPROJECT_WRITE_PROJECTS": "my-project"
      }
    }
  }
}
```

With a PyPI install the command is simply `openproject-ce-mcp`; source
installs can use the `.venv` binary path. The full set of `env` keys is the
same as every other client — see [`.mcp.json.example`](../.mcp.json.example)
or [Configuration](configuration.md).

## Protect credentials

**`.cursor/mcp.json` holds your API token.**

```bash
chmod 600 .cursor/mcp.json
```

Add `.cursor/mcp.json` to your project's `.gitignore` so it is never committed.

## Reload and verify

Open the command palette and run "Reload Window". Then:

- Under **Settings → MCP**, confirm `openproject` is listed and enabled.
- Ask Cursor to call `list_projects` (or `get_current_user`). A successful reply
  confirms the base URL and token work.

## User-wide setup (alternative)

Use `~/.cursor/mcp.json` (same content, same `chmod 600` credential
protection) to make the server available in all projects instead of one.
Project-scoped is preferred for per-project permissions.

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — global vs. project-scoped, and every client's file layout
- [Configuration](configuration.md) — the full environment variable reference
