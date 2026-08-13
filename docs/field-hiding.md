# Field hiding

<p align="center">
  <img src="../img/field-hiding.jpg" alt="Project records passing through a privacy shield that reveals only permitted fields." width="960">
</p>

Two env-var forms let you omit specific fields from MCP responses and reject
attempts to write them, without touching the OpenProject instance itself:

- `OPENPROJECT_HIDE_<ENTITY>_FIELDS` — comma-separated field names to omit from
  reads and reject on writes for a given entity; `*` wildcards supported
  (e.g. `OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS=custom_field_*,budget`).
- `OPENPROJECT_HIDE_CUSTOM_FIELDS` — custom field names or keys to omit; `*`
  wildcards supported.

Both are plain comma-separated lists. Field names and patterns are normalized
case-insensitively before glob matching; `-`, `_`, and spaces are treated
consistently. There is no JSON or `entity:field` syntax to quote or escape.

## Custom fields: a read/write asymmetry

`OPENPROJECT_HIDE_CUSTOM_FIELDS` behaves differently on reads than on writes:

- **On writes** (`create_work_package`/`update_work_package`'s `custom_fields`
  input), a pattern matches EITHER the raw key (e.g. `customField12`) OR the
  custom field's resolved friendly name (e.g. `Story points`) — whichever the
  caller happened to supply is checked against the pattern.
- **On reads** (`list_work_packages`/`search_work_packages`/`get_work_package`/
  `get_work_packages`/`list_my_open_work_packages`'s `custom_fields`/
  `custom_comments` response fields), a pattern matches ONLY the raw
  `customField<N>` key/wildcard — never a friendly name. Response keys are
  always the raw key (`custom_fields` never exposes friendly names), so a
  hide pattern written as a friendly name has no effect on what is hidden
  from reads, even though the identical pattern successfully blocks a write
  using that same friendly name.

Hiding a `customField<N>` entry also hides its matching `customComment<N>`
entry in `custom_comments` (the comment logically belongs to the same
field) — there is no separate pattern match against the comment key itself.
In practice `custom_comments` is always empty for work packages on stock
OpenProject CE: only Projects opt into per-custom-field comments, work
packages do not (verified against `acts_as_customizable`'s per-model
`comments:` option) — the field exists for forward compatibility only.

To hide a custom field from both reads and writes reliably, use its raw key
(e.g. `OPENPROJECT_HIDE_CUSTOM_FIELDS=customField12`) rather than its
friendly name.

Supported entities for `OPENPROJECT_HIDE_<ENTITY>_FIELDS`: `project`,
`membership`, `role`, `principal`, `user`, `group`, `project_access`,
`project_admin_context`, `project_configuration`, `action`, `capability`,
`job_status`, `project_phase_definition`, `project_phase`, `view`,
`query_filter`, `query_column`, `query_operator`, `query_sort_by`,
`query_filter_instance_schema`, `document`, `news`, `wiki_page`, `category`,
`attachment`, `time_entry_activity`, `time_entry`, `work_package`,
`relation`, `activity`, `reminder`, `version`, `sprint`, `board`, `grid`,
`current_user`, `instance_configuration`, `status`, `priority`, `type`,
`watcher`, `notification`, `file_link`, `emoji_reaction`, `wiki_page_link`,
`user_preferences`, `rendered_text`, `help_text`, `working_day`,
`non_working_day`, `custom_option`, `user_non_working_time`,
`user_working_hours`.

See [Configuration](configuration.md) for the two variables' required/default
values.

## See also

- [Documentation hub](README.md) — full documentation index
- [Tool reference](tools.md) — which response fields exist per entity before hiding
- [Configuration](configuration.md) — the full environment variable reference
