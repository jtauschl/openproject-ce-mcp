# Cursor

Cursor uses the same MCP config shape as Claude Code (`mcpServers` with
`command` + `env`) — only the file location differs.

## Setup: Project-scoped (Preferred)

1. **Create `.cursor/mcp.json` in your project root.** Use the `command` path and
   `env` values from the `.mcp.json` the installer generated; the structure is
   identical (root key `mcpServers`). On Windows the `command` path is
   `...\.venv\Scripts\openproject-ce-mcp.exe`; use the exact path the installer printed.
   ```json
   {
     "mcpServers": {
       "openproject": {
         "command": "/absolute/path/to/openproject-ce-mcp/.venv/bin/openproject-ce-mcp",
         "env": {
           "OPENPROJECT_BASE_URL": "https://op.example.com",
           "OPENPROJECT_API_TOKEN": "replace-with-your-token",
           "OPENPROJECT_ALLOWED_PROJECTS_READ": "my-project,other-project",
           "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "my-project"
         }
       }
     }
   }
   ```
   The full set of `env` keys is the same as every other client — see
   [`.mcp.json.example`](../.mcp.json.example) or the [Configuration table](../README.md#configuration).

2. **Protect it if it contains secrets:** `chmod 600 .cursor/mcp.json`.
   **This file holds your API token.** Add `.cursor/mcp.json` to your project's
   `.gitignore` so it is never committed.

3. **Reload:** open the command palette and run "Reload Window", then confirm the
   `openproject` server is enabled under **Settings → MCP**.

## Setup: User-wide

Use `~/.cursor/mcp.json` (same content) to make the server available in all
projects instead of one. Project-scoped is preferred for per-project permissions.

### Verify

- Under **Settings → MCP**, confirm `openproject` is listed and enabled.
- Ask Cursor to call `list_projects` (or `get_current_user`). A successful reply
  confirms the base URL and token work.
