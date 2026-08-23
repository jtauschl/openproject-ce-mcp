# Context efficiency

<p align="center">
  <img src="../img/context-efficiency.jpg" alt="A dense API payload compressed into a small set of structured, agent-ready records." width="960">
</p>

A core reason to use this MCP instead of calling the OpenProject REST API
directly: it returns agent-shaped, context-frugal responses. The raw v3 API
answers a list request with full HAL payloads — every element carries ~21
top-level fields plus ~46 `_links`. The MCP returns a compact summary per row,
drops derivable and duplicated fields, and lets the agent request only the
fields it needs.

This page is the maintained, authoritative source for the methodology and
measurements behind the short numbers quoted in the [README](../README.md).
Update both places together when the numbers change (e.g. after a toolset
change) — the README table is a deliberately duplicated snapshot, not a link
target that auto-syncs.

## Response size

Measured against the same three representative work packages, using
[tiktoken](https://github.com/openai/tiktoken)'s `cl100k_base` encoding (the
GPT-4-family tokenizer) as a real-tokenizer stand-in — no public tokenizer
exists for Claude models, so this is a consistent, reproducible
approximation, not an exact Claude token count, but a real BPE tokenizer
rather than the bytes/4 approximation used in earlier revisions of this page.
Reproducible with [`tools/measure-context.py`](https://github.com/jtauschl/openproject-ce-mcp/blob/main/tools/measure-context.py)
(`uv sync --extra measure` first) against a local Docker test instance.
Covers list, single-read, search, a confirmed write, and batch operations —
not just one call shape — each compared against the equivalent raw
OpenProject REST API v3 (HAL) call(s):

| Call | Raw API tokens | MCP tokens | vs. raw |
|---|---:|---:|---:|
| `list_work_packages` (3 rows) | ~10,139 | ~713 | **−93%** |
| `list_work_packages` with `select` (5 fields) | ~10,139 | ~144 | **−99%** |
| `get_work_package` (single read) | ~3,424 | ~409 | **−88%** |
| `search_work_packages` (8 rows) | ~21,066 | ~2,067 | **−90%** |
| `update_work_package` (confirmed write) | ~3,425 | ~461 | **−87%** |
| `bulk_create_work_packages` (×5, vs. 5 raw POSTs) | ~15,612 | ~1,173 | **−92%** |
| `bulk_update_work_packages` (×5, vs. 5 raw PATCHes) | ~15,617 | ~1,208 | **−92%** |

The savings are consistent across call shapes — this isn't a one-off number
for list responses specifically. `select` remains the largest additional,
opt-in lever on top of the baseline MCP trimming.

## The cost of null-vs-absent distinguishability

Not every context-shaping property is a saving. A caller needs to be able to
tell "this field is unset (`null`)" apart from "this field was never
returned" — otherwise a missing key is ambiguous. `elide_none`, derived
per-tool from whether the tool's own signature accepts `select`, controls
whether `None`-valued fields are dropped; a field requested via `select` is
always kept even when its value is `null`; and `next_offset` is never
dropped, since a caller pages until it comes back `null`, not until it's
absent. This makes some responses slightly *larger* than a maximal-elision
policy would — a deliberate, measured trade-off, not a regression.

The table below is **not** a before/after of two released versions — no
version of this MCP ever shipped a policy that eliminated `None` on
select-less tools or dropped a selected `null`, so "eliding `None`" is a
hypothetical maximal-elision counterfactual, not this MCP's actual prior
behavior. It quantifies what the real, registered null-preserving behavior
costs relative to that hypothetical baseline. Measured against 50 real
seeded work packages (the first page fetched by `tools/measure-context.py`,
not an invented `None` distribution — real field-population patterns are
uneven, e.g. `responsible` is unset on nearly every seeded row here,
`priority` on very few, so a synthetic 50/50 split would misrepresent the
actual cost):

| Scenario | Maximal elision (hypothetical) | Explicit `null` (real behavior) | Cost |
|---|---:|---:|---:|
| Full rows, simulating a select-less tool (50 rows) | ~7,933 tokens | ~14,421 tokens | **+82%** |
| `select=[id,subject,responsible]` (50 rows, all 50 with `responsible=None`) | ~793 tokens | ~1,093 tokens | **+38%** |

Reproducible with the same `tools/measure-context.py` script (its "Cost of
null-vs-absent distinguishability" section) — it needs the same Docker test
instance as the table above, though it fetches its own separate page of rows
(see the script's comments for the exact query). The first scenario is the
larger of the two because it affects *every* field on a tool with no
`select` parameter at all (e.g. `list_statuses`, one of several list tools
whose return type happens to carry a `results` field but has no `select` in
its own signature — see `tools_runtime.py`'s `register_selected_tools()`, specifically the
inner `tool()` wrapper's `elide_none` check, for how that
distinction is derived from the real function signature, not guessed from
the return type; simulated here on work-package rows since this
instance's 14 seeded statuses are all fully populated and would show no
elidable fields at all). The second scenario is narrower: only fields
actually named in `select` are affected, so the cost scales with how much of
a row a caller asks for, not with the whole row — here it happens to be
worst-case (every row's `responsible` was `None` in this seed data).

## Tool catalog size

The tool set itself is trimmed too, mainly by not emitting redundant output
schemas. A fresh, unconfigured install — the actual default state, before
`OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS` are set — registers
only the small set of project-independent read tools: 12 tools, ~2.4k tokens
(project-scoped read tools additionally require a non-empty
`OPENPROJECT_READ_PROJECTS`, since one that can only ever return an empty
result or a permission error would just be dead catalog weight). Project-scoped
write tools are only registered once **both** allowlists are non-empty (same
reasoning, applied to `OPENPROJECT_WRITE_PROJECTS`); once granted, and with
every write scope enabled — the worst case — the `tools/list` payload is 121
tools, ~43k tokens. Turning on the rarely-used `extended` metadata tools
(`OPENPROJECT_ENABLE_EXTENDED_READ=true`, see
[Configuration](configuration.md#tool-groups)) on top of that adds 12 more
tools, ~45k tokens. Confirmed writes also drop the echoed request `payload`.

### Server instructions are sent once, not per tool

The server-level CE usage notes (`CE_INSTRUCTIONS` in `server.py`, surfaced via
the spec-standard MCP `initialize.instructions` field) are carried exactly
once — `tools/measure-context.py` verifies no registered tool's own
`description` duplicates them (a regression test,
`test_ce_instructions_are_not_duplicated_into_any_tool_description` in
`tests/test_server.py`, pins this). If a client duplicated them into every
tool description instead, the worst-case `tools/list` payload above would
balloon roughly 4x. This has been observed happening in practice with a
real MCP client during tool discovery — attributed to the client's own
MCP-to-function-schema translation (many function-calling APIs have no
separate slot for server-wide notes), not to this server or to MCPServer's
`Tool.description` construction (built solely from each function's own
docstring). No local
workaround was added — copying instructions into every tool description here
would just make the non-duplicating case duplicate too.

## Reproducing these numbers

```bash
uv sync --extra measure   # installs tiktoken for real token counts
python tools/measure-context.py
```

The tool-catalog part needs no live instance. The response-size table and the
null-vs-absent cost section both need a local Docker test instance:

```bash
docker/test/up.sh 17
```

then point the script at it as described in the script's own docstring
(`OPENPROJECT_BASE_URL`, `OPENPROJECT_API_TOKEN`, `OPENPROJECT_TEST_PROJECT`
pointed at the seeded test instance).

## See also

- [Documentation hub](README.md) — full documentation index
- [Configuration](configuration.md) — the tool-exposure flags and other context-budget variables
- [Development](../CONTRIBUTING.md) — running the Docker test instances
