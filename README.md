# OpenProject MCP

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/protocol-MCP%20stdio-purple.svg)](https://modelcontextprotocol.io)

<p align="center">
  <img src="img/openproject-mcp-hero.png" alt="Hero image showing a Python terminal and an OpenProject board connected by a structured data stream." width="960">
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

---

## How it works

- Communicates with the MCP client over stdio — no remote server, no persistent storage
- Reads are enabled by default; writes require explicit opt-in via environment variables
- Create and update operations validate the payload against OpenProject form endpoints before writing; delete and other simple operations execute directly once confirmed
- Project scope is enforced server-side: the MCP only exposes what the configured allowlists permit
- Responses are bounded and paginated — compact summaries, not raw HAL payloads

---

## Getting started

In short:

1. **Install the server** (the one-liner below).
2. **Copy the `command` and `env`** from the generated `.mcp.json` into your MCP
   client's config — or let the installer register a detected client for you.
3. **Restart your client.**
4. **Verify** by asking it to call `list_projects`.

The rest of this section covers each step in detail.

### Requirements

| | |
|---|---|
| Python | 3.10 or later |
| git | required — the installer clones this repository |
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

The installer clones the repo, installs dependencies (via `uv` if available, or
`venv` + `pip` otherwise), and runs the interactive setup. Pick your OS:

#### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/jtauschl/openproject-mcp/main/get.ps1 | iex
```

Clones to `%USERPROFILE%\openproject-mcp`. The installed binary is
`...\.venv\Scripts\openproject-mcp.exe`. To override the destination, set
`$env:DIR` before running.

#### macOS

```bash
curl -fsSL https://raw.githubusercontent.com/jtauschl/openproject-mcp/main/get.sh | sh
```

Clones to `~/openproject-mcp`. The installed binary is
`~/openproject-mcp/.venv/bin/openproject-mcp`. To override the destination:

```bash
DIR=~/tools/openproject-mcp curl -fsSL https://raw.githubusercontent.com/jtauschl/openproject-mcp/main/get.sh | sh
```

#### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/jtauschl/openproject-mcp/main/get.sh | sh
```

Same as macOS: clones to `~/openproject-mcp`, binary at
`~/openproject-mcp/.venv/bin/openproject-mcp`, `DIR=…` overrides the destination.

In all cases the setup then writes a local `.mcp.json` and can optionally set up
a detected MCP client for you (see below).

### Register the server in your MCP client

Setup has two steps:

1. **Install the server once** — the steps above build the `openproject-mcp`
   binary in `.venv`, regardless of how many clients or projects you use.
2. **Register it per client** — each client needs its own config file pointing at
   that binary. Registration only points your client to the installed binary; it
   is not a second install. Using more than one client (say Claude *and* Codex)?
   Create one config file per client; they sit side by side.

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

**The installer can set up a detected client for you.** Before collecting your
settings, it asks whether to configure a detected client automatically. This adds
the server to that client's user-wide config, making it available in every
project. **The default is no** — project-specific config (below) gives finer
control and is recommended. When you opt in, only the `openproject` entry is added
and your existing config is backed up first.

To register manually, copy the `command` and `env` values from the installer's
`.mcp.json` into the file and format your client's guide shows — the values are
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
| Tools appear but writes fail | Writes are opt-in. Enable the relevant `OPENPROJECT_ENABLE_*_WRITE` flag and make sure the project is in `OPENPROJECT_ALLOWED_PROJECTS_WRITE`. |

**Uninstall**

- **Windows:** remove the install directory (`Remove-Item -Recurse -Force $env:USERPROFILE\openproject-mcp`) and delete the `openproject` entry from any client config you registered it in.
- **macOS / Linux:** `~/openproject-mcp/uninstall.sh`

---

## Configuration

Your client config (`.mcp.json`, `.codex/config.toml`, or `.vscode/mcp.json`) contains your API token. Treat it like a password. This repo gitignores `.mcp.json`, but when you place a project-scoped config in your **own** project, add it to that project's `.gitignore` so the token is never committed.

Access is grouped into five chains: `project`, `membership`, `work_package`, `version`, and `board`. Each chain has a read flag and a write flag. Scoped flags control each chain independently.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENPROJECT_BASE_URL` | yes | — | Base URL of your OpenProject instance, e.g. `https://op.example.com` |
| `OPENPROJECT_API_TOKEN` | yes | — | Personal API token |
| `OPENPROJECT_ALLOWED_PROJECTS_READ` | no | `*` | Readable projects; comma-separated identifiers, names, or glob patterns (e.g. `my-project,team-*`); `*` allows all visible projects |
| `OPENPROJECT_ALLOWED_PROJECTS_WRITE` | no | empty | Writable projects; empty disables all project-scoped writes; always intersected with read scope |
| `OPENPROJECT_ALLOWED_PROJECTS` | no | — | Backward-compatible alias for `OPENPROJECT_ALLOWED_PROJECTS_READ` |
| `OPENPROJECT_ENABLE_PROJECT_READ` | no | `true` | Projects, documents, news, wiki, lifecycle |
| `OPENPROJECT_ENABLE_WORK_PACKAGE_READ` | no | `true` | Work packages, relations, attachments, time entries |
| `OPENPROJECT_ENABLE_MEMBERSHIP_READ` | no | `true` | Memberships, roles, principals |
| `OPENPROJECT_ENABLE_VERSION_READ` | no | `true` | Versions |
| `OPENPROJECT_ENABLE_BOARD_READ` | no | `true` | Boards and views |
| `OPENPROJECT_HIDE_<ENTITY>_FIELDS` | no | empty | Comma-separated fields to omit from reads and reject on writes; `*` wildcards supported |
| `OPENPROJECT_HIDE_CUSTOM_FIELDS` | no | empty | Custom field names or keys to omit; `*` wildcards supported |
| `OPENPROJECT_ENABLE_ADMIN_WRITE` | no | `false` | User and group management (create/update/delete/lock users, create/update/delete groups). Must be set explicitly — not activated by any other write flag, and not prompted for by `configure_mcp.py`; edit `.mcp.json` by hand to enable it. |
| `OPENPROJECT_ENABLE_PROJECT_WRITE` | no | `false` | Project create/update/delete, news, documents, grids |
| `OPENPROJECT_ENABLE_MEMBERSHIP_WRITE` | no | `false` | Project membership create/update/delete |
| `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE` | no | `false` | Work-package create/update/delete, comments, relations, attachments, time entries |
| `OPENPROJECT_ENABLE_VERSION_WRITE` | no | `false` | Version create/update/delete |
| `OPENPROJECT_ENABLE_BOARD_WRITE` | no | `false` | Board create/update/delete |
| `OPENPROJECT_AUTO_CONFIRM_WRITE` | no | `false` | Skip the preview step for all writes |
| `OPENPROJECT_AUTO_CONFIRM_DELETE` | no | inherits `OPENPROJECT_AUTO_CONFIRM_WRITE` | Skip the preview step for deletes |
| `OPENPROJECT_TIMEOUT` | no | `12` | Request timeout in seconds |
| `OPENPROJECT_VERIFY_SSL` | no | `true` | Verify TLS certificates |
| `OPENPROJECT_DEFAULT_PAGE_SIZE` | no | `20` | Default results per page |
| `OPENPROJECT_MAX_PAGE_SIZE` | no | `50` | Hard cap on results per request |
| `OPENPROJECT_MAX_RESULTS` | no | `100` | Hard cap on total results returned by a tool |
| `OPENPROJECT_LOG_LEVEL` | no | `WARNING` | `CRITICAL`, `ERROR`, `WARNING`, or `INFO` |

Supported entities for `OPENPROJECT_HIDE_<ENTITY>_FIELDS`: `project`, `membership`, `role`, `principal`, `project_access`, `project_admin_context`, `project_configuration`, `job_status`, `project_phase_definition`, `project_phase`, `view`, `document`, `news`, `wiki_page`, `category`, `attachment`, `time_entry_activity`, `time_entry`, `work_package`, `relation`, `activity`, `version`, `board`, `current_user`, `instance_configuration`.

**Never share your API token** in chat messages, screenshots, or log output. If a token has been exposed, revoke it immediately in **My account → Access tokens** and create a new one.

---

## Tools

Tools are grouped by area: projects, memberships, users, groups, work packages, versions, boards, time entries, wiki, news, documents, notifications, grids, and more.

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

Five files, no deep abstractions:

- `config.py` — environment parsing and safe defaults
- `client.py` — HTTP access, policy checks, HAL normalization, preview/confirm writes
- `models.py` — compact dataclasses returned to MCP clients
- `tools.py` — validated MCP tool handlers
- `server.py` — FastMCP lifecycle wiring

`client.py` is intentionally large: all policy-sensitive logic (read gates, write gates, project scoping, field hiding) lives in one place to make it easier to audit.

See [docs/architecture.md](docs/architecture.md) for request flow details and the safety model.

---

## Development

### Set up

```bash
git clone https://github.com/jtauschl/openproject-mcp.git
cd openproject-mcp

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

Releases are cut manually — the project is not published to PyPI, and CI does not
publish anything. Every push and PR runs the test matrix plus a `build` job
(`uv build` + `uvx twine check dist/*`) so the package always stays buildable.

To cut a release:

1. Bump `version` in `pyproject.toml` and update `CHANGELOG.md`.
2. `uv run pytest` and `uv build` locally (CI enforces both).
3. Merge to `main`, then tag: `git tag vX.Y.Z && git push --tags`.
4. Create the GitHub release from the tag; attach the `dist/` artifacts if you
   want distributable builds.

---
