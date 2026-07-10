# OpenProject CE MCP

[![PyPI](https://img.shields.io/pypi/v/openproject-ce-mcp.svg)](https://pypi.org/project/openproject-ce-mcp/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/protocol-MCP%20stdio-purple.svg)](https://modelcontextprotocol.io)

<p align="center">
  <img src="img/openproject-ce-mcp-hero.jpg" alt="Hero image showing a Python terminal and an OpenProject board connected by a structured data stream." width="960">
</p>

An MCP server for OpenProject that lets local AI agents read and manage project data through structured, guarded tools.

The server runs as a local subprocess of your MCP client over stdio. It wraps OpenProject API v3 and exposes typed tools for projects, work packages, memberships, versions, boards, time entries, and more.

---

## Scope: Community Edition

This MCP server targets **OpenProject Community Edition** only. It does not support Enterprise Edition features such as:

- Placeholder Users
- Budgets
- Portfolios
- Programs
- Custom Actions
- Baseline Comparisons

**Note:** OpenProject Enterprise Edition includes its own MCP server. If you have an Enterprise license, use the official Enterprise MCP instead of this one.

---

## Table of Contents

- [What you can do](#what-you-can-do)
- [How it works](#how-it-works)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Tools](#tools)
- [Integrations](#integrations)
- [Architecture](#architecture)
- [Development](#development)

---

## What you can do

**Projects**
- List, create, copy, update, and delete projects
- Read project configurations, lifecycle phases, and admin context
- Create, update, and delete memberships and versions; list roles

**Work packages**
- List and search work packages with structured filters
- Create, update, and delete work packages; create subtasks; create, update, and delete relations; add comments (no edit or delete)
- Upload and delete attachments; add and remove watchers; read activity logs
- Log, update, and delete time entries

**Boards and views**
- Create, read, update, and delete saved boards (queries); read views

**Users and groups**
- Read user accounts and group memberships
- Create, update, lock, unlock, and delete users; add and remove group members

**Supporting data**
- Fetch individual wiki pages by id; create, update, and delete news; read and update documents
- Read and mark notifications; read help texts, working days, and instance configuration
- Create and inspect grids; inspect custom options

All write operations follow a preview-then-confirm pattern by default: call a tool once to get a validated preview, then again with `confirm=true` to execute. This can be bypassed globally with `OPENPROJECT_AUTO_CONFIRM_WRITE=true`.

Self-scoped mutations of the current user's own state — notification read state, preferences, and the current user's emoji reactions — execute directly without a preview step. Project-attached reactions still enforce project write scope.

---

## How it works

- Communicates with the MCP client over stdio — no remote server, no persistent storage
- Reads are enabled by default; writes require explicit opt-in via environment variables
- Create and update operations validate the payload against OpenProject form endpoints before writing; delete and other simple operations execute directly once confirmed
- Project scope is enforced server-side: the MCP only exposes what the configured allowlists permit
- Responses are bounded and paginated — compact summaries, not raw HAL payloads

### Context efficiency

A core reason to use this MCP instead of calling the OpenProject REST API directly:
it returns agent-shaped, context-frugal responses. The raw v3 API answers a list
request with full HAL payloads — every element carries ~21 top-level fields plus
~46 `_links`. The MCP returns a compact summary per row, drops derivable and
duplicated fields, and lets the agent request only the fields it needs.

Measured against the same three representative work packages (token ≈
bytes/4), reproducible with `tools/measure-context.py` against a local
Docker test instance:

| Response | Tokens | vs. raw API |
|---|---:|---:|
| Raw OpenProject REST API v3 (HAL) | ~7,900 | baseline |
| `list_work_packages` (MCP) | ~1,050 | **−87%** |
| `list_work_packages` with `select` (5 fields) | ~120 | **−98%** |

The tool set itself is trimmed too, mainly by not emitting redundant output
schemas: on a fully write-enabled deployment (all write scopes on, metadata
tools off — the default), the `tools/list` payload is currently ~30k tokens,
down from an unoptimized ~60k baseline (**−50%**). Read-only deployments (no
write scopes enabled) pay a smaller ~19k. Rarely-used metadata tools are
gated off by default (`OPENPROJECT_ENABLE_METADATA_TOOLS`), and confirmed
writes drop the echoed request `payload`. Run `python tools/measure-context.py`
to reproduce all of these numbers (the tool-catalog part needs no live
instance; the response-size table needs a local Docker test instance — see
the script's docstring).

---

## Getting started

In short:

1. **Install the server from PyPI** with `uv`.
2. **Run `openproject-ce-mcp configure`** and let it write your MCP client config.
3. **Restart your client.**
4. **Verify** by asking it to call `get_current_user` or `list_projects`.

The rest of this section covers each step in detail.

### Requirements

| | |
|---|---|
| Python | 3.10 or later |
| git | only for the "install from source" path (clones this repository) |
| OpenProject | Community Edition 16.1 or later (reviewed for compatibility through 17.5), API v3 accessible |
| OS | macOS 12+, Linux, or Windows 10/11 |

[`uv`](https://github.com/astral-sh/uv) is recommended for dependency management but not required.

### Prepare your OpenProject instance

An administrator must enable API token creation once:

**Administration → API and webhooks → API**

| Setting | Recommended |
|---|---|
| Enable API tokens | checked |
| Write access to read-only attributes | unchecked |
| Enable CORS | unchecked |

To create a personal token: **My account → Access tokens → + API token**. Copy the token immediately — it is only shown once. Format: `opapi-...`.

### Install

Install from PyPI with `uv`, then run the interactive setup:

```bash
uv tool install openproject-ce-mcp
openproject-ce-mcp configure
openproject-ce-mcp --version
```

`configure` collects your OpenProject URL, API token, project scope, and whether
project-scoped writes should be enabled. It can write supported client configs
for you.

Project-scoped configuration is recommended for most users: the OpenProject MCP
is available only in the current project/workspace. Choose global configuration
only if you intentionally want the same OpenProject server available everywhere.

The setup asks where to write the config before it asks for credentials:

1. **Configure globally (user-wide)?** — registers the server in a detected
   client's user-wide config (e.g. `~/.claude.json`), available in every project.
2. **Configure project-scoped (this directory)?** — writes config files into the
   current directory (`.mcp.json`, `.codex/config.toml`, `.vscode/mcp.json`,
   `.cursor/mcp.json`); offered for every supported client, whether or not it is
   detected. A generic `.mcp.json` you can copy values from is written too (unless
   you selected Claude Code, whose project config *is* `.mcp.json`).

Configure either global or project-scoped in one run. Run `configure` again if
you intentionally want both scopes with separate settings. If a deselected scope
already has an OpenProject entry, setup asks whether to remove it; it never
silently deletes it. Choosing neither aborts before it asks for your token,
unless you only chose to remove existing entries. Existing entries for other MCP
servers are kept and each edited file is backed up first. After it writes, it
tells you how to (re)load each client so the server actually starts.

Restart your MCP client after installation or configuration, then ask it to call
`get_current_user` or `list_projects`.

### Update

Upgrade the installed PyPI package, then restart your MCP client:

```bash
uv tool install --upgrade openproject-ce-mcp
openproject-ce-mcp --version
```

If you installed with another tool:

```bash
pipx upgrade openproject-ce-mcp
# or
pip install --upgrade openproject-ce-mcp
```

No config rewrite is usually needed after an update. Re-run
`openproject-ce-mcp configure` only when you want to change client targets,
project scope, write access, or advanced settings.

### Advanced install alternatives

Use these when `uv tool install` is not the right fit for your environment:

```bash
pipx install openproject-ce-mcp
pip install openproject-ce-mcp
```

With `uv`, you can also skip installing entirely and point your client's
`command` at `uvx` with args `["openproject-ce-mcp"]`. Treat this as an advanced
client-config option; the normal path is to install once and let `configure`
write the client config.

<details>
<summary><b>Alternative: install from source</b> (curl one-liner, needs git)</summary>

The source installer clones the repo, installs dependencies (via `uv` if
available, or `venv` + `pip` otherwise), and runs the same interactive setup.

**Windows (PowerShell)** — clones to `%USERPROFILE%\openproject-ce-mcp`, binary at `...\.venv\Scripts\openproject-ce-mcp.exe`; set `$env:DIR` to override the destination:

```powershell
irm https://raw.githubusercontent.com/jtauschl/openproject-ce-mcp/main/get.ps1 | iex
```

**macOS / Linux** — clones to `~/openproject-ce-mcp`, binary at `~/openproject-ce-mcp/.venv/bin/openproject-ce-mcp`; `DIR=…` overrides the destination:

```bash
curl -fsSL https://raw.githubusercontent.com/jtauschl/openproject-ce-mcp/main/get.sh | sh
```

</details>

PyPI/source installs use the same setup flow after installation: project
directories get a local `.mcp.json`; global setup registers a detected client
directly (see below).

### Client registration reference

`openproject-ce-mcp configure` writes supported client configs for you. Use this
section only when you need to inspect the file layout or register the server by
hand.

Registration only points your client to the installed command; it is not a
second install. Using more than one client (say Claude and Codex)? Create one
config file per client; they sit side by side.

**Which guide do I use?** Use VS Code → the GitHub Copilot guide. Use Claude Code
→ the Claude guide. Use the Claude desktop app → the Claude Desktop guide. Use
Cursor or Codex → their own guide. Any other MCP client → the generic note below.

The file, location, and format differ per client — you cannot copy one client's
config to another verbatim:

| Client | Project-scoped file | User-wide file | Format | Root key |
|---|---|---|---|---|
| Claude / Claude Code | `.mcp.json` | `~/.claude.json` | JSON | `mcpServers` |
| Claude Desktop app | — (global only) | `claude_desktop_config.json` | JSON | `mcpServers` |
| Codex | `.codex/config.toml` | `~/.codex/config.toml` | TOML | `[mcp_servers.openproject]` |
| Cursor | `.cursor/mcp.json` | `~/.cursor/mcp.json` | JSON | `mcpServers` |
| VS Code (GitHub Copilot) | `.vscode/mcp.json` | User `mcp.json` | JSON | `servers` |

> **VS Code users:** the Copilot guide below is your guide — VS Code runs MCP
> servers through GitHub Copilot in Agent mode.

To register manually, copy the `command` and `env` values from the generated
`.mcp.json` into the file and format your client's guide shows. The values are
identical across clients.

Follow the guide for your client:

- [Claude / Claude Code](docs/claude.md)
- [Claude Desktop app](docs/claude-desktop.md)
- [Codex](docs/codex.md)
- [Cursor](docs/cursor.md)
- [VS Code / GitHub Copilot](docs/github.md)

**Any other MCP client** (Windsurf, JetBrains AI Assistant/Junie, Cline,
Continue, Warp, Zed, …) uses the same pattern: point `command` at the binary from
the generated `.mcp.json` and copy the `env` values. The root key is almost
always `mcpServers` (Zed uses `context_servers` with `"source": "custom"`;
Continue uses YAML with the same fields).

Each guide shows the project-scoped and/or user-wide config, how to reload the
client, and how to verify the server is picked up.

### Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Server / tools don't appear | Client not restarted, or the config is in the wrong file. Reload the client and confirm the file, location, and root key match your client's row above. |
| `[auth_error]` on the first call | Wrong `OPENPROJECT_API_TOKEN` or `OPENPROJECT_BASE_URL`. Re-check both; the token is `opapi-…` and the base URL has no trailing `/api/v3`. |
| Tools appear but writes fail | Writes are opt-in. Enable write access, make sure the project is in `OPENPROJECT_ALLOWED_PROJECTS_WRITE`, and check the corresponding write-group flag such as `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`. |

**Uninstall**

First unregister the server. This removes the `openproject` entry from your
clients' **user-wide** configs **and** from **project-local** configs in the
current directory (`.mcp.json`, `.codex/config.toml`, `.vscode/mcp.json`,
`.cursor/mcp.json`) — so run it from the project directory to clean that up too.
Your other MCP servers and settings are kept and each edited file is backed up
first; results are listed grouped by scope:

```bash
openproject-ce-mcp configure --uninstall   # or: openproject-ce-mcp-setup --uninstall
```

Then remove the package itself, matching how you installed it:

```bash
uv tool uninstall openproject-ce-mcp   # or: pipx uninstall openproject-ce-mcp
                                       # or: pip uninstall openproject-ce-mcp
```

<details>
<summary><b>Uninstalling a source install</b></summary>

If you installed from source, `uninstall.sh` / `uninstall.ps1` also remove the
local environment (`.venv`, caches, the API-source clones) in addition to
unregistering the client entries:

- **Windows:** `.\uninstall.ps1` (then remove the install dir if you want: `Remove-Item -Recurse -Force $env:USERPROFILE\openproject-ce-mcp`)
- **macOS / Linux:** `~/openproject-ce-mcp/uninstall.sh`

</details>

---

## Troubleshooting

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

If a check fails, doctor prints a `[FAIL]` message with details and suggestions. Common issues:

- **Missing env vars**: Add `OPENPROJECT_BASE_URL` and `OPENPROJECT_API_TOKEN` to your client config's `env` section
- **Auth failure**: Check that your API token is valid (regenerate it in OpenProject if needed)
- **Cannot connect**: Verify your base URL is correct and the OpenProject instance is reachable
- **No configs found**: Run `openproject-ce-mcp configure` to register the server with your MCP clients

**Exit codes**: `0` = all checks passed, `1` = one or more checks failed

---

## Configuration

Your client config (`.mcp.json`, `.codex/config.toml`, or `.vscode/mcp.json`) contains your API token. Treat it like a password. This repo gitignores `.mcp.json`, but when you place a project-scoped config in your **own** project, add it to that project's `.gitignore` so the token is never committed.

`openproject-ce-mcp configure` writes a complete config. The basic path asks for
connection, project scope, whether project-scoped writes should be enabled, and
— only if writes are enabled — whether to skip the write-preview step
(auto-confirm), which defaults to off. Detailed per-chain read/write groups,
field filtering, and runtime settings are behind the "Configure advanced
options?" prompt; if you skip it while reconfiguring, existing advanced values
are preserved.

### Connection

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENPROJECT_BASE_URL` | yes | — | Base URL of your OpenProject instance, e.g. `https://op.example.com` |
| `OPENPROJECT_API_TOKEN` | yes | — | Personal API token |

### Project Scope

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENPROJECT_ALLOWED_PROJECTS_READ` | no | `*` | Readable projects; comma-separated identifiers, names, or glob patterns (e.g. `my-project,team-*`); `*` allows all visible projects |
| `OPENPROJECT_ALLOWED_PROJECTS_WRITE` | no | empty | Writable projects; empty disables all project-scoped writes; always intersected with read scope |
| `OPENPROJECT_ALLOWED_PROJECTS` | no | — | Deprecated alias for `OPENPROJECT_ALLOWED_PROJECTS_READ`; still honored (with a startup warning) if `_READ` is unset, but will be removed in a future release — rename it |

### Tool Groups

Access is grouped into five chains: `project`, `membership`, `work_package`,
`version`, and `board`. Each chain has a read flag and a write flag. Read flags
default on. Write flags only matter when `OPENPROJECT_ALLOWED_PROJECTS_WRITE`
is not empty; enabling write access in the basic setup turns the normal
project-scoped write groups on by default, and Advanced setup can narrow them.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENPROJECT_ENABLE_PROJECT_READ` | no | `true` | Projects, documents, news, wiki, lifecycle |
| `OPENPROJECT_ENABLE_WORK_PACKAGE_READ` | no | `true` | Work packages, relations, attachments, time entries |
| `OPENPROJECT_ENABLE_MEMBERSHIP_READ` | no | `true` | Memberships, roles, principals |
| `OPENPROJECT_ENABLE_VERSION_READ` | no | `true` | Versions |
| `OPENPROJECT_ENABLE_BOARD_READ` | no | `true` | Boards and views |
| `OPENPROJECT_ENABLE_PROJECT_WRITE` | no | `false` | Project create/update/delete, news, documents, grids |
| `OPENPROJECT_ENABLE_MEMBERSHIP_WRITE` | no | `false` | Project membership create/update/delete |
| `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE` | no | `false` | Work-package create/update/delete, comments, relations, attachments, time entries |
| `OPENPROJECT_ENABLE_VERSION_WRITE` | no | `false` | Version create/update/delete |
| `OPENPROJECT_ENABLE_BOARD_WRITE` | no | `false` | Board create/update/delete |

### Confirmation Behavior

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENPROJECT_AUTO_CONFIRM_WRITE` | no | `false` | Skip the preview step for writes |
| `OPENPROJECT_AUTO_CONFIRM_DELETE` | no | `false` in generated configs; inherits `OPENPROJECT_AUTO_CONFIRM_WRITE` if omitted | Skip the preview step for deletes |

### Token / Context Budget

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENPROJECT_ENABLE_METADATA_TOOLS` | no | `false` | Expose the rarely-used metadata/reference tools (`get_query_*` schema tools, `render_text`, `get_custom_option`, `list_help_texts`/`get_help_text`, `list_working_days`/`list_non_working_days`). Off by default to keep them out of the tool set and save context; they stay reachable once enabled |
| `OPENPROJECT_DEFAULT_PAGE_SIZE` | no | `10` | Default results per page (kept small to bound list context; raise if you want more rows per call) |
| `OPENPROJECT_MAX_PAGE_SIZE` | no | `50` | Hard cap on results per request |
| `OPENPROJECT_MAX_RESULTS` | no | `100` | Hard cap on total results returned by a tool |
| `OPENPROJECT_TEXT_LIMIT` | no | `500` | Char cap for the description preview in list/search results (context protection across many rows). Single-item reads (`get_work_package`, `get_work_package_activities`) return full text regardless; a per-call `text_limit` overrides this |

### Security / Privacy

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENPROJECT_HIDE_<ENTITY>_FIELDS` | no | empty | Comma-separated fields to omit from reads and reject on writes; `*` wildcards supported |
| `OPENPROJECT_HIDE_CUSTOM_FIELDS` | no | empty | Custom field names or keys to omit; `*` wildcards supported |
| `OPENPROJECT_ATTACHMENT_ROOT` | no | current working directory | Directory that attachment uploads are confined to. Files outside it are refused, and credential/config files (`.mcp.json`, `.env`, `*.pem`, keys) are refused even inside it, so a tool call cannot exfiltrate local secrets |
| `OPENPROJECT_ENABLE_ADMIN_WRITE` | no | `false` | User and group management (create/update/delete/lock users, create/update/delete groups). Must be set explicitly and is not activated by any project-scoped write flag |

### Network / Runtime

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENPROJECT_TIMEOUT` | no | `12` | Request timeout in seconds |
| `OPENPROJECT_VERIFY_SSL` | no | `true` | Verify TLS certificates |
| `OPENPROJECT_MAX_RETRIES` | no | `3` | Retries for 429/5xx responses |
| `OPENPROJECT_RETRY_BASE_DELAY` | no | `1.0` | Initial retry delay in seconds |
| `OPENPROJECT_RETRY_MAX_DELAY` | no | `60.0` | Maximum retry delay in seconds |
| `OPENPROJECT_LOG_LEVEL` | no | `WARNING` | `CRITICAL`, `ERROR`, `WARNING`, or `INFO` |

Supported entities for `OPENPROJECT_HIDE_<ENTITY>_FIELDS`: `project`, `membership`, `role`, `principal`, `user`, `group`, `project_access`, `project_admin_context`, `project_configuration`, `action`, `capability`, `job_status`, `project_phase_definition`, `project_phase`, `view`, `query_filter`, `query_column`, `query_operator`, `query_sort_by`, `query_filter_instance_schema`, `document`, `news`, `wiki_page`, `category`, `attachment`, `time_entry_activity`, `time_entry`, `work_package`, `relation`, `activity`, `reminder`, `version`, `sprint`, `board`, `current_user`, `instance_configuration`, `status`, `type`.

**Never share your API token** in chat messages, screenshots, or log output. If a token has been exposed, revoke it immediately in **My account → Access tokens** and create a new one.

---

## Tools

Tools are grouped by area: projects, memberships, users, groups, work packages, versions, boards, time entries, wiki, news, documents, notifications, grids, and more.

List and search tools accept a `select` parameter to return only the fields you
need per row, and responses are trimmed for context economy (list results drop
the derivable `count`/`truncated`; a confirmed write drops the echoed request
`payload`). On `update_work_package` / `update_project`, pass `"none"` to clear a
nullable field (assignee, responsible, version, sprint, parent, category, project_phase).
A handful of rarely-used metadata tools are gated behind
`OPENPROJECT_ENABLE_METADATA_TOOLS` (see Configuration).

See the full [tool reference](docs/tools.md) for descriptions of every tool.

### Errors

Every tool failure carries a stable, machine-readable category as a leading
`[category]` prefix on the error message, so an agent can branch on the failure
type instead of parsing free text. The categories are:

| Category | Meaning |
|---|---|
| `[validation_error]` | An input was rejected before the request (fix the arguments and retry) |
| `[auth_error]` | Authentication failed (check the API token) |
| `[permission_denied]` | The token lacks permission, or a write scope is disabled |
| `[not_found]` | The resource does not exist (or the feature needs a newer OpenProject) |
| `[transport_error]` | OpenProject could not be reached (transient — safe to retry) |
| `[server_error]` | OpenProject returned an unexpected failure |
| `[openproject_error]` | Any other OpenProject-side failure |

Successful write previews are not errors — they return a structured result with
`ready`, `requires_confirmation`, `validation_errors`, and a human-readable
`message`.

---

## Integrations

The server communicates over stdio and is compatible with any MCP client. Client-specific setup guides are available in the [`docs/`](docs/) folder.

---

## Architecture

A few narrow modules, no deep abstractions:

- `config.py` — environment parsing and safe defaults
- `client.py` — HTTP access, policy checks, HAL normalization, preview/confirm writes
- `retry_transport.py` — HTTP retry with backoff for transient failures
- `models.py` — compact dataclasses returned to MCP clients
- `tools.py` — validated MCP tool handlers
- `server.py` — FastMCP lifecycle wiring
- `setup_cli.py` — the interactive `configure` command
- `doctor.py` — the `doctor` diagnostics command

`client.py` is intentionally large: all policy-sensitive logic (read gates, write gates, project scoping, field hiding) lives in one place to make it easier to audit.

See [docs/architecture.md](docs/architecture.md) for request flow details, naming conventions, and the safety model.

---

## Security

### Prompt Injection

User-provided text (work-package descriptions, comments, news, wiki content) is marked with `<user-content>` tags and flagged in server instructions as untrusted. Agents should treat this content as data, not as instructions.

See [SECURITY.md](SECURITY.md) for the full security model, including prompt injection mitigations, reporting procedures, and supported versions.

---

## Development

### Set up

```bash
git clone https://github.com/jtauschl/openproject-ce-mcp.git
cd openproject-ce-mcp

# option A: uv (recommended)
uv sync --dev

# option B: venv + pip
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### Run tests

**Unit tests** (no network — run against `httpx` mocks):

```bash
# uv
uv run pytest

# venv
.venv/bin/python -m pytest
```

**Integration tests** (require a live OpenProject instance):

```bash
OPENPROJECT_BASE_URL=https://op.example.com \
OPENPROJECT_API_TOKEN=opapi-... \
OPENPROJECT_TEST_PROJECT=mcp-test \
uv run pytest -m integration -v
```

`OPENPROJECT_TEST_PROJECT` is the project identifier used for write tests (default: `mcp-test`). Integration tests are excluded from the default run (`-m 'not integration'`) and must be opted in explicitly.

For local, throwaway instances across the OpenProject versions where the API changed (16.6 classic + 17.4 displayId + 17.5 semantic/workspaces), see [`docker/test/`](docker/test/) — `docker/test/up.sh` boots and seeds them and prints the env block to run the integration tests against each. To verify the client's API assumptions against the OpenProject source across releases, see [`tools/api-check/`](tools/api-check/).

### After code changes

The MCP server runs as a subprocess. After any code change, restart your MCP client before updated tools become active.

### Releasing

The package is published to [PyPI](https://pypi.org/project/openproject-ce-mcp/)
via GitHub Actions using [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC — no API token stored), triggered by pushing a `vX.Y.Z` tag. Every push
and PR also runs the test matrix plus a `build` job (`uv build` +
`uvx twine check dist/*`) so the package always stays buildable. See
[RELEASE.md](RELEASE.md) for the maintainer release process.

---
