# Codex

<p align="center">
  <img src="../img/codex.jpg" alt="Codex artwork for the Codex MCP guide." width="960">
</p>

## Recommended setup

Codex supports `env_vars` on an `mcp_servers` entry — a whitelist of
environment variable names to forward from the process that launches Codex
into the server's environment, instead of embedding their values in
`.codex/config.toml`. For a private credential like an OpenProject API
token, this keeps the token out of `.codex/config.toml`:

```toml
[mcp_servers.openproject]
command = "openproject-ce-mcp"
env_vars = ["OPENPROJECT_API_TOKEN"]

[mcp_servers.openproject.env]
OPENPROJECT_BASE_URL = "https://op.example.com"
OPENPROJECT_READ_PROJECTS = "my-project,other-project"
OPENPROJECT_WRITE_PROJECTS = "my-project"
```

`OPENPROJECT_API_TOKEN` must be set in the environment of the process that
launches Codex — a shell profile is enough if Codex starts from that same
initialized shell; a GUI/IDE launch may need an OS-level environment
mechanism or a secret manager instead. If the variable isn't set when Codex
starts, it isn't forwarded and the MCP server exits at startup with
`OPENPROJECT_API_TOKEN is required.`, rather than silently running with an
empty token. Only the token needs this treatment — the other, non-sensitive
values can stay as literals in the `env` table as shown above.

Codex loads project-scoped config files (`.codex/config.toml`) only when you
trust the project. You do not need the Codex CLI installed for this setup if
you use the IDE extension and edit the config file directly.

## Automatic setup provided by this package

`openproject-ce-mcp configure` does not use `env_vars` — like every other
client this tool supports, it writes a plain config file directly, with all
values (including the token) as literals in `[mcp_servers.openproject.env]`.
Run it, answer the project-scoped gate, and select Codex — it writes
`.codex/config.toml` for you, with only the values you set (everything else
falls back to a safe default and is omitted from the file). See
[Installation](installation.md) for installing the package first.

## Manual setup (matching this package's automatic `.codex/config.toml` output)

If you'd rather reproduce what `configure` writes automatically, create
`.codex/config.toml` in your project root:

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

With the `env_vars` pattern above, `.codex/config.toml` itself holds no
secret. The current automatic setup (`configure`) writes the token directly
into the file, and a manual setup that skips `env_vars` does the same — in
both cases, protect it:

```bash
chmod 600 .codex/config.toml
```

Add `.codex/config.toml` and `.codex/config.toml.bak*` to your project's
`.gitignore` so neither the file nor its timestamped backups are ever
committed.

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

**Example:** For the recommended credential handling, use the `env_vars`
configuration from "Recommended setup" in `~/.codex/config.toml`. You can
also use the literal configuration instead, but then the file contains the
token and must be protected accordingly.

**Note:** All projects share the same credentials and permissions. For
credentials specifically, the `env_vars` pattern under "Recommended setup"
above is preferred.

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
