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
| search | subject_or_id | :text | ** | ~, !~ | Free text search (search_work_packages only); matches only subject and numeric ID, never version/category/description or other linked fields — use the `version` filter above for version-based matches |
| created_on | created_at | :datetime_past | =d | >t-, <t-, t-, t, w, =d, <>d | Single date exact match |
| created_between | created_at | :datetime_past | <>d | >t-, <t-, t-, t, w, =d, <>d | Date range |
| updated_on | updated_at | :datetime_past | =d | >t-, <t-, t-, t, w, =d, <>d | Single date exact match |
| updated_between | updated_at | :datetime_past | <>d | >t-, <t-, t-, t, w, =d, <>d | Date range |
| due_on | due_date | :date | =d | <t+, >t+, t+, t, w, >t-, <t-, t-, =d, <>d, !* | Single date exact match |
| due_between | due_date | :date | <>d | <t+, >t+, t+, t, w, >t-, <t-, t-, =d, <>d, !* | Date range |
| custom_field_filters | cf_\<N\> (per entry) | varies by field format | varies by field format | varies by field format | Filters by custom field value(s) — a dict of many, not a single named parameter; see "Custom-Field Filters" below |

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
| >= | Greater or equal | Numeric/date lower bound | cf_5 >= 3.14 |
| <= | Less or equal | Numeric/date upper bound | cf_5 <= 100 |
| &= | Contains all | List/user/version CF has ALL given values | cf_8 &= [1, 2] |

The last three rows are custom-field-only (see "Custom-Field Filters" above) — no built-in filter in the
table at the top of this document uses them.

## Custom-Field Filters

Added in OPM-109, as a distinct follow-up to OPM-94 (custom-field read-value exposure) — see OPM-90's
design audit for why filtering and value exposure are kept separate.

Verified against OpenProject CE source code (`op-sources/full-17.6`):
`app/models/queries/filters/shared/custom_field_filter.rb` (dispatch), `app/models/queries/filters/shared/custom_fields/{base,list_optional,user,bool}.rb` (per-format strategy selection), and
`app/models/queries/filters/strategies/{string,text,date,cf_integer,cf_float,cf_list_optional,boolean_list}.rb`
(operator sets).

Custom fields are filtered via the `custom_field_filters` parameter on `list_work_packages`/`search_work_packages`,
a dict keyed by `cf_<N>` or `customField<N>` (both forms accepted transparently, always normalized to `cf_<N>`
on the wire):

```python
custom_field_filters={
    "cf_12": {"operator": "=", "values": ["42"]},
    "customField7": {"operator": "~", "values": ["Acme"]},
}
```

**`cf_<N>` vs `customField<N>` — a real divergence, not a typo.** `cf_<N>` is `CustomField#column_name`
(`custom_field.rb:328`), the actual OpenProject **filter key**. `customField<N>` is
`CustomField#attribute_name(:camel_case)`, the **JSON/PATCH key** used for reading/writing a field's value
(the `custom_fields` dict on `list_work_packages`/`get_work_package` results, and the `custom_fields`
write-path parameter on `create_work_package`/`update_work_package`). These are two different strings
identifying the same field — using `customField<N>` as a filter key would silently fail or be
misinterpreted, which is exactly why OPM-109 exists as a distinct piece of work from OPM-94.

### Custom-Field Format → Filter Strategy Table

Ten CE-realistic custom-field formats exist; each dispatches to its own filter strategy
(`custom_field_filter.rb`'s `subfilter_class`, then `custom_fields/base.rb`'s `type` case):

