# Documentation

<p align="center">
  <img src="../img/docs-overview.jpg" alt="A luminous documentation map connecting setup, tools, security, and analytics." width="960">
</p>

Full documentation for `openproject-ce-mcp`, organized by what you're trying
to do. Start at the [project README](../README.md) for the product overview
and quickstart; use this page to find the detail page you need.

## Getting started

- **[Installation](installation.md)** — install, update, and uninstall the
  package with pipx or uv; source install; OpenProject-side prerequisites.
- **[Clients](clients.md)** — choose the right client guide, understand
  global vs. project-scoped registration, and see where each client's config
  file lives.
- **[Configuration](configuration.md)** — what the `configure` wizard asks in
  quick vs. advanced mode, and the full environment variable reference.
- **[Troubleshooting](troubleshooting.md)** — the `doctor` diagnostic
  command, exit codes, and fixes for common setup problems.

## Client guides

Pick the guide for the MCP client you use — each covers registration, credential
protection, reload, and verification for that specific client:

- **[Claude / Claude Code](claude.md)**
- **[Claude Desktop app](claude-desktop.md)**
- **[Codex](codex.md)**
- **[Cursor](cursor.md)**
- **[VS Code / GitHub Copilot](github.md)**

## Using the tools

- **[Tool reference](tools.md)** — every MCP tool this server exposes, grouped
  by area, plus the write preview/confirm pattern and error categories.
- **[Work package filters](filters.md)** — filter keys, operators, and type
  strategies accepted by `list_work_packages` / `search_work_packages`.
- **[Field hiding](field-hiding.md)** — the full list of entities supported by
  `OPENPROJECT_HIDE_<ENTITY>_FIELDS`.

## For contributors

- **[Development](development.md)** — dev environment setup, running unit and
  integration tests, the Docker test instances, and API-drift checks.
- **[Architecture](architecture.md)** — module layout, request flow, naming
  conventions, and the defense-in-depth safety model.
- **[Context efficiency](context-efficiency.md)** — the methodology and full
  measurements behind the README's token-savings numbers, and how to
  reproduce them.

## Security

- **[Security policy](../SECURITY.md)** — supported versions, vulnerability
  reporting, and the prompt-injection threat model.
- **[Release checklist](../RELEASE.md)** — the maintainer release checklist.
