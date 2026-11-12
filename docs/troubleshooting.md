# Troubleshooting

<p align="center">
  <img src="../img/troubleshooting.jpg" alt="A magnifying lens diagnosing a broken connection and restoring it to a verified state." width="960">  <!-- markdownlint-disable-line MD013 -->
</p>

## Quick diagnosis: `doctor`

If the OpenProject MCP server doesn't appear in your MCP client after
installation and configuration, run the built-in diagnostic command:

```bash
openproject-ce-mcp doctor
```

The `doctor` command checks every OpenProject entry in every MCP client
configuration on its own, the way that client starts the server. One client's
broken entry is never hidden by another client's entry or by the shell you run
`doctor` from.

1. **Binary and version**: the installed package, the resolved binary path,
   and the Python version and executable running it; a Python older than 3.11
   fails.
2. **Config files**: the client configurations it found (Claude Code, Claude
   Desktop, VS Code and its Agent Host, Codex, Cursor) and how many OpenProject
   entries each holds. An entry is a server named `openproject` or
   `openproject-*`, or any server whose command or arguments name
   `openproject-ce-mcp`. On macOS and Linux, a file with an entry that group or
   others may read or write is a warning, since it usually holds the API token.
3. **Environment per entry**: the variables the client would pass to the
   server, built with that client's rules. Claude Code and VS Code pass their own
   environment plus the entry's `env` (Claude Code also the `env` blocks of its
   settings files, VS Code also `envFile` from `.vscode/mcp.json` and its user
   `mcp.json`); Claude Desktop and Codex pass only a fixed set of variables plus
   what the entry names. Placeholders are resolved the way each client does:
   `${env:NAME}` in VS Code's own files, `${NAME}` and `${NAME:-default}` in
   Claude Code and in the `.mcp.json` and Copilot CLI files VS Code reads.
   VS Code takes the Claude Desktop, Cursor and Windsurf files it discovers
   literally.
   A missing `OPENPROJECT_BASE_URL` or `OPENPROJECT_API_TOKEN` fails only when the
   client cannot get it from anywhere else; when it could come from the client's
   own environment, which this shell only approximates, the entry is reported as
   not fully verified.
4. **Settings**: the same validation the server runs at startup, plus
   warnings for insecure settings, and a summary of the project scopes and
   write groups.
5. **Command**: an absolute command that does not exist or is not executable
   fails; a command that is not on `PATH` here is a warning. For Claude Desktop
   on macOS, a command found only outside `/usr/bin:/bin:/usr/sbin:/sbin` is a
   warning: the app starts with that `PATH`. For `uvx`, `uv` and `pipx` the
   package and version spec are shown.
6. **API connectivity**: a live connection test, run in a separate process
   with the entry's environment, so the entry's proxy and certificate settings
   apply. The process also gets `HOME`, `USER`, `PATH`, `LOGNAME`, `SHELL`,
   `TMPDIR` and `LANG` from your shell (on Windows also the variables a process
   needs to open network connections), plus `OPENPROJECT_MAX_RETRIES=0` and
   `OPENPROJECT_TIMEOUT=5` so the test fails fast. Entries with the same
   connection settings are tested once. A failure names its kind, for example
   a TLS/certificate error apart from an unreachable server or a timeout.
7. **Tool registration**: which MCP tools would register with the entry's
   settings. Under `OPENPROJECT_TOOL_PROFILE=core` the line also gives the count
   the same settings register under `full`.
8. **MCP dispatch**: that the server builds with the entry's settings and its
   tool-call dispatch rejects unknown arguments, checked in memory with a time
   limit, without starting the server or connecting. Like the tool preview, it
   runs only for entries without a `[FAIL]` so far.

Every line names the client, the server name and the file; entries whose
results differ only in the client share one block that names all of them. A
disabled entry (for example in Claude Code's `disabledMcpServers` or
`disabledMcpjsonServers`, or a Codex server with `enabled = false`) is checked
but does not count. A Codex entry in a project file that Codex does not load
here is reported as inactive. A Claude Code entry that a more specific scope
overrides is still checked and counted, because it applies elsewhere.

When no client configures an OpenProject server, `doctor` checks the process
environment instead.

### Codex

When Codex is installed, `doctor` runs `codex mcp list --json` up to twice: in the
current directory and in an empty temporary directory, which shows the
user-level configuration that applies everywhere else. Codex merges up to eight
configuration layers, and some of them (enterprise cloud configuration, macOS
managed preferences) cannot be read from files, so only Codex itself can say
what applies. `codex mcp list` reads Codex's credential store and contacts
configured HTTP MCP servers for OAuth discovery (at most 5 seconds each). Its
output contains tokens; `doctor` never prints it, only server names, key names
and Codex's own reason for a disabled server.

`doctor` also checks the Codex configuration files it can read (the system and
user `config.toml`, the project `.codex/config.toml` files Codex would consider,
and on Linux and macOS `/etc/codex/managed_config.toml`) for what each of them
sets.

A Codex server can run on a remote environment (`environment_id`). `doctor`
resolves that setting from the files it can read and treats a server those
files leave local as local, and says so for each entry. Managed configuration
that `doctor` cannot read could still move the server to a remote environment.
Flags passed to a particular Codex launch, such as `--config` or `--profile`,
are not covered.

Example output:

