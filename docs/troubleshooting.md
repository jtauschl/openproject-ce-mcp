# Troubleshooting

<p align="center">
  <img src="../img/troubleshooting.jpg" alt="A magnifying lens diagnosing a broken connection and restoring it to a verified state." width="960">
</p>

## Quick diagnosis: `doctor`

If the OpenProject MCP server doesn't appear in your MCP client after installation and configuration, run the built-in diagnostic command:

```bash
openproject-ce-mcp doctor
```

The `doctor` command checks your complete MCP setup and reports what's working and what needs fixing:

1. **Binary and version** — verifies the installed package and resolved binary path
2. **Client configs** — discovers MCP client configurations (Claude Code, Claude Desktop, VS Code, Codex, Cursor)
3. **Config parsing** — validates that your client configs are readable and contain a valid `openproject` entry
4. **Environment** — loads and validates `OPENPROJECT_*` environment variables from your client config or shell
5. **API connectivity** — tests your base URL and API token with a live connection to OpenProject
6. **Tool registration** — previews which MCP tools will be registered based on your read/write permissions

Example output:

```
Running OpenProject MCP diagnostics...

[OK] Binary: /usr/local/bin/openproject-ce-mcp (v0.3.0)
[OK] Clients: 2 configs found
  - Claude Code (global, detected): ~/.claude.json
  - Claude Desktop (global, detected): ~/Library/.../claude_desktop_config.json
[OK] Config parsing: all openproject entries valid
[OK] Environment: loaded from client configs
[OK] API: connected (Your Name)
[OK] Tools: 127 registered
  create_work_package, list_projects, update_work_package, ...

Restart needed for:
  - Claude Desktop: quit and reopen (window reload not enough)

All checks passed.
```

If a check fails, doctor prints a `[FAIL]` message with details and suggestions.

**Exit codes**: `0` = all checks passed, `1` = one or more checks failed

## Common issues

| Symptom | Likely cause and fix |
|---|---|
| Server / tools don't appear | Client not restarted, or the config is in the wrong file. Reload the client and confirm the file, location, and root key match your client's row in [Clients](clients.md#file-layout-per-client). |
| `[auth_error]` on the first call | Wrong `OPENPROJECT_API_TOKEN` or `OPENPROJECT_BASE_URL`. Re-check both; the token is `opapi-…` and the base URL has no trailing `/api/v3`. |
| Tools appear but writes fail | The project-scope allowlists are the real write gate, not the write-category flags (which default on). Make sure the target project is in **both** `OPENPROJECT_READ_PROJECTS` and `OPENPROJECT_WRITE_PROJECTS`, and check that the corresponding write-category flag such as `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE` hasn't been explicitly set to `false` — see [Configuration](configuration.md#tool-groups). |
| Missing env vars | Add `OPENPROJECT_BASE_URL` and `OPENPROJECT_API_TOKEN` to your client config's `env` section. |
| Auth failure | Check that your API token is valid (regenerate it in OpenProject if needed). |
| Cannot connect | Verify your base URL is correct and the OpenProject instance is reachable. |
| No configs found | Run `openproject-ce-mcp configure` to register the server with your MCP clients — see [Installation](installation.md) and [Clients](clients.md). |

Every MCP tool failure also carries a stable, machine-readable category as a
leading `[category]` prefix on the error message — see the
[error reference](tools.md#errors) for the full list.

## See also

- [Documentation hub](README.md) — full documentation index
- [Installation](installation.md) — install, update, and uninstall the package
- [Clients](clients.md) — client config file locations
- [Configuration](configuration.md) — the full environment variable reference
