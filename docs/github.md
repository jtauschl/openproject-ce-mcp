# VS Code (GitHub Copilot)

<p align="center">
  <img src="../img/github.jpg" alt="GitHub Copilot artwork for the GitHub Copilot MCP guide." width="960">
</p>

This guide covers **VS Code**, where MCP servers run through **GitHub Copilot in
Agent mode**. If you use VS Code, this is your guide.

## Recommended setup

Use `.vscode/mcp.json` in your workspace (workspace-scoped — VS Code's term
for what other clients call project-scoped). This allows different
workspaces to have different OpenProject access and permissions.

## Automatic setup

Run `openproject-ce-mcp configure`, answer the project-scoped gate, and choose
VS Code (or pick the global option) — it writes `.vscode/mcp.json` with the
correct `servers` block and `"type": "stdio"` for you, with only the values
you set (everything else falls back to a safe default and is omitted from the
file). See [Installation](installation.md) for installing the package first.

## Manual setup

Create `.vscode/mcp.json`:

```json
{
  "servers": {
    "openproject": {
      "type": "stdio",
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
installs can use the `.venv` binary path (`...\.venv\Scripts\openproject-ce-mcp.exe`
on Windows). The full set of `env` keys is the same as every other client —
see [`.mcp.json.example`](../.mcp.json.example) or [Configuration](configuration.md).

Avoid hardcoding sensitive information when possible. VS Code recommends
using environment files or input variables.

## Protect credentials

**`.vscode/mcp.json` holds your API token.**

```bash
chmod 600 .vscode/mcp.json
```

Add `.vscode/mcp.json` to your project's `.gitignore` so it is never committed.

## Reload and verify

Open the command palette (**Cmd+Shift+P** on macOS, **Ctrl+Shift+P** on
Windows/Linux) and run "Developer: Reload Window". Then:

- Switch Copilot Chat to **Agent mode** (MCP tools are only available there).
- Open the tool picker in Copilot Chat and confirm the `openproject` tools are listed.
- Ask Copilot to call `list_projects` (or `get_current_user`). A successful reply confirms the base URL and token work.
- If the server doesn't appear, re-check that the file is `.vscode/mcp.json` with a `servers` block and `"type": "stdio"`, and that `command` is available on PATH (or is the absolute `.venv` path for a source install).

---

## User-wide setup (alternative)

Use the user `mcp.json` if you want the server available in all workspaces
instead of one:

1. Open the command palette (**Cmd+Shift+P** on macOS, **Ctrl+Shift+P** on Windows/Linux) and select "Open User MCP Settings"
2. **Add the same config** as above (workspace-scoped example)
3. **Reload:** Open the command palette again and run "Developer: Reload Window"

If you prefer to edit the file directly, the user `mcp.json` lives at:

- **Windows:** `%APPDATA%\Code\User\mcp.json`
- **macOS:** `~/Library/Application Support/Code/User/mcp.json`
- **Linux:** `~/.config/Code/User/mcp.json`

**Protect credentials** the same way as the workspace-scoped file (`chmod 600`
on macOS/Linux; restrict to your user via **Properties → Security** on
Windows).

**Note:** All workspaces share the same credentials and permissions.
Workspace-scoped setup (above) is the preferred method.

---

## Notes

- Switch Copilot Chat to Agent mode so MCP tools are available
- Workspace-scoped setup (`.vscode/mcp.json`) is preferred for fine-grained project permissions
- `OPENPROJECT_READ_PROJECTS` accepts comma-separated identifiers, names, or glob patterns: `project-one,team-*`. Use `*` for all visible projects
- `OPENPROJECT_WRITE_PROJECTS` is the real write gate — the 5 core write-category flags (like `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`) are on by default and do nothing until a project is listed here; set one to `false` to exclude that category instead

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — global vs. project-scoped ("workspace-scoped" here), and every client's file layout
- [Configuration](configuration.md) — the full environment variable reference