```text
Running OpenProject MCP diagnostics...

[OK] Binary: /usr/local/bin/openproject-ce-mcp (v<version>)
[OK] Python: 3.13.1 (/usr/local/opt/python@3.13/bin/python3.13)
Config files:
  - Claude Code (user scope): ~/.claude.json, 1 OpenProject entry
  - Claude Desktop (user): ~/Library/Application Support/Claude/claude_desktop_config.json, 1 OpenProject entry
  - Codex (user layer): ~/.codex/config.toml

Connection checks run with each entry's environment plus this shell's HOME, USER, PATH, LOGNAME, SHELL, TMPDIR, LANG (platform minimum), with OPENPROJECT_MAX_RETRIES=0 and OPENPROJECT_TIMEOUT=5.
[INFO] Claude Code: Claude Code can add its agent proxy settings, which this doctor cannot see

[OK] Claude Code openproject (~/.claude.json, user scope): settings valid
    Read projects: OPM, TST
    Write projects: TST
    ...
[OK] Claude Code openproject (~/.claude.json, user scope): command: /usr/local/bin/openproject-ce-mcp
[OK] Claude Code openproject (~/.claude.json, user scope): API: connected (Your Name)
[OK] Claude Code openproject (~/.claude.json, user scope): Tools: <N> would register (profile full): list_projects, ...
[OK] Claude Code openproject (~/.claude.json, user scope): MCP: dispatch rejects unknown arguments (checked in process)

[FAIL] Claude Desktop openproject (~/Library/Application Support/Claude/claude_desktop_config.json, user): OPENPROJECT_API_TOKEN is not set, and Claude Desktop cannot get it from anywhere else
...

[INFO] Codex openproject (this directory and user level): assuming Codex runs it locally; managed configuration this doctor cannot read could change that
[OK] Codex openproject (this directory and user level): settings valid
...
[OK] Codex openproject (this directory and user level): API: connected (Your Name)

Restart needed for:
  - Claude Code (CLI + IDE extension): run /mcp in Claude Code, or start a new session
  - Claude Desktop app: quit Claude Desktop completely and reopen it (a window reload is not enough)
  - Codex (CLI + IDE extension): reload the editor window or restart Codex

1 entry failed; see the [FAIL] lines above:
  - Claude Desktop openproject (~/Library/Application Support/Claude/claude_desktop_config.json, user)
```

**Exit codes**: `1` when an entry that counts has a `[FAIL]` or the Python
running `doctor` is too old, otherwise `0`.
The output ends with `All checks passed.` only when everything could be
verified; otherwise it lists the entries that failed or could not be fully
verified, or says that there is no active OpenProject entry.

## Common issues

| Symptom | Likely cause and fix |
| --- | --- |
| Server / tools don't appear | Client not restarted, or the config is in the wrong file. Reload the client and confirm the file, location, and root key match your client's row in [Clients](clients.md#file-layout-per-client) — `configure` writes to whatever directory it was launched from, so also check that matches the folder your client has open, and re-run `configure` from there if not. |
| `[AUTHENTICATION_FAILED]` on the first call | Wrong `OPENPROJECT_API_TOKEN` or `OPENPROJECT_BASE_URL`. Re-check both; the token is `opapi-…` and the base URL has no trailing `/api/v3`. |
| Tools appear but writes fail | The project-scope allowlists are the real write gate, not the write-category flags (which default on). Make sure the target project is in **both** `OPENPROJECT_READ_PROJECTS` and `OPENPROJECT_WRITE_PROJECTS`, and check that the corresponding write-category flag such as `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE` hasn't been explicitly set to `false` — see [Configuration](configuration.md#tool-groups). |
| Missing env vars | Add `OPENPROJECT_BASE_URL` and `OPENPROJECT_API_TOKEN` (or `OPENPROJECT_API_TOKEN_VAR`, the name of the variable that holds the token) to your client config's `env` section. |
| `OPENPROJECT_API_TOKEN_VAR must be an environment variable name` or `The environment variable that OPENPROJECT_API_TOKEN_VAR names is not set` | The value is the variable's name, not the token: letters, digits and underscores, not starting with a digit. The variable must reach the server (Codex: list it in `env_vars`). |
| `OPENPROJECT_API_TOKEN and OPENPROJECT_API_TOKEN_VAR are both set` | Set only one. An entry can clear an inherited `OPENPROJECT_API_TOKEN` with an empty value. |
| Auth failure | Check that your API token is valid (regenerate it in OpenProject if needed). |
| Cannot connect | Verify your base URL is correct and the OpenProject instance is reachable. |
| No configs found | Run `openproject-ce-mcp configure` to register the server with your MCP clients — see [Installation](installation.md) and [Clients](clients.md). |
| Codex CLI shows the server, IDE extension doesn't | First check the basics: the project is trusted, the IDE extension and CLI are pointed at the same project directory, and the file (`.codex/config.toml` vs. `~/.codex/config.toml`) matches the scope you configured — see [Clients](clients.md#file-layout-per-client). If those all check out and `codex mcp list` (CLI) shows the server but the IDE extension still doesn't, reload the editor window or restart the IDE; if it still doesn't appear, this may be a known upstream Codex extension-detection gap (tracked as Codex GitHub issue #6465) rather than a problem with this server's config — check the upstream issue for its current status. |

Every MCP tool failure also carries a stable, machine-readable category as a
leading `[category]` prefix on the error message — see the [error
reference](tools.md#errors) for the full list.

## See also

- [Documentation hub](README.md) — full documentation index
- [Installation](installation.md) — install, update, and uninstall the package
- [Clients](clients.md) — client config file locations
- [Configuration](configuration.md) — the full environment variable reference
