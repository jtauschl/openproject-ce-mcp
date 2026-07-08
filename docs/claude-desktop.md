# Claude Desktop app

<p align="center">
  <img src="../img/claude.jpg" alt="Claude artwork for the Claude Desktop MCP guide." width="960">
</p>

This guide covers the standalone **Claude Desktop app** (macOS/Windows). It is a
different program from Claude Code, and it uses its **own** config file —
Claude Desktop does not read the Claude Code config (`~/.claude.json`).

Claude Desktop only has a single, user-wide config: the server is available in
every conversation. There is no project-scoped option here (for per-project
permissions, use Claude Code — see [claude.md](claude.md)).

## Setup

1. **Locate the config file** (create it if it does not exist):
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux:** `~/.config/Claude/claude_desktop_config.json`

   In the app you can open it via **Settings → Developer → Edit Config**.

2. **Protect it if it contains secrets** (macOS/Linux):
   ```bash
   chmod 600 ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```
   On Windows, restrict the file to your user via its **Properties → Security**.

3. **Add the server.** The easiest path is to let `openproject-ce-mcp configure`
   detect the Claude Desktop app and write this file for you (it registers Claude
   Desktop through its global config — Claude Desktop has no project-local config).
   To add it by hand instead, copy the `env` block from any config the wizard
   generates (for example the `.mcp.json` it writes in a project directory); the
   root key is the same, `mcpServers`. With a PyPI install the command is simply
   `openproject-ce-mcp`; source installs can use the `.venv` binary path.
   ```json
   {
     "mcpServers": {
       "openproject": {
         "command": "openproject-ce-mcp",
         "env": {
           "OPENPROJECT_BASE_URL": "https://op.example.com",
           "OPENPROJECT_API_TOKEN": "replace-with-your-token",

           "OPENPROJECT_ALLOWED_PROJECTS_READ": "*",
           "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "",

           "OPENPROJECT_ENABLE_PROJECT_READ": "true",
           "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "true",
           "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": "true",
           "OPENPROJECT_ENABLE_VERSION_READ": "true",
           "OPENPROJECT_ENABLE_BOARD_READ": "true",

           "OPENPROJECT_HIDE_PROJECT_FIELDS": "",
           "OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS": "",
           "OPENPROJECT_HIDE_ACTIVITY_FIELDS": "",
           "OPENPROJECT_HIDE_CUSTOM_FIELDS": "",

           "OPENPROJECT_ENABLE_ADMIN_WRITE": "false",

           "OPENPROJECT_ENABLE_PROJECT_WRITE": "false",
           "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": "false",
           "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "false",
           "OPENPROJECT_ENABLE_VERSION_WRITE": "false",
           "OPENPROJECT_ENABLE_BOARD_WRITE": "false",

           "OPENPROJECT_TIMEOUT": "12",
           "OPENPROJECT_VERIFY_SSL": "true",
           "OPENPROJECT_DEFAULT_PAGE_SIZE": "10",
           "OPENPROJECT_MAX_PAGE_SIZE": "50",
           "OPENPROJECT_MAX_RESULTS": "100",
           "OPENPROJECT_TEXT_LIMIT": "500",
           "OPENPROJECT_LOG_LEVEL": "WARNING"
         }
       }
     }
   }
   ```

   If the file already has a `mcpServers` block, add the `openproject` entry
   alongside your existing servers instead of replacing the whole file. Other
   keys (such as `OPENPROJECT_AUTO_CONFIRM_WRITE`) are optional and fall back to
   safe defaults when omitted — see the [Configuration table](../README.md#configuration).

4. **Restart Claude Desktop** completely (quit and reopen — a window reload is
   not enough).

### Verify

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
- `OPENPROJECT_ALLOWED_PROJECTS_READ` accepts comma-separated identifiers, names, or glob patterns: `project-one,team-*`. Use `*` for all visible projects.
- `OPENPROJECT_ALLOWED_PROJECTS_WRITE` only narrows scope; it doesn't enable writes. Use the scoped `OPENPROJECT_ENABLE_*_WRITE` flags for the operations you need.
