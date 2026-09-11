# Context efficiency

<p align="center">
  <img src="../img/context-efficiency.jpg" alt="A dense API payload compressed into a small set of structured, agent-ready records." width="960">  <!-- markdownlint-disable-line MD013 -->
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

Measured on the 0.4.0 release against a local OpenProject 17.8 test
instance. Token counts use
[tiktoken](https://github.com/openai/tiktoken)'s `o200k_base` encoding as a
stable, reproducible BPE proxy; they are not the exact billed count for every
model, provider, or MCP client. The response figures are a representative
snapshot of real instance content, so reruns can vary with descriptions,
populated fields, and accumulated test rows. Reproduce them with
[`tools/measure-context.py`](../tools/measure-context.py) after installing the
`measure` extra. The script covers list, single-read, search, a confirmed
write, and batch operations, each compared with the equivalent raw OpenProject
REST API v3 (HAL) call or calls:

| Call | Raw API tokens | MCP tokens | vs. raw |
| --- | ---: | ---: | ---: |
| `list_work_packages` (3 rows) | ~9,992 | ~861 | **−91%** |
| `list_work_packages` with `select` (5 fields) | ~9,992 | ~174 | **−98%** |
| `get_work_package` (single read) | ~3,378 | ~461 | **−86%** |
| `search_work_packages` (1 row) | ~6,946 | ~329 | **−95%** |
| `update_work_package` (confirmed write) | ~3,379 | ~512 | **−85%** |
| `bulk_create_work_packages` (×5, vs. 5 raw POSTs) | ~15,012 | ~1,354 | **−91%** |
| `bulk_update_work_packages` (×5, vs. 5 raw PATCHes) | ~15,017 | ~1,389 | **−91%** |

The savings are consistent across call shapes — this isn't a one-off number for
list responses specifically. `select` remains the largest additional, opt-in
lever on top of the baseline MCP trimming.

## The cost of null-vs-absent distinguishability

Not every context-shaping property is a saving. A caller needs to be able to
tell "this field is unset (`null`)" apart from "this field was never returned" —
otherwise a missing key is ambiguous. `elide_none`, derived per-tool from
whether the tool's own signature accepts `select`, controls whether
`None`-valued fields are dropped; a field requested via `select` is always kept
even when its value is `null`; and `next_offset` is never dropped, since a
caller pages until it comes back `null`, not until it's absent. This makes some
responses slightly *larger* than a maximal-elision policy would — a deliberate,
measured trade-off, not a regression.

The table below is **not** a before/after of two released versions — no version
of this MCP ever shipped a policy that eliminated `None` on select-less tools or
dropped a selected `null`, so "eliding `None`" is a hypothetical maximal-elision
counterfactual, not this MCP's actual prior behavior. It quantifies what the
real, registered null-preserving behavior costs relative to that hypothetical
baseline. Measured against 20 real seeded work packages (the first page fetched
by `tools/measure-context.py`, not an invented `None` distribution — real
field-population patterns are uneven, e.g. `responsible` is unset on nearly
every seeded row here, `priority` on very few, so a synthetic 50/50 split would
misrepresent the actual cost):

| Scenario | Maximal elision (hypothetical) | Explicit `null` (real behavior) | Cost |
| --- | ---: | ---: | ---: |
| Full rows, simulating a select-less tool (20 rows) | ~3,968 tokens | ~6,669 tokens | **+68%** |
| `select=[id,subject,responsible]` (20 rows, all with `responsible=None`) | ~356 tokens | ~475 tokens | **+33%** |

Reproducible with the same `tools/measure-context.py` script (its "Cost of
null-vs-absent distinguishability" section) — it needs the same Docker test
instance as the table above, though it fetches its own separate page of rows
(see the script's comments for the exact query). The first scenario is the
larger of the two because it affects *every* field on a tool with no `select`
parameter at all (e.g. `list_statuses`, one of several list tools whose return
type happens to carry a `results` field but has no `select` in its own signature
— see `tools_runtime.py`'s `register_selected_tools()`, specifically the inner
`tool()` wrapper's `elide_none` check, for how that distinction is derived from
the real function signature, not guessed from the return type; simulated here on
work-package rows since this instance's 14 seeded statuses are all fully
populated and would show no elidable fields at all). The second scenario is
narrower: only fields actually named in `select` are affected, so the cost
scales with how much of a row a caller asks for, not with the whole row — here
it happens to be worst-case (every row's `responsible` was `None` in this seed
data).

## Tool catalog size

The tool set itself is trimmed too, mainly by not emitting redundant output
schemas. A fresh, unconfigured install registers only project-independent read
tools. Project-scoped reads require a non-empty `OPENPROJECT_READ_PROJECTS`;
writes require the corresponding feature flag and a non-empty
`OPENPROJECT_WRITE_PROJECTS`. This avoids advertising tools that can only
return an empty result or a permission error.

These figures are exact snapshots of the serialized `tools/list` payload for
the measured source tree. Unlike response sizes, they do not depend on live
OpenProject data. They are still a context-size proxy: an MCP client or model
provider may transform or cache the catalog before billing it.

| Configuration | Tools | Catalog tokens |
| --- | ---: | ---: |
| Fresh install, no project scope | 14 | ~3,677 |
| Project reads, no writes | 85 | ~35,923 |
| Work-package writes only | 147 | ~56,018 |
| Every write scope | 168 | ~61,432 |
| Every write scope plus extended metadata | 180 | ~63,349 |

The extended metadata group adds 12 rarely used tools and is opt-in through
`OPENPROJECT_ENABLE_EXTENDED_READ=true`; see
[Configuration](configuration.md#tool-groups). Confirmed writes also omit the
echoed request `payload` from their response.

### Practical configuration examples

For issue triage, grant only the projects that should be searchable and leave
all write flags off:

```env
OPENPROJECT_READ_PROJECTS=OPM,TST
```

Then request only the fields needed for the next decision, for example:

```text
list_work_packages(
  project="OPM",
  select=["id", "display_id", "subject", "status", "assignee"]
)
```

For an automation that updates work packages, add a narrow write allowlist and
enable only `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`. Admin, personal-data, and
extended metadata tools can remain disabled. Enable extended metadata only
while exploring uncommon reference data, then disable it again if its tools
are not part of the normal workflow.

Tool enablement reduces the fixed catalog cost; `select` reduces the variable
response cost. They address different parts of the context budget and work
best together.

### Server instructions are sent once, not per tool

The server-level CE usage notes (`CE_INSTRUCTIONS` in `server.py`, surfaced via
the spec-standard MCP `initialize.instructions` field) are carried exactly once
— `tools/measure-context.py` verifies no registered tool's own `description`
duplicates them (a regression test,
`test_ce_instructions_are_not_duplicated_into_any_tool_description` in
`tests/test_server.py`, pins this). If a client duplicated them into every tool
description instead, the worst-case `tools/list` payload above would balloon
roughly 4x. This has been observed happening in practice with a real MCP client
during tool discovery — attributed to the client's own MCP-to-function-schema
translation (many function-calling APIs have no separate slot for server-wide
notes), not to this server or to MCPServer's `Tool.description` construction
(built solely from each function's own docstring). No local workaround was added
— copying instructions into every tool description here would just make the
non-duplicating case duplicate too.

## Reproducing these numbers

```bash
uv sync --extra measure   # installs tiktoken for real token counts
python tools/measure-context.py
```

The tool-catalog part needs no live instance. The response-size table and the
null-vs-absent cost section both need a local Docker test instance:

```bash
docker/test/up.sh 178
```

then point the script at it as described in the script's own docstring
(`OPENPROJECT_BASE_URL`, `OPENPROJECT_API_TOKEN`, `OPENPROJECT_TEST_PROJECT`
pointed at the seeded test instance).

## See also

- [Documentation hub](README.md) — full documentation index
- [Configuration](configuration.md) — the tool-exposure flags and other
  context-budget variables
- [Development](../CONTRIBUTING.md) — running the Docker test instances
