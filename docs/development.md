# Development

<p align="center">
  <img src="../img/development.jpg" alt="A Python development pipeline passing source modules through tests and containers into a verified package." width="960">
</p>

## Set up

```bash
git clone https://github.com/jtauschl/openproject-ce-mcp.git
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

For local, throwaway instances across the OpenProject versions where the API changed (16.6 classic + 17.4 displayId + 17.5 semantic/workspaces), see [`docker/test/`](../docker/test/) — `docker/test/up.sh` boots and seeds them and prints the env block to run the integration tests against each. To verify the client's API assumptions against the OpenProject source across releases, see [`tools/api-check/`](../tools/api-check/).

## After code changes

The MCP server runs as a subprocess. After any code change, restart your MCP client before updated tools become active.

## Releasing

The package is published to [PyPI](https://pypi.org/project/openproject-ce-mcp/)
via GitHub Actions using [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC — no API token stored), triggered by pushing a `vX.Y.Z` tag. Every push
and PR also runs the test matrix plus a `build` job (`uv build` +
`uvx twine check dist/*`) so the package always stays buildable. See
[RELEASE.md](../RELEASE.md) for the maintainer release process.

## See also

- [Documentation hub](README.md) — full documentation index
- [Architecture](architecture.md) — module layout, request flow, and the safety model
- [Release checklist](../RELEASE.md) — maintainer release checklist
