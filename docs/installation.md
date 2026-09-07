# Installation

<p align="center">
  <img src="../img/setup-workflow.jpg" alt="A Python package flowing through a successful terminal setup into several MCP clients." width="960">  <!-- markdownlint-disable-line MD013 -->
</p>

This page covers installing, updating, and removing the `openproject-ce-mcp`
package itself. For registering the installed server with a specific MCP client,
see [Clients](clients.md). For what `openproject-ce-mcp configure` asks and
every environment variable it can set, see [Configuration](configuration.md).

## Requirements

| | |
| --- | --- |
| Python | 3.10 or later |
| OpenProject | Community Edition 16.1 or later (source-audited through 17.8, runtime-smoke-tested through 17.8), API v3 accessible |
| OS | macOS 12+, Linux, or Windows 10/11 |

## Prepare your OpenProject instance

An administrator must enable API token creation once, under
**Administration → API and webhooks → API**:

| Setting | Recommended |
| --- | --- |
| Enable API tokens | checked |
| Write access to read-only attributes | unchecked |
| Enable CORS | unchecked |

To create a personal token: **My account → Access tokens → + API token**. Copy
the token immediately — it is only shown once. Format: `opapi-...`.

## Install

This package ships two globally-runnable console commands (`openproject-ce-mcp`
and `openproject-ce-mcp configure`), the kind of standalone CLI tool
[`pipx`](https://pipx.pypa.io/) is designed for: each tool gets its own isolated
environment while staying available on your `PATH`, without the version
conflicts a plain `pip install` into your system Python can cause. `pipx` does
not ship with Python — install it once per machine:

```bash
# macOS
brew install pipx
pipx ensurepath

# Linux
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# Windows (PowerShell)
py -m pip install --user pipx
py -m pipx ensurepath
```

See the [official pipx installation
guide](https://pipx.pypa.io/stable/installation/) for other package managers.
Then:

```bash
pipx install openproject-ce-mcp
openproject-ce-mcp configure
openproject-ce-mcp --version
```

`configure` collects your OpenProject URL, API token, project scope, and whether
writes should be enabled. It then writes the config for the MCP client(s) you
choose. See [Clients](clients.md) for which client to pick and where each config
file lives, and [Configuration](configuration.md) for what the wizard asks and
every setting it can write.

Restart your MCP client after installation or configuration, then ask it to call
`get_current_user` or `list_projects` to verify.

### If you already use uv

[`uv`](https://github.com/astral-sh/uv)'s own tool-install mode works the same
way `pipx` does — isolated per-tool environment, available on `PATH`:

```bash
uv tool install openproject-ce-mcp
openproject-ce-mcp configure
```

Prefer this over `pipx` only if you already have `uv` installed for other
reasons; it isn't worth installing just for this package over `pipx`.

### Plain pip

Use `pip install openproject-ce-mcp` only inside an environment you're already
managing explicitly — a virtualenv, a container, or a project that pins its own
dependencies. A bare `pip install` into your system/user Python is not
recommended: it skips the isolation `pipx`/`uv tool` give you, and can conflict
with other Python tools on the same interpreter.

### Run without installing

`uvx openproject-ce-mcp` runs the package on demand via `uv`, with no persistent
install at all. This is a client-config detail, not a separate install method:
point your MCP client's `command` at `uvx` with args `["openproject-ce-mcp"]`
instead of running `configure` — see [Clients](clients.md) for the per-client
config shape.

## Update

Upgrade the installed PyPI package, then restart your MCP client:

```bash
pipx upgrade openproject-ce-mcp
openproject-ce-mcp --version
```

If you installed with another tool:

```bash
uv tool install --upgrade openproject-ce-mcp
# or, inside the environment you installed it into:
pip install --upgrade openproject-ce-mcp
```

No config rewrite is usually needed after an update. Re-run `openproject-ce-mcp
configure` only when you want to change client targets, project scope, write
access, or advanced settings.

## Development / from source

Contributing, or want to run an unreleased branch? Clone the repository and set
up a development environment — see
[Development](https://github.com/jtauschl/openproject-ce-mcp/blob/main/CONTRIBUTING.md#set-up)
for the exact commands (`git clone` + `uv sync --dev`, or a plain `venv` + `pip
install -e ".[dev]"` alternative). Run the setup wizard from that checkout with
`python3 configure_mcp.py` (or `uv run python configure_mcp.py` if you used
`uv`) instead of the installed `openproject-ce-mcp configure` command.

## Uninstall

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
pipx uninstall openproject-ce-mcp   # or: uv tool uninstall openproject-ce-mcp
                                    # or: pip uninstall openproject-ce-mcp
```

A source checkout's own `.venv` and caches are just local files — remove the
checkout directory (or `rm -rf .venv .pytest_cache .ruff_cache`) directly once
you've run `configure --uninstall` from it as above.

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — which client to register with and where its config
  lives
- [Configuration](configuration.md) — wizard modes and the full environment
  variable reference
- [Troubleshooting](troubleshooting.md) — `doctor` diagnostics and common setup
  issues
