# Claude

<p align="center">
  <img src="../img/claude.jpg" alt="Claude artwork for the Claude MCP guide." width="960">
</p>

## Recommended setup

Use `.mcp.json` in your project root (project-scoped). This allows different
projects to have different OpenProject access and permissions. Prefer this
over the user-wide alternative below unless you intentionally want one
OpenProject server shared across every project — see
[global vs. project-scoped](clients.md#global-vs-project-scoped).

## Automatic setup

Run `openproject-ce-mcp configure`, answer the project-scoped gate, and select
Claude Code — it writes `.mcp.json` for you, with only the values you set
(everything else falls back to a safe default and is omitted from the file).
See [Installation](installation.md) for installing the package first.

## Manual setup

Create `.mcp.json` in your project root:

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

With a PyPI install (uv tool / pipx / pip) the `command` is simply
`openproject-ce-mcp` (resolved from your PATH); for a zero-install setup use
`"command": "uvx"` with `"args": ["openproject-ce-mcp"]`. A source install
instead points at the `.venv` binary (`...\.venv\bin\openproject-ce-mcp`, or
`...\.venv\Scripts\openproject-ce-mcp.exe` on Windows).

The full set of `env` keys is the same as every other client — see
[`.mcp.json.example`](../.mcp.json.example) or [Configuration](configuration.md).

## Protect credentials

**`.mcp.json` holds your API token.**

```bash
chmod 600 .mcp.json
```

Add `.mcp.json` to your project's `.gitignore` so it is never committed.

## Reload and verify

Restart Claude Code, or run "Developer: Reload Window" from the command
palette (**Cmd+Shift+P** on macOS, **Ctrl+Shift+P** on Windows/Linux). Then:

- The `openproject` server appears in Claude Code's MCP server list (`/mcp`).
- Ask Claude to call `list_projects` (or `get_current_user`). A successful call returns your projects (or your account), which confirms the base URL and token work.
- If nothing appears, check that `command` is available on PATH (or is the absolute `.venv` path for a source install) and that `.mcp.json` is in the folder Claude Code opened as the project root.

---

## User-wide setup (alternative)

If you want to share one OpenProject CE MCP instance across all projects
instead of scoping it per project, use the user-wide config in your home
directory:

- File:
  - **Windows:** `%USERPROFILE%\.claude.json`
  - **macOS:** `~/.claude.json`
  - **Linux:** `~/.claude.json`
- **Protect credentials:** `chmod 600 ~/.claude.json` on macOS/Linux; on
  Windows restrict it to your user via **Properties → Security**.

**Example:**
```json
{
  "mcpServers": {
    "openproject": {
      "command": "openproject-ce-mcp",
      "env": {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "replace-with-your-token",
        "OPENPROJECT_READ_PROJECTS": "*",
        "OPENPROJECT_WRITE_PROJECTS": ""
      }
    }
  }
}
```

The full set of `env` keys is the same as every other client — see
[`.mcp.json.example`](../.mcp.json.example) or [Configuration](configuration.md).

**Note:** All projects share the same credentials and permissions.
Project-scoped setup (above) is the preferred method.

---

## Notes

- After changing the config, reload MCP servers: run "Developer: Reload Window" from the command palette (**Cmd+Shift+P** on macOS, **Ctrl+Shift+P** on Windows/Linux)
- `OPENPROJECT_READ_PROJECTS` accepts comma-separated identifiers, names, or glob patterns: `project-one,team-*`. Use `*` for all visible projects
- `OPENPROJECT_WRITE_PROJECTS` is the real write gate — the 5 core write-category flags (like `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`) are on by default and do nothing until a project is listed here; set one to `false` to exclude that category instead

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — global vs. project-scoped, and every client's file layout
- [Configuration](configuration.md) — the full environment variable reference
