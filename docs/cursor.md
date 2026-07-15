# Cursor

<p align="center">
  <img src="../img/cursor.jpg" alt="Cursor artwork for the Cursor MCP guide." width="960">
</p>

Cursor uses the same MCP config shape as Claude Code (`mcpServers` with
`command` + `env`) — only the file location differs.

## Recommended setup

For a local STDIO server in the Cursor IDE, Cursor supports `${env:VAR_NAME}`
as a placeholder in `env` values — it resolves to an already-set OS
environment variable at launch instead of embedding the value in
`.cursor/mcp.json`. For a private credential like an OpenProject API token,
this keeps the token out of `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "openproject": {
      "command": "openproject-ce-mcp",
      "env": {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "${env:OPENPROJECT_API_TOKEN}",
        "OPENPROJECT_READ_PROJECTS": "my-project,other-project",
        "OPENPROJECT_WRITE_PROJECTS": "my-project"
      }
    }
  }
}
```

`OPENPROJECT_API_TOKEN` must be set in the environment of the process that
launches Cursor — a shell profile is enough if Cursor starts from that same
initialized shell; a GUI launch may need an OS-level environment mechanism or
a secret manager instead. Restart Cursor afterward so it picks up the
variable. `${env:...}` is Cursor's documented interpolation mechanism for
keeping the token out of `mcp.json`; unlike VS Code, Cursor does not support
`${input:...}` there. This guidance covers a local STDIO server in the Cursor
IDE specifically — Cursor Agent CLI, Cloud Agents/Automations, and remote
environments may resolve variables differently and aren't covered here.

## Automatic setup provided by this package

`openproject-ce-mcp configure` does not use `${env:...}` — like every other
client this tool supports, it writes a plain config file directly, with the
token as a literal value. Run it, answer the project-scoped gate, and select
Cursor — it writes `.cursor/mcp.json` for you. See
[Installation](installation.md) for installing the package first.

## Manual setup (matching this package's automatic `.cursor/mcp.json` output)

If you'd rather reproduce what `configure` writes automatically, create
`.cursor/mcp.json`. The structure is identical to every other client
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

With the `${env:...}` pattern above, `.cursor/mcp.json` itself holds no
secret. The current automatic setup (`configure`) writes the token directly
into the file, and a manual setup that skips `${env:...}` does the same — in
both cases, protect it:

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
Project-scoped is preferred for per-project permissions; for credentials
specifically, the `${env:...}` pattern under "Recommended setup" above is
preferred either way.

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — global vs. project-scoped, and every client's file layout
- [Configuration](configuration.md) — the full environment variable reference
