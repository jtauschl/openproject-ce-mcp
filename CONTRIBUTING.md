# Development

<p align="center">
  <img src="img/development.jpg" alt="A Python development pipeline passing source modules through tests and containers into a verified package." width="960">
</p>

## Where to send a pull request

`main` is not the active development branch — it stays frozen at the last
finalized release. Active work happens on two parallel release branches:
the current `release/0.4.x` bugfix branch (fixes for the released version;
check the repo's branch list for the exact version) and `release/0.5.0`
(new development for the next release). Clone and base your PR on
whichever of these matches the code you're touching, not `main` — a
checkout of `main` (or a PR against it) leaves you on a frozen snapshot
and needing manual re-application onto the correct release branch. A fix
landing on the current `release/0.4.x` branch is forward-merged into
`release/0.5.0` (never cherry-picked, unless explicitly justified) so the
next release always carries every prior bugfix.

## Set up

```bash
# bugfix on the released version (layered `app/` architecture):
git clone -b release/0.4.1 https://github.com/jtauschl/openproject-ce-mcp.git

# new development for the next release (layered `app/` architecture):
git clone -b release/0.5.0 https://github.com/jtauschl/openproject-ce-mcp.git

cd openproject-ce-mcp

# option A: uv (recommended)
uv sync --dev

# option B: venv + pip
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Run tests

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

For local, throwaway instances across every supported OpenProject minor (16.0 through the latest — see [`docker/test/README.md`](docker/test/README.md) for exactly which versions and why each one matters), see [`docker/test/`](https://github.com/jtauschl/openproject-ce-mcp/tree/main/docker/test) — `docker/test/up.sh` boots and seeds them and prints the env block to run the integration tests against each. To verify the client's API assumptions against the OpenProject source across releases, see [`tools/api-check/`](https://github.com/jtauschl/openproject-ce-mcp/tree/main/tools/api-check).

## After code changes

The MCP server runs as a subprocess. After any code change, restart your MCP client before updated tools become active.

## Releasing

The package is published to [PyPI](https://pypi.org/project/openproject-ce-mcp/)
via GitHub Actions using [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC — no API token stored), triggered by pushing a `vX.Y.Z` tag. Every push
and PR also runs the test matrix plus a `build` job (`uv build` +
`uvx twine check dist/*`) so the package always stays buildable.

## See also

- [Documentation hub](docs/README.md) — full documentation index
- [Architecture](docs/architecture.md) — module layout, request flow, and the safety model
