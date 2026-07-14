# Installation

<p align="center">
  <img src="../img/setup-workflow.jpg" alt="A Python package flowing through a successful terminal setup into several MCP clients." width="960">
</p>

This page covers installing, updating, and removing the `openproject-ce-mcp`
package itself. For registering the installed server with a specific MCP
client, see [Clients](clients.md). For what `openproject-ce-mcp configure`
asks and every environment variable it can set, see
[Configuration](configuration.md).

## Requirements

| | |
|---|---|
| Python | 3.10 or later |
| git | only for the "install from source" path (clones this repository) |
| OpenProject | Community Edition 16.1 or later (reviewed for compatibility through 17.5), API v3 accessible |
| OS | macOS 12+, Linux, or Windows 10/11 |

## Prepare your OpenProject instance

An administrator must enable API token creation once:

**Administration → API and webhooks → API**

| Setting | Recommended |
|---|---|
| Enable API tokens | checked |
| Write access to read-only attributes | unchecked |
| Enable CORS | unchecked |

To create a personal token: **My account → Access tokens → + API token**. Copy the token immediately — it is only shown once. Format: `opapi-...`.

## Install pipx (prerequisite)

[`pipx`](https://pipx.pypa.io/) installs Python CLI tools into isolated
environments and is the recommended way to install this package. It does not
ship with Python — install it once per machine:

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

See the [official pipx installation guide](https://pipx.pypa.io/stable/installation/) for other package managers.

[`uv`](https://github.com/astral-sh/uv) is a faster alternative to pipx, but it must also be installed first — see the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/). `uvx`, which is included with `uv`, can instead run the package on demand without installing `openproject-ce-mcp` as a persistent tool — see [Advanced install alternatives](#advanced-install-alternatives) below.

## Install

```bash
pipx install openproject-ce-mcp
openproject-ce-mcp configure
openproject-ce-mcp --version
```

`configure` collects your OpenProject URL, API token, project scope, and
whether writes should be enabled. It then writes the config for the MCP
client(s) you choose. See [Clients](clients.md) for which client to pick and
where each config file lives, and [Configuration](configuration.md) for what
the wizard asks and every setting it can write.

Restart your MCP client after installation or configuration, then ask it to
call `get_current_user` or `list_projects` to verify.

## Update

Upgrade the installed PyPI package, then restart your MCP client:

```bash
pipx upgrade openproject-ce-mcp
openproject-ce-mcp --version
```

If you installed with another tool:

```bash
uv tool install --upgrade openproject-ce-mcp
# or
pip install --upgrade openproject-ce-mcp
```

No config rewrite is usually needed after an update. Re-run
`openproject-ce-mcp configure` only when you want to change client targets,
project scope, write access, or advanced settings.

## Advanced install alternatives

Use these when `pipx` is not the right fit for your environment:

```bash
uv tool install openproject-ce-mcp
pip install openproject-ce-mcp
```

With `uv`, you can also skip installing entirely and point your client's
`command` at `uvx` with args `["openproject-ce-mcp"]`. Treat this as an
advanced client-config option; the normal path is to install once and let
`configure` write the client config.

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

PyPI and source installs use the same setup flow after installation — see
[Clients](clients.md) and [Configuration](configuration.md) for what happens next.

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

<details>
<summary><b>Uninstalling a source install</b></summary>

If you installed from source, `uninstall.sh` / `uninstall.ps1` also remove the
local environment (`.venv`, caches, the API-source clones) in addition to
unregistering the client entries:

- **Windows:** `.\uninstall.ps1` (then remove the install dir if you want: `Remove-Item -Recurse -Force $env:USERPROFILE\openproject-ce-mcp`)
- **macOS / Linux:** `~/openproject-ce-mcp/uninstall.sh`

</details>

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — which client to register with and where its config lives
- [Configuration](configuration.md) — wizard modes and the full environment variable reference
- [Troubleshooting](troubleshooting.md) — `doctor` diagnostics and common setup issues
