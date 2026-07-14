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

Supported entities for `OPENPROJECT_HIDE_<ENTITY>_FIELDS`: `project`,
`membership`, `role`, `principal`, `user`, `group`, `project_access`,
`project_admin_context`, `project_configuration`, `action`, `capability`,
`job_status`, `project_phase_definition`, `project_phase`, `view`,
`query_filter`, `query_column`, `query_operator`, `query_sort_by`,
`query_filter_instance_schema`, `document`, `news`, `wiki_page`, `category`,
`attachment`, `time_entry_activity`, `time_entry`, `work_package`,
`relation`, `activity`, `reminder`, `version`, `sprint`, `board`,
`current_user`, `instance_configuration`, `status`, `type`, `watcher`.

See [Configuration](configuration.md) for the two variables' required/default
values.

## See also

- [Documentation hub](README.md) — full documentation index
- [Tool reference](tools.md) — which response fields exist per entity before hiding
- [Configuration](configuration.md) — the full environment variable reference
