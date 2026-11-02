# Field hiding

<p align="center">
  <img src="../img/field-hiding.jpg" alt="Project records passing through a privacy shield that reveals only permitted fields." width="960">  <!-- markdownlint-disable-line MD013 -->
</p>

Two env-var forms let you omit specific fields from MCP responses and reject
attempts to write them, without touching the OpenProject instance itself:

- `OPENPROJECT_HIDE_<ENTITY>_FIELDS` — comma-separated field names to omit from
  reads and reject on writes for a given entity; `*` wildcards supported (e.g.
  `OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS=custom_field_*,budget`).
- `OPENPROJECT_HIDE_CUSTOM_FIELDS` — custom field names or keys to omit; `*`
  wildcards supported.

Both are plain comma-separated lists. Field names and patterns are normalized
case-insensitively before glob matching; `-`, `_`, and spaces are treated
consistently. There is no JSON or `entity:field` syntax to quote or escape.

A pattern matches every field it covers: `OPENPROJECT_HIDE_ACTIVITY_FIELDS=details*`
hides `details`, `details_truncated` and `details_omitted`. Any hide setting for
work package fields or custom fields also makes `get_work_package_activities` leave
out the change details, because OpenProject renders every changed value into them,
and hiding fields of work packages, projects, versions, documents, meetings, posts,
users, groups, principals or views makes `render_text` refuse, because its macros render their names.

A hidden work package field is also closed as a query. `list_work_packages` and
`search_work_packages` refuse a filter, a `sort_by` column or a `group_by` column that
orders or labels by a hidden field (`version` and `target_versions` close together, and
`assigned_to` and `assignee` are one field), `list_my_open_work_packages` is refused while
`assignee` or `status` is hidden, and the aggregates of `include_sums` leave out the sums of
`estimated_time`, `remaining_time`, `percentage_done` and of a hidden custom field. Without
this, the values would show up one query at a time.

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
  always the raw key (`custom_fields` never exposes friendly names), so a hide
  pattern written as a friendly name has no effect on what is hidden from reads,
  even though the identical pattern successfully blocks a write using that same
  friendly name.

Hiding a `customField<N>` entry also hides its matching `customComment<N>` entry
in `custom_comments` (the comment logically belongs to the same field) — there
is no separate pattern match against the comment key itself. In practice
`custom_comments` is always empty for work packages on stock OpenProject CE:
only Projects opt into per-custom-field comments, work packages do not (verified
against `acts_as_customizable`'s per-model `comments:` option) — the field
exists for forward compatibility only.

To hide a custom field from both reads and writes reliably, use its raw key
(e.g. `OPENPROJECT_HIDE_CUSTOM_FIELDS=customField12`) rather than its friendly
name.

## Work package `version`/`target_versions`: a coupled field pair

`version` and `target_versions` read from and write to the same underlying
OpenProject data (`version` is a derived single-value projection of
`target_versions` — see [Tool reference](tools.md) for the full semantics).
Hiding either one via `OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS` hides both:
listing only `version` (or only `target_versions`) in the pattern still
removes both fields from every response and rejects writes to either — the
other field would otherwise trivially leak the "hidden" one back out under a
different name.

## Work package `display_id`: the bare-number guard

A write that names a work package by a bare number is refused unless
`expect_display_id` (or, for a parent, `expect_parent_display_id`) names the
ticket (see [Tool reference](tools.md)). While
`display_id` is hidden by `OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS`, the server
cannot show or compare the display id, so the guard is off and
the expectation is refused with an error naming the hiding setting. The
refusal messages leave out any other hidden field (`project`, `subject`) as well.

Supported entities for `OPENPROJECT_HIDE_<ENTITY>_FIELDS`: `project`,
`membership`, `role`, `principal`, `user`, `group`, `project_access`,
`project_admin_context`, `project_configuration`, `action`, `capability`,
`job_status`, `project_phase_definition`, `project_phase`, `view`,
`query_filter`, `query_column`, `query_operator`, `query_sort_by`,
`query_filter_instance_schema`, `document`, `news`, `wiki_page`, `post`,
`category`, `budget`, `revision`, `attachment`, `time_entry_activity`, `time_entry`, `cost_entry`,
`cost_type`, `work_package_costs_by_type_element`, `github_pull_request`,
`gitlab_issue`, `gitlab_merge_request`, `work_package`, `relation`, `activity`,
`reminder`, `version`, `sprint`, `backlog_bucket`, `board`, `grid`,
`current_user`, `instance_configuration`, `status`, `priority`, `type`,
`watcher`, `notification`, `file_link`, `emoji_reaction`, `wiki_page_link`,
`user_preferences`, `rendered_text`, `help_text`, `working_day`,
`non_working_day`, `custom_option`, `user_non_working_time`,
`user_working_hours`, `meeting`, `meeting_agenda_item`, `meeting_outcome`,
`meeting_section`, `recurring_meeting`, `storage`, `project_storage`.

See [Configuration](configuration.md) for the two variables' required/default
values.

## See also

- [Documentation hub](README.md) — full documentation index
- [Tool reference](tools.md) — which response fields exist per entity before
  hiding
- [Configuration](configuration.md) — the full environment variable reference
