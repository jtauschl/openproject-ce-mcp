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

Measured against the same three representative work packages (token ≈
bytes/4), reproducible with [`tools/measure-context.py`](https://github.com/jtauschl/openproject-ce-mcp/blob/main/tools/measure-context.py)
against a local Docker test instance. Covers list, single-read, search, a
confirmed write, and batch operations — not just one call shape — each
compared against the equivalent raw OpenProject REST API v3 (HAL) call(s):

| Call | Raw API tokens | MCP tokens | vs. raw |
|---|---:|---:|---:|
| `list_work_packages` (3 rows) | ~7,950 | ~1,080 | **−86%** |
| `list_work_packages` with `select` (5 fields) | ~7,950 | ~120 | **−98%** |
| `get_work_package` (single read) | ~2,670 | ~430 | **−84%** |
| `search_work_packages` | ~6,520 | ~745 | **−89%** |
| `update_work_package` (confirmed write) | ~2,670 | ~490 | **−82%** |
| `bulk_create_work_packages` (×5, vs. 5 raw POSTs) | ~11,585 | ~1,935 | **−83%** |
| `bulk_update_work_packages` (×5, vs. 5 raw PATCHes) | ~11,580 | ~1,930 | **−83%** |

The savings are consistent across call shapes — this isn't a one-off number
for list responses specifically. `select` remains the largest additional,
opt-in lever on top of the baseline MCP trimming.

## Tool catalog size

The tool set itself is trimmed too, mainly by not emitting redundant output
schemas. A fresh, unconfigured install — the actual default state, before
`OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS` are set — registers
only the read tool set: 58 tools, ~18k tokens. Project-scoped write tools are
only registered once **both** allowlists are non-empty (an empty
`OPENPROJECT_WRITE_PROJECTS` alone leaves them unregistered, since a write
tool that can never pass the project-scope check would just be dead catalog
weight); once granted, and with every write scope enabled — the worst case —
the `tools/list` payload is 119 tools, ~32k tokens, down from an unoptimized
~60k-tool-count-equivalent baseline. Turning on the rarely-used `extended`
metadata tools (`OPENPROJECT_ENABLE_EXTENDED_READ=true`, see
[Configuration](configuration.md#tool-groups)) on top of that adds 12 more
tools, ~34k tokens. Confirmed writes also drop the echoed request `payload`.

## Reproducing these numbers

```bash
python tools/measure-context.py
```

The tool-catalog part needs no live instance. The response-size table needs a
local Docker test instance:

```bash
docker/test/up.sh 17
```

then point the script at it as described in the script's own docstring
(`OPENPROJECT_BASE_URL`, `OPENPROJECT_API_TOKEN`, `OPENPROJECT_TEST_PROJECT`
pointed at the seeded test instance).

## See also

- [Documentation hub](README.md) — full documentation index
- [Configuration](configuration.md) — the tool-exposure flags and other context-budget variables
- [Development](development.md) — running the Docker test instances
