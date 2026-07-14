# Codex

<p align="center">
  <img src="../img/codex.jpg" alt="Codex artwork for the Codex MCP guide." width="960">
</p>

## Recommended setup

Use `.codex/config.toml` in your project root (project-scoped). This allows
different projects to have different OpenProject access and permissions.
Codex loads project-scoped config files only when you trust the project. You
do not need the Codex CLI installed for this setup if you use the IDE
extension and edit the config file directly.

## Automatic setup

Run `openproject-ce-mcp configure`, answer the project-scoped gate, and select
Codex — it writes `.codex/config.toml` for you, with only the values you set
(everything else falls back to a safe default and is omitted from the file).
See [Installation](installation.md) for installing the package first.

## Manual setup

Create `.codex/config.toml` in your project root:

```toml
[mcp_servers.openproject]
command = "openproject-ce-mcp"

[mcp_servers.openproject.env]
OPENPROJECT_BASE_URL = "https://op.example.com"
OPENPROJECT_API_TOKEN = "replace-with-your-token"
OPENPROJECT_READ_PROJECTS = "my-project,other-project"
OPENPROJECT_WRITE_PROJECTS = "my-project"
```

With a PyPI install (uv tool / pipx / pip) the `command` is simply
`openproject-ce-mcp` (resolved from your PATH); for a zero-install setup use
`command = "uvx"` with `args = ["openproject-ce-mcp"]`. A source install
instead points at the `.venv` binary (`...\.venv\bin\openproject-ce-mcp`, or
`...\.venv\Scripts\openproject-ce-mcp.exe` on Windows).

The full set of `env` keys is the same as every other client — see
[`.mcp.json.example`](../.mcp.json.example) or [Configuration](configuration.md).

**CLI alternative (optional):** If you have the Codex CLI installed, you can
add the server from the terminal instead. This writes to your shared Codex
configuration:

```bash
codex mcp add openproject \
  --env OPENPROJECT_BASE_URL=https://op.example.com \
  --env OPENPROJECT_API_TOKEN=your-token \
  -- \
  openproject-ce-mcp
```

If you use `codex mcp add`, prefer `--env KEY=VALUE` for server variables.
Plain shell `export`s are session-scoped and are not written into the saved
MCP entry.

## Protect credentials

**`.codex/config.toml` holds your API token.**

```bash
chmod 600 .codex/config.toml
```

Add `.codex/config.toml` to your project's `.gitignore` so it is never committed.

## Reload and verify

In the IDE extension:

- trust the project
- reload the editor window or restart Codex if needed
- confirm the `openproject` server appears in Codex
- confirm MCP tools are available in the session
- ask Codex to call `list_projects` (or `get_current_user`); a successful reply confirms the base URL and token work

If the server doesn't appear immediately, restart Codex or reload the editor window.

---

## User-wide setup (alternative)

If you want to share one OpenProject CE MCP instance across all projects
instead of scoping it per project, use the user-wide `config.toml`:

- File:
  - **Windows:** `%USERPROFILE%\.codex\config.toml`
  - **macOS:** `~/.codex/config.toml`
  - **Linux:** `~/.codex/config.toml`
- **Protect credentials:** `chmod 600 ~/.codex/config.toml` on macOS/Linux; on
  Windows restrict it to your user via **Properties → Security**.

**Example:** Use the same config as above in `~/.codex/config.toml`.

**Note:** All projects share the same credentials and permissions.
Project-scoped setup (above) is the preferred method.

---

## Notes

- Codex supports user-level configuration in `~/.codex/config.toml` and project-scoped overrides in `.codex/config.toml`
- Codex loads project-scoped config files only for trusted projects
- Codex shares MCP configuration between the CLI and the IDE extension
- You do not need the Codex CLI when configuring Codex through the IDE extension
- Treat the CLI flow as optional helper functionality, not as the primary Codex setup path
- Project-scoped setup (`.codex/config.toml`) is preferred for fine-grained project permissions
- `OPENPROJECT_READ_PROJECTS` accepts comma-separated identifiers, names, or glob patterns: `project-one,team-*`. Use `*` for all visible projects
- `OPENPROJECT_WRITE_PROJECTS` is the real write gate — the 5 core write-category flags (like `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`) are on by default and do nothing until a project is listed here; set one to `false` to exclude that category instead

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — global vs. project-scoped, and every client's file layout
- [Configuration](configuration.md) — the full environment variable reference