| Format | Filter Strategy | Operators | Notes |
|--------|------------------|-----------|-------|
| string | `:string` (`Strategies::String`) | `=`, `~`, `!`, `!~` | Free string match/contains |
| text | `:text` (`Strategies::Text`) | `~`, `!~` | Contains-only, no exact `=` |
| link | `:string` (`Strategies::String`) | `=`, `~`, `!`, `!~` | No dedicated "link" strategy exists server-side (absent from every `case`/`when` in the dispatch chain) — falls through to plain string, identical to the string row above |
| int | `CfInteger` | `=`, `!`, `>=`, `<=`, `!*`, `*` | `base.rb` explicitly overrides `:integer` → `CfInteger`; values must parse as `Integer` |
| float | `CfFloat` | `=`, `!`, `>=`, `<=`, `!*`, `*` | Same operator set as int, `Float`-typed values |
| date | `Strategies::Date` | `<t+`, `>t+`, `t+`, `t`, `w`, `>t-`, `<t-`, `t-`, `=d`, `<>d`, `!*` | Identical to the built-in `due_date` row above (same strategy class, unmodified) |
| bool | `BooleanList` | `=`, `!` | Values are the literal wire strings `"t"`/`"f"` (`OpenProject::Database::DB_VALUE_TRUE`/`FALSE`), not JSON `true`/`false`; only one value per filter call |
| list | `CfListOptional` | `=`, `&=`, `!`, `*`, `!*` | Differs from the built-in `:list_optional` row above: `!*`/`*` mean none/any (same symbols, CF-specific semantics), `!` is `NotEqualsAll`, and `&=` (`EqualsAll`, "contains all of") has no built-in equivalent. Values are `CustomOption` ids |
| user | `CfListOptional` (via `CustomFields::User`, inherits `ListOptional` unchanged) | `=`, `&=`, `!`, `*`, `!*` | Same operators as list; also accepts the literal value `"me"`, resolved server-side against the current user (and their group memberships) |
| version | `CfListOptional` | `=`, `&=`, `!`, `*`, `!*` | Same as list; values are `Version` ids instead of `CustomOption` ids |

**Not supported (Enterprise-only, rejected explicitly):** `hierarchy`, `weighted_item_list` — both are
`enterprise_feature:`-tagged in `config/initializers/custom_field_format.rb`, so a caller cannot legitimately
have one configured on a CE instance. A third format, `calculated_value`, is likewise Enterprise-gated
**and** registered `only: %w(Project)` — it cannot exist as a work-package custom field's format at all, so
no `cf_<N>` filter on `list_work_packages`/`search_work_packages` could ever resolve to it (nothing to
reject). Note this differs slightly by OpenProject version even where it would matter: 17.6 folds
`calculated_value` into the plain `:float`/`CfFloat` strategy, while 17.7 introduces a dedicated
`CfCalculatedValue` strategy (`=`, `!`, `>=`, `<=`, `=t`, `=f`, `!*`, `*`) — moot for this MCP either way,
since the field can never attach to a work package.

### Global (no-project) filtering constraint

`Queries::WorkPackages::Filter::CustomFieldContext.custom_fields(context)` excludes `user`- and
`version`-format custom fields entirely from the global, no-project filter set
(`.where.not(field_format: %w(user version))`) — only project-scoped queries consider these two formats
filterable. A `custom_field_filters` entry referencing a `user`- or `version`-format field without also
passing `project` will fail server-side with an unhelpful "filter not available" error; always pass
`project` when filtering on one of these two formats.

### Operator validation: local syntax check only, no per-call schema probe

`list_work_packages`/`search_work_packages` validate `custom_field_filters` locally only for **syntax**:
the `cf_<N>`/`customField<N>` key shape, and that the operator is one of the symbols legal for *at least
one* CE custom-field format (the union across the table above). They do **not** probe a live schema to
confirm the operator is legal for a *specific* field's actual format — OpenProject's own custom-field
`available_filters`/query-filter-schema machinery (`GET /api/v3/queries/filter_instance_schemas/cf_<N>`) is
the authoritative source for that, and querying it per filter would add a network round trip to every
`list_work_packages`/`search_work_packages` call that uses `custom_field_filters`, at exactly the same
"cost per resolution" tradeoff the write path's schema-probe-based name resolution already has (see
`_get_write_schema` in `work_package_service.py`) — except unlike the write path, list/search calls have no
single project+type context guaranteeing one probe suffices. An operator that is syntactically valid but
illegal for a specific field's format is rejected by OpenProject itself with a clean `400 InvalidQuery`
response, mapped by this MCP to a `ValueError`/`InvalidInputError` carrying OpenProject's own message — not
a raw/opaque failure, satisfying OPM-109's "fail clearly" requirement without the added round trip. This is
a deliberate scope decision for this ticket; a future ticket could add real client-side format-aware
validation via the query-filter-schema endpoint above.

