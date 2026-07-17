# OpenProject CE MCP

[![PyPI](https://img.shields.io/pypi/v/openproject-ce-mcp.svg)](https://pypi.org/project/openproject-ce-mcp/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/jtauschl/openproject-ce-mcp/blob/main/LICENSE)
[![MCP](https://img.shields.io/badge/protocol-MCP%20stdio-purple.svg)](https://modelcontextprotocol.io)

<p align="center">
  <img src="https://raw.githubusercontent.com/jtauschl/openproject-ce-mcp/main/img/openproject-ce-mcp-hero.jpg" alt="Hero image showing a Python terminal and an OpenProject board connected by a structured data stream." width="960">
</p>

An MCP server for OpenProject that lets local AI agents read and manage project data through structured, guarded tools.

The server runs as a local subprocess of your MCP client over stdio. It wraps OpenProject API v3 and exposes typed tools for projects, work packages, memberships, versions, boards, time entries, and more.

> **Reading this on PyPI?** All links below point to the GitHub repository —
> the `docs/` pages and images ship in the git repo and source distribution,
> not in the installed package itself.

## Why use this MCP

- **Context-frugal by design** — compact, agent-shaped responses instead of raw HAL payloads (~21 fields + ~46 links per item in the raw API). Measured up to **−98%** tokens per response with `select`; see [Context efficiency](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/context-efficiency.md) for the full numbers.
- **Guarded writes** — every write follows a preview-then-confirm pattern; there is no way to bypass it.
- **Defense-in-depth project scope** — MCP read/write allowlists restrict the token's effective scope in addition to OpenProject's own server-side permissions.
- **Typed tools, not a raw REST client** — one call per intent (list, search, create, update) instead of hand-built HAL requests and link-following.

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

All write operations follow a preview-then-confirm pattern: call a tool once to get a validated preview, then again with `confirm=true` to execute. There is no way to bypass this.

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

## How it works

- Communicates with the MCP client over stdio — no remote server, no persistent storage
- Read tools are registered by default, but no project data is accessible until `OPENPROJECT_READ_PROJECTS` is configured
- The 5 core write categories are enabled by default, but stay inert until a project is listed in `OPENPROJECT_WRITE_PROJECTS` — that allowlist, not the category flags, is the real gate; personal-data and admin writes stay opt-in separately
- Create and update operations validate the payload against OpenProject form endpoints before writing; delete and other simple operations execute directly once confirmed
- Project scope is enforced server-side: the MCP only exposes what the configured allowlists permit
- Responses are bounded and paginated — compact summaries, not raw HAL payloads

A core reason to use this MCP instead of calling the OpenProject REST API
directly: it returns context-frugal responses instead of raw HAL payloads —
and not just for listing. The numbers below are measured against the same
three representative work packages; read/search/write/batch calls all land
in the same **−82% to −98%** range. For the full per-call-type breakdown,
the tool-catalog size numbers, and how to reproduce them, see
[Context efficiency](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/context-efficiency.md).

| Response | Tokens | vs. raw API |
|---|---:|---:|
| Raw OpenProject REST API v3 (HAL) | ~7,950 | baseline |
| `list_work_packages` (MCP) | ~1,080 | **−86%** |
| `list_work_packages` with `select` (5 fields) | ~120 | **−98%** |

---

## Install

This quickstart requires [`pipx`](https://pipx.pypa.io/); see [Installation](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/installation.md) if it isn't installed yet.

```bash
pipx install openproject-ce-mcp
openproject-ce-mcp configure
openproject-ce-mcp --version
```

`configure` collects your OpenProject URL, API token, and project scope, then
writes the config for the MCP client(s) you choose. Project-scoped is
recommended: the server is then available only in the current project.
Global makes it available everywhere. Restart your MCP client afterward,
then ask it to call `get_current_user` or `list_projects` to verify.

See [Installation](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/installation.md) for requirements, updating, source
installs, and uninstalling, and [Clients](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/clients.md) for per-client
setup guides.

---

## Documentation

Full documentation lives in [`docs/`](https://github.com/jtauschl/openproject-ce-mcp/tree/main/docs), starting at the
[documentation hub](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/README.md):

- **Setup:** [Installation](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/installation.md) · [Clients](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/clients.md) · [Configuration](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/configuration.md) · [Troubleshooting](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/troubleshooting.md)
- **Using the tools:** [Tool reference](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/tools.md) · [Work package filters](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/filters.md) · [Field hiding](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/field-hiding.md)
- **Client guides:** [Claude / Claude Code](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/claude.md) · [Claude Desktop](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/claude-desktop.md) · [Codex](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/codex.md) · [Cursor](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/cursor.md) · [VS Code / GitHub Copilot](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/github.md)
- **Contributing:** [Development](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/development.md) · [Architecture](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/architecture.md) · [Context efficiency](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/context-efficiency.md)

---

## Configuration essentials

Your client config (`.mcp.json`, `.codex/config.toml`, or `.vscode/mcp.json`)
contains your API token — treat it like a password and keep it out of version
control; choose your client-specific guide from [Clients](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/clients.md)
for the exact `.gitignore` step. `configure` writes a minimal config: only the values that differ from a
safe default. Read tools are registered by default, and so are the 5 core
write categories — but project access stays denied either way until you list
projects in `OPENPROJECT_READ_PROJECTS` (and, for writes, in
`OPENPROJECT_WRITE_PROJECTS` too); that allowlist pair, not the category
flags, is the real gate.

See [Configuration](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/configuration.md) for the full environment variable
reference and what `configure --quick` vs. `--advanced` ask.

---

## Security

### Prompt Injection

User-provided text (work-package descriptions, comments, news, wiki content) is marked with `<user-content>` tags and flagged in server instructions as untrusted. Agents should treat this content as data, not as instructions.

See [SECURITY.md](https://github.com/jtauschl/openproject-ce-mcp/blob/main/SECURITY.md) for the full security model, including prompt injection mitigations, reporting procedures, and supported versions.

---

## Development

```bash
git clone https://github.com/jtauschl/openproject-ce-mcp.git
cd openproject-ce-mcp
uv sync --dev
uv run pytest
```

See [Development](https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/development.md) for the full test suite (unit,
integration, and Docker test instances) and [RELEASE.md](https://github.com/jtauschl/openproject-ce-mcp/blob/main/RELEASE.md) for the
maintainer release process.
