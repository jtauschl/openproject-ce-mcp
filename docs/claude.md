# Claude

<p align="center">
  <img src="../img/claude.jpg" alt="Claude artwork for the Claude MCP guide." width="960">
</p>

## Recommended setup

Claude Code defines three MCP installation scopes: **Local** (the default —
private to you, tied to this project directory, stored in `~/.claude.json`),
**Project** (`.mcp.json` — meant to be committed and shared with your team),
and **User** (`~/.claude.json` — shared across every project). For a private
credential like an OpenProject API token, Claude Code's own recommendation is
**Local scope**. Register the server with:

```bash
claude mcp add \
  --env OPENPROJECT_BASE_URL=https://op.example.com \
  --env OPENPROJECT_API_TOKEN=replace-with-your-token \
  --env OPENPROJECT_READ_PROJECTS=my-project,other-project \
  --env OPENPROJECT_WRITE_PROJECTS=my-project \
  --transport stdio \
  --scope local \
  openproject -- openproject-ce-mcp
```

With a PyPI install (uv tool / pipx / pip) the command is simply
`openproject-ce-mcp`; for a zero-install setup replace the command with `uvx`
and pass `openproject-ce-mcp` as its argument (`-- uvx openproject-ce-mcp`). A
source install instead points at the `.venv` binary. See
[Installation](installation.md) for installing the package first, and
[Configuration](configuration.md) for the full `env` key reference.

This writes a private, per-project entry into `~/.claude.json` — there is
nothing to gitignore, since the entry lives outside your repository. The
token is still stored in plain text inside that file, though; protect it with
`chmod 600 ~/.claude.json` on macOS/Linux, or restrict it to your user via
**Properties → Security** on Windows. See
[global vs. project-scoped](clients.md#global-vs-project-scoped) for how this
compares to the other clients this tool supports.

## Automatic setup provided by this package

`openproject-ce-mcp configure` does not drive `claude mcp add` — like every
other client this tool supports, it writes a plain config file directly
instead. For Claude Code that means either a project `.mcp.json` (Claude
Code's **Project scope**, meant for config shared and committed with your
team) or a flat `~/.claude.json` (**User scope**, shared across every
project), depending on which gate you answer during `configure`. Run it,
answer the project-scoped gate, and select Claude Code — it writes
`.mcp.json` for you, with only the values you set (everything else falls back
to a safe default and is omitted from the file). See
[Installation](installation.md) for installing the package first.

Because `.mcp.json` is Project scope, Claude Code expects it to be committed;
this tool instead embeds your token in it and relies on `.gitignore` to keep
it private (see "Protect credentials" below) — a deliberate deviation from
Claude Code's own scope model, kept only so this tool's `.mcp.json` output
matches the single-config-file pattern it uses for every other client. If you
want Claude Code's native, private Local scope instead, use the manual
command under "Recommended setup" above rather than this automatic path.

## Manual setup (matching this package's automatic `.mcp.json` output)

If you'd rather reproduce what `configure` writes automatically — or want the
same single-file pattern this tool uses for every other client — create
`.mcp.json` in your project root:

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

Add `.mcp.json` and `.mcp.json.bak*` to your project's `.gitignore` so neither
the file nor its timestamped backups are ever committed.

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

**Note:** All projects share the same credentials and permissions. For
credentials specifically, the native Local-scope setup under "Recommended
setup" above is preferred — it stays private and project-specific without
sharing across every project the way this User-scope option does.

---

## Notes

- After changing the config, reload MCP servers: run "Developer: Reload Window" from the command palette (**Cmd+Shift+P** on macOS, **Ctrl+Shift+P** on Windows/Linux)
- `OPENPROJECT_READ_PROJECTS` accepts comma-separated identifiers, names, or glob patterns: `project-one,team-*`. Use `*` for all visible projects
- `OPENPROJECT_WRITE_PROJECTS` is the real write gate — the 5 core write-category flags (like `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`) are on by default and do nothing until a project is listed here; set one to `false` to exclude that category instead

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — global vs. project-scoped, and every client's file layout
- [Configuration](configuration.md) — the full environment variable reference