### Hidden custom fields

A custom field matched by `OPENPROJECT_HIDE_CUSTOM_FIELDS` cannot be used in `custom_field_filters` — the
call is rejected with a clear error before any network request, not silently dropped from the filter list
(unlike the read-side value-masking behavior, which silently omits rather than rejects — a deliberately
different UX for filtering, per the ticket's explicit requirement). Both canonical spellings of the field's
key (`cf_<N>` and `customField<N>`) are checked against configured hide patterns, since a pattern might have
been written using either form.

### Friendly names not supported

Only raw `cf_<N>`/`customField<N>` keys are accepted — friendly-name resolution (as supported on the write
path's `custom_fields` parameter, resolved against a project+type schema probe) is deliberately out of scope
for this ticket. `list_work_packages`/`search_work_packages` have no reliable single project+type context to
resolve a name against safely: `project` is optional, two projects can define same-named-but-different
custom fields, and a friendly name might not even be enabled on every project in scope. Learn a field's
`cf_<N>` id from any prior `get_work_package`/`list_work_packages` call's `custom_fields` dict keys (they are
`customField<N>`-keyed per OPM-94 — strip the `customField` prefix and use `cf_<N>`).

### Custom-field sort/group

Custom fields are also sortable/groupable via their `cf_<N>` key on `sort_by`/`group_by` — this predates
OPM-109 (landed in commit `740a250`, 2026-07-20, live-verified against a real OpenProject instance) and
required no change for this ticket. See `_CUSTOM_FIELD_PATTERN` in `tools.py` and the `sort_by`/`group_by`
parameter docs on `list_work_packages`. Note this pass-through is intentionally permissive at the MCP layer
(any `cf_\d+`-shaped string is accepted locally): OpenProject itself builds the real sort/group SQL from each
field's select-instance definition, and not every format is guaranteed sortable/groupable there (e.g. `text`
CFs are excluded from select-instance ordering server-side) — an unsupported combination surfaces as
OpenProject's own error rather than being pre-validated client-side, the same tradeoff as the operator
validation above.

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
- **Last verified:** 2026-07-17 (unchanged between 17.5 and 17.6, confirmed byte-identical against OpenProject's own source)
- **Test coverage:** payload-shape contract tests in `tests/unit/`

Custom-field filtering (OPM-109) additionally verified against:
- **Filter dispatch:** `app/models/queries/filters/shared/custom_field_filter.rb`,
  `app/models/queries/filters/shared/custom_fields/{base,list_optional,user,bool}.rb`
- **Strategies:** `app/models/queries/filters/strategies/{string,text,date,cf_integer,cf_float,
  cf_list_optional,boolean_list}.rb`
- **Enterprise gating / format registration:** `config/initializers/custom_field_format.rb`
- **Global-scope constraint:** `app/models/queries/work_packages/filter/custom_field_context.rb`
- **17.7 `calculated_value` divergence:** `op-sources/17.7/app/models/queries/filters/shared/custom_fields/base.rb`
  and `strategies/cf_calculated_value.rb`
- **Last verified:** 2026-08-13 against `op-sources/full-17.6` and `op-sources/17.7`
- **Test coverage:** `tests/unit/test_tool_validation.py` (key/shape validation),
  `tests/unit/test_app_work_package_service.py` (per-format filter-shape + hide-field rejection),
  `tests/unit/test_work_package_tools.py` and `tests/unit/test_work_package_reads.py` (tool → client →
  httpx wire-payload forwarding), `tests/integration/test_work_packages.py` (live round trip against the
  OPM-94 seeded custom field)

## See Also

- [Documentation hub](README.md) — full documentation index
- [tools.md](tools.md) - MCP tool documentation
- [OpenProject API v3 documentation](https://www.openproject.org/docs/api/introduction/)
