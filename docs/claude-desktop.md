# Claude Desktop app

<p align="center">
  <img src="../img/claude.jpg" alt="Claude artwork for the Claude Desktop MCP guide." width="960">
</p>

This guide covers the standalone **Claude Desktop app** (macOS/Windows/Linux
(Beta) — the Linux build officially supports Ubuntu 22.04+ and Debian 12+ on
x64/arm64, with a few feature gaps compared to macOS/Windows). It is a
different program from Claude Code, and it uses its **own** config file —
Claude Desktop does not read the Claude Code config (`~/.claude.json`).

## Recommended setup

Claude Desktop only has a single, user-wide config — every conversation
shares it. There is no project-scoped option here; for per-project
permissions, use Claude Code instead (see [claude.md](claude.md)).

## Automatic setup

Let `openproject-ce-mcp configure` detect the Claude Desktop app and write
this file for you (it registers Claude Desktop through its global config —
Claude Desktop has no project-local config), with only the values you set
(everything else falls back to a safe default and is omitted from the file).
See [Installation](installation.md) for installing the package first.

## Manual setup

1. **Locate the config file** (create it if it does not exist):
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux (Beta):** `~/.config/Claude/claude_desktop_config.json`

   In the app you can open it via **Settings → Developer → Edit Config**.

2. **Add the server:**
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

   If the file already has a `mcpServers` block, add the `openproject` entry
   alongside your existing servers instead of replacing the whole file. With a
   PyPI install the command is simply `openproject-ce-mcp`; source installs can
   use the `.venv` binary path. The full set of `env` keys is the same as every
   other client — see [`.mcp.json.example`](../.mcp.json.example) or
   [Configuration](configuration.md).

## Protect credentials

**This file holds your API token.**

```bash
# macOS
chmod 600 ~/Library/Application\ Support/Claude/claude_desktop_config.json

# Linux (Beta)
chmod 600 ~/.config/Claude/claude_desktop_config.json
```

On Windows, restrict the file to your user via its **Properties → Security**.

## Reload and verify

**Restart Claude Desktop** completely (quit and reopen — a window reload is
not enough). Then:

- Open a new conversation and check the tools/plugins menu for the `openproject`
  server.
- Ask Claude to call `list_projects` (or `get_current_user`). A successful reply
  confirms the base URL and token work.
- If the server does not appear, re-check the file location, that the JSON is
  valid, and that `command` is available on PATH (or is the absolute `.venv` path for a source install).

## Notes

- Claude Desktop and Claude Code use separate config files. If you already
  configured the server in Claude Desktop and want it in Claude Code too, you can
  import it with `claude mcp add-from-claude-desktop`.
- `OPENPROJECT_READ_PROJECTS` accepts comma-separated identifiers, names, or glob patterns: `project-one,team-*`. Use `*` for all visible projects.
- `OPENPROJECT_WRITE_PROJECTS` is the real write gate — the 5 core write-category flags (like `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`) are on by default and do nothing until a project is listed here; set one to `false` to exclude that category instead.

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — global vs. project-scoped, and every client's file layout
- [Configuration](configuration.md) — the full environment variable reference
