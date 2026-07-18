# Work Package Filters

<p align="center">
  <img src="../img/work-package-filters.jpg" alt="Many work package records passing through layered filters into a precise result set." width="960">
</p>

Verified against OpenProject CE source code (versions 16.0–17.6).

This document describes all work package filter parameters available in `list_work_packages` and `search_work_packages` tools, their official API filter keys, supported operators, and implementation details.

## Filter Reference Table

| Parameter | Filter Key | Filter Type | Operators Used | All Available Operators | Notes |
|-----------|------------|-------------|----------------|------------------------|-------|
| assignee | assigned_to_id | :list_optional | = | =, !, *, !* | Can filter by user ID or "me" |
| assignee_me | assigned_to_id | :list_optional | = | =, !, *, !* | Boolean shorthand for current user |
| status | status_id | :list | = | =, ! | Filter by status ID |
| open_only | status_id | :list (custom) | o | o, c, *, =, ! | Boolean for open statuses only (StatusFilter adds o/c/* operators) |
| priority | priority_id | :list | = | =, ! | Filter by priority ID |
| type | type_id | :list | = | =, ! | Filter by work package type ID |
| version | version_id | :list_optional | = | =, !, *, !* | Filter by version ID |
| version_status | version_id | :list_optional (custom) | o, c, l | o, c, l, =, !, *, !* | o=open, c=closed, l=locked (VersionFilter adds o/c/l operators) |
| project | project_id | :list | = | =, ! | Filter by project ID |
| query | subject_or_id | :text | ** | ~, !~ | Free text search (search_work_packages only) |
| created_on | created_at | :datetime_past | =d | >t-, <t-, t-, t, w, =d, <>d | Single date exact match |
| created_between | created_at | :datetime_past | <>d | >t-, <t-, t-, t, w, =d, <>d | Date range |
| updated_on | updated_at | :datetime_past | =d | >t-, <t-, t-, t, w, =d, <>d | Single date exact match |
| updated_between | updated_at | :datetime_past | <>d | >t-, <t-, t-, t, w, =d, <>d | Date range |
| due_on | due_date | :date | =d | <t+, >t+, t+, t, w, >t-, <t-, t-, =d, <>d, !* | Single date exact match |
| due_between | due_date | :date | <>d | <t+, >t+, t+, t, w, >t-, <t-, t-, =d, <>d, !* | Date range |

## Filter Type Strategies

### :list

**Supported operators:** `=` (equals), `!` (not equals)

- **Used for:** status, priority, type, project
- **Behavior:** Values required, no "none" option
- **Source:** OpenProject CE 17.6 `app/models/queries/filters/strategies/list.rb`

### :list_optional

**Supported operators:** `=` (equals), `!` (not equals), `*` (any), `!*` (none)

- **Used for:** assigned_to, version
- **Behavior:** Supports "exists" and "not exists" queries
- **Source:** OpenProject CE 17.6 `app/models/queries/filters/strategies/list_optional.rb`

### :date

**Supported operators:** `<t+`, `>t+`, `t+`, `t`, `w`, `>t-`, `<t-`, `t-`, `=d`, `<>d`, `!*`

- **Used for:** due_date
- **Behavior:** Full date and relative operators; can check for "no date set" with `!*`
- **Source:** OpenProject CE 17.6 `app/models/queries/filters/strategies/date.rb`

### :datetime_past

**Supported operators:** `>t-`, `<t-`, `t-`, `t`, `w`, `=d`, `<>d`

- **Used for:** created_at, updated_at
- **Behavior:** Past-focused (no future operators); no "none" option (these fields always have values)
- **Source:** OpenProject CE 17.6 `app/models/queries/filters/strategies/date_time_past.rb`

### :text

**Supported operators:** `~` (contains), `!~` (not contains)

- **Used for:** subject_or_id (in search)
- **Behavior:** Pattern matching only
- **Source:** OpenProject CE 17.6 `app/models/queries/filters/strategies/text.rb`

## Filter-Specific Custom Operators

Some filters extend their base strategy with custom operators via `available_operators` and `operator_strategy` methods:

### StatusFilter (status_id)

- **Base strategy:** `:list` (=, !)
- **Custom operators:** `o` (OpenWorkPackages), `c` (ClosedWorkPackages), `*` (All)
- **Implementation:** Custom `operator_strategy` method
- **Source:** OpenProject CE 17.6 `app/models/queries/work_packages/filter/status_filter.rb`

### VersionFilter (version_id)

- **Base strategy:** `:list_optional` (=, !, *, !*)
- **Custom operators:** `o` (OpenStatus), `c` (ClosedStatus), `l` (LockedStatus)
- **Implementation:** Custom `operator_strategy` method
- **Source:** OpenProject CE 17.6 `app/models/queries/work_packages/filter/version_filter.rb`

## Operator Reference

| Operator | Name | Description | Example |
|----------|------|-------------|---------|
| = | Equals | Exact match | status_id = 1 |
| ! | Not equals | Exclude value | priority_id ! 5 |
| * | Any | Has any value | version_id * |
| !* | None | Has no value | due_date !* |
| ~ | Contains | Text contains | subject ~ "bug" |
| !~ | Not contains | Text doesn't contain | subject !~ "feature" |
| =d | On date | Exact date match | created_at =d 2026-01-15 |
| <>d | Between dates | Date range | due_date <>d ["2026-01-01", "2026-01-31"] |
| t | Today | Relative to today | created_at t |
| w | This week | Current week | updated_at w |
| >t- | More than ago | More than N days ago | created_at >t- 7 |
| <t- | Less than ago | Less than N days ago | updated_at <t- 3 |
| t- | Days ago | Exactly N days ago | created_at t- 1 |
| <t+ | In less than | In next N days | due_date <t+ 7 |
| >t+ | In more than | After next N days | due_date >t+ 14 |
| t+ | In | In exactly N days | due_date t+ 3 |
| o | Open | Open status/version | status_id o |
| c | Closed | Closed version | version_id c |
| l | Locked | Locked version | version_id l |
| ** | Everywhere | Search everywhere | subject_or_id ** "OPM-123" |

## Implementation Notes

### Official Filter Keys

This implementation uses **official filter keys** as defined in OpenProject's source filter files (`def self.key`). Examples:

- `type_id` for type filtering
- `version_id` for version filtering
- `assigned_to_id` for assignee filtering

These keys correspond to the filter model definitions in OpenProject CE and ensure consistent, future-proof API usage.

**Source:** OpenProject CE source code `app/models/queries/work_packages/filter/*_filter.rb` (each defines `def self.key`)

### Date Format Requirements

- **Date filters** (`due_date`): Accept `YYYY-MM-DD` format
- **DateTime filters** (`created_at`, `updated_at`): Accept `YYYY-MM-DD` format (converted to DateTime by API)
- **Date ranges:** Pass as array `["start_date", "end_date"]` with start ≤ end validation

### Date Filter Constraints

Date filter parameters are mutually exclusive per field:
- Use either `created_on` or `created_between` (single date vs. range)
- Use either `updated_on` or `updated_between` (single date vs. range)
- Use either `due_on` or `due_between` (single date vs. range)

## Source Verification

All filter keys and operators verified against OpenProject CE 17.6 source code:
- **Filter definitions:** `app/models/queries/work_packages/filter/*.rb`
- **Strategy definitions:** `app/models/queries/filters/strategies/*.rb`
- **Last verified:** 2026-07-17 (unchanged between 17.5 and 17.6, confirmed byte-identical in `.op-sources`)
- **Test coverage:** payload-shape contract tests in `tests/unit/`

## See Also

- [Documentation hub](README.md) — full documentation index
- [tools.md](tools.md) - MCP tool documentation
- [OpenProject API v3 documentation](https://www.openproject.org/docs/api/introduction/)
