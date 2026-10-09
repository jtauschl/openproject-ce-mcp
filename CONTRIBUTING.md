# Development

<p align="center">
  <img src="img/development.jpg" alt="A Python development pipeline passing source modules through tests and containers into a verified package." width="960">
</p>

## Where to send a pull request

`main` is frozen at the last release. Base your PR on the branch that
matches your change:

- `release/0.4.3`: bugfixes for the released version.
- `release/0.5.0`: new development for the next release.

Fixes on `release/0.4.3` are carried into `release/0.5.0` by the maintainer,
so a fix needs only one PR.

## Set up

```bash
# bugfix on the released version:
git clone -b release/0.4.3 https://github.com/jtauschl/openproject-ce-mcp.git

# new development for the next release:
git clone -b release/0.5.0 https://github.com/jtauschl/openproject-ce-mcp.git

cd openproject-ce-mcp

# option A: uv (recommended)
uv sync --dev

# option B: venv + pip
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Run tests

Before pushing, run the full gate: `./dev ci` (lint, types, tests with the
coverage gate, build). Besides `uv`, it needs `shellcheck`, `shfmt` 3.14.1
and `actionlint` on your `PATH`. `./dev test` runs the unit tests alone.

**Unit tests** (no network — run against `httpx` mocks):

```bash
# uv
uv run pytest

# venv
.venv/bin/python -m pytest
```

**Integration tests** (require a disposable, non-production OpenProject instance; they create, update and delete data):

```bash
OPENPROJECT_BASE_URL=https://op.example.com \
OPENPROJECT_API_TOKEN=opapi-... \
OPENPROJECT_TEST_PROJECT=mcp-test \
uv run pytest -m integration -v
```

`OPENPROJECT_TEST_PROJECT` is the project identifier used for write tests (default: `mcp-test`). Integration tests are excluded from the default run (`-m 'not integration'`) and must be opted in explicitly.

For local, throwaway instances across every supported OpenProject minor (16.0 through the latest — see [`docker/test/README.md`](docker/test/README.md) for exactly which versions and why each one matters), see [`docker/test/`](docker/test/) — `docker/test/up.sh` boots and seeds them and prints the env block to run the integration tests against each. To verify the client's API assumptions against the OpenProject source across releases, see [`tools/api-check/`](tools/api-check/).

## After code changes

The MCP server runs as a subprocess. After any code change, restart your MCP client before updated tools become active.

## Conventions

### Design

- **Every write is preview-then-confirm, with no way around it.** OpenProject's own permissions stay the final authority.
- **Add a tool for a capability, not for an endpoint.** Follow the [Tool catalog conventions](docs/architecture.md#tool-catalog-conventions) for naming, `get_*` versus `list_*`, group placement, and descriptions.
- **Keep the context cost low.** Every enabled tool's description adds to a fixed catalog cost in every session. Every field a response returns adds to the cost of each call.
- **Check OpenProject behavior against its source**, not only against the published spec.
- **Follow the existing pattern.** Don't add defensive code for cases that can't happen.

### Code and tests

- **Test the actual claim**, not just that the code path ran. A new client method needs both a unit test and an integration test.
- **Tool docstrings are short and state the contract:** what the tool does, any non-obvious or consequential effects (such as notifications or irreversibility), and constraints the schema can't express. Don't repeat parameter types or the server instructions.
- **Inline comments explain WHY, never WHAT.** Comment only what the code can't show: a hidden constraint, a workaround, an invariant. Don't include history, dates, or PR and ticket references.
- **Don't silence lint or type findings locally.** The one exception is a genuine false positive: suppress it with the rule ID and a one-line reason.

### Commits, changelog, PRs

- **Use an imperative commit subject under ~72 characters.** Put the WHY, spec deviations, and how you verified the change in the body.
- **The CHANGELOG records the user-visible WHAT, never the WHY.** Keep entries as short as possible. Skip internal changes. Mark breaking changes with **Breaking:**.
- **Keep one concern per PR.**
- **Everything committed is in English.**

## See also

- [Documentation hub](docs/README.md) — full documentation index
- [Architecture](docs/architecture.md) — module layout, request flow, and the safety model
