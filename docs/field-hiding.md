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
work package fields or custom fields also makes `list_work_package_activities` leave
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

A hidden custom field column is closed the same way: with `custom_fields` named in the entity's
hide setting, or the field matched by `OPENPROJECT_HIDE_CUSTOM_FIELDS`, a `cf_<N>` entry in
`sort_by`, `group_by` or `custom_field_filters` is refused on work packages and projects. Naming
`custom_fields` in `OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS` or `OPENPROJECT_HIDE_PROJECT_FIELDS` also
refuses writes to `custom_fields` on that entity.

## Project attributes

Project custom fields (project attributes) follow the same rules as work package custom fields:

- `OPENPROJECT_HIDE_PROJECT_FIELDS` naming `custom_fields` or `custom_comments` hides the whole dict.
- `OPENPROJECT_HIDE_CUSTOM_FIELDS` removes single entries by the raw `customField<N>` key, together with the
  `customComment<N>` entry: a comment is judged by its field's key, so it goes even when the value is not in
  the result.
- `get_project_admin_context` leaves out the definitions of hidden attributes.
- The preview and result `payload` of every write that shows a form payload (projects, work packages,
  versions, users, time entries and the rest) leave out hidden custom field values the form echoes back, and
  the static fields too (see "Write previews" below). The text of a rejected write follows the rule in "Server
  error texts" below.
- Like every read-side hide, reads, previews, filters and sorts follow the raw key: a pattern written as a
  friendly name refuses writes by that name but does not redact there (see below). The text of a rejected
  work package write is the exception: it also judges a custom field by its name, because the form hands the
  schema over.
- A version-valued attribute that points to a version outside `OPENPROJECT_READ_PROJECTS` reads as `null`,
  and `update_project` refuses a write that would replace such a hidden value.

## Custom fields: a read/write asymmetry

`OPENPROJECT_HIDE_CUSTOM_FIELDS` behaves differently on reads than on writes:

- **On writes** (`custom_fields` input of the work package and project write tools),
  a pattern matches EITHER the raw key (e.g. `customField12`) OR the
  custom field's resolved friendly name (e.g. `Story points`) — whichever the
  caller happened to supply is checked against the pattern.
- **On reads** (the `custom_fields`/`custom_comments` response fields of the work package
  and project read tools), a pattern matches ONLY the raw
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
`expect_display_id` (or, for a parent, `expect_parent_display_id`; for the related
work package of a relation, `expect_related_display_id`) names the
ticket (see [Tool reference](tools.md)). While
`display_id` is hidden by `OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS`, the server
cannot show or compare the display id, so the guard is off and
the expectation is refused with an error naming the hiding setting. The
refusal messages leave out any other hidden field (`project`, `subject`) as well.

## User `status`/`locked`: a coupled field pair

`locked` is derived from `status` (`status` is the value `locked` for a locked account), so the two names are one
fact. Hiding either one via `OPENPROJECT_HIDE_USER_FIELDS` hides both in every user result, and `create_user` (which
writes `status`) and `set_user_locked` refuse while either is hidden.

## Write previews: the `payload` of a result

The server's form answer echoes every attribute the contract lets the caller write, whether the caller sent it or
not, so a preview of `update_user(firstname=...)` would show the user's `status`, `login` and `email`. The `payload`
of a write result (preview, rejected and invalid; a confirmed result carries none) therefore leaves out every key
that carries a field `OPENPROJECT_HIDE_<ENTITY>_FIELDS` hides, under its wire name (`startDate` for `start_date`,
`_links.parent` for `parent_id` and `parent_name`, `firstName` and `lastName` for `firstname`, `lastname` and
`name`). The coupled pairs hide together here as everywhere (`status` and `locked`, `version` and
`target_versions`, `user` and `user_id`). The body sent to the server when you confirm is not changed.

- **An unknown key is hidden once the entity has any hide setting.** The server renders keys the client does not
  classify (module patches, newer versions); such a key is shown only while nothing of its entity is hidden. A key
  you passed in yourself and the client does not classify therefore disappears from the preview of an operator who
  hides something. Custom field keys follow their own settings (above). The same rule empties most of a preview
  whose entity has many keys the client does not classify (a grid or a board): the keys of the table stay, the rest
  goes as soon as any field of the entity is hidden.
- **The preview of a delete** reads its values from the record, which the hide setting stamps but does not
  change; it leaves out the values of the hidden fields too. When you hide `name` (or `title`, `identifier`), the
  preview of a delete names its target by its id only (see "Write results" below): hiding wins over "a preview
  names its target". The record in `result` is stamped like any read, so a hidden field is absent there as well.

## Server error texts

OpenProject answers a rejected write with errors that carry the API attribute they are about
(`status`, `effectiveDate`, `customField5`) and a message in the language of the token's account, which names
that attribute or quotes a value (`Status is invalid`). Only the attribute can be judged, so the server's text is
handled by it, wherever it reaches a caller: the `validation_errors` of a form, the text of a rejected commit or
delete, the `error` of a failed bulk item, the text of a rejected read.

- **Nothing changes while no hide setting is active.** The texts are exactly what the server sent. (Our own
  refusal to replace a version of a project names the project by the reference you passed, hide or not.)
- **While any hide setting is active** (an entity's `OPENPROJECT_HIDE_<ENTITY>_FIELDS` or
  `OPENPROJECT_HIDE_CUSTOM_FIELDS`), the server's text is not passed on. A rejected write of an entity renders
  each error again by that entity: an error whose attribute names a hidden field is replaced by `A field hidden
  by the hide settings is invalid.`, the others keep their message, so the caller still learns the visible reason.
  The attribute (an API name such as `status` or `customField5`) stays visible in the key of `validation_errors`, which
  keeps its error classes, and in the header of a 422 text (`Code (attribute): ...`).
- **What an error names is judged by the attribute.** A known attribute is hidden when the field it is about is
  hidden (a start or finish date error follows `start_date` and `due_date` both: its message quotes the soonest
  start that the predecessors allow, their finish or their start). A `base` error is hidden when a field it can describe is
  hidden (for a work package: status, versions, parent, project, type). A custom field key is judged by the
  custom field settings, by its name too in a work package write (the form's schema names it); where no name is
  known (other entities, a delete) a name pattern hides the entry, so it never leaves a title behind. A pattern is
  a name pattern unless it is exactly a raw key without wildcards (`customField5`); `cf_5` is a name pattern
  here, unlike in sorts and filters; a `customComment<N>` pattern counts as a raw key and hides no error, as on reads.
- **An error the policy cannot attribute is hidden while any hide setting is active:** an attribute no table
  knows, and an error without attribute (a malformed request, a filter error). The cost: with only `user.email`
  hidden, the text of a rejected filter loses its reason, while an error about a known attribute keeps its own.
- **A stale `lockVersion`** (`UpdateConflict`) is a constant sentence of the server and stays readable.
- **A 403 drops its detail** while a hide is active unless the text names an attribute the settings leave visible: a
  real 403 carries no attribute (the text of a quarantined attachment names its file), so its detail goes and the
  sentence `OpenProject denied access to this resource.` stays; a refusal for a missing permission is still said.
- **Limits.** The text of a rejected request that no service renders by an entity (the flat client, resolvers,
  the `setup` and `doctor` commands) is the generic `OpenProject rejected the request.`; so is the text of a
  service that has no entity of its own (cost, status, priority and type reads, action and capability reads,
  the GitHub and GitLab links, `render_text` and the other extended metadata reads, the project admin context). The free text of a failed copy job (`get_job_status`) is not redacted. The
  refusal to write a hidden custom field names what the caller typed, not the field's title.

## Write results: identity fields and copies of a hidden value

A write result repeats the value of a field in members beside `payload` and `result`: the identity fields
(`project`, `meeting_id`, `grid_id`, `work_package_id` ...) and the work package `target` and `related_target` of a
write that names a work package through an association (`time_entry.entity_id`, `relation.from_id` and `to_id`,
`attachment.container_id`). Each member names the field it repeats (its owner; a few members name two fields that
carry the same value, such as the id and the display id of a work package): when the settings hide that field the
member leaves the result, key and value. The owner of `project` is the field of the entity that was written
(`version.defining_project`, `membership.project_name`, `work_package.project`), not the `name` of the project;
hiding a project's name does not change another entity's result, as on reads.

- **Ids are fields.** `work_package_id`, `meeting_id` and the like leave the result when the `id` (for a work
  package reference also the `display_id`) or the named association field is hidden, in every copy: the `id`, the
  meeting, agenda item and occurrence references and the file name and size of an upload in a preview `payload` too.
  A hidden `id` leaves a delete preview without the id; the record in `result` and the message still describe it.
- **A relation names its ends by direction.** OpenProject stores `precedes` as `follows` with the ends swapped, so
  on a create hiding `from_id` or `to_id` hides every member that names an end of the relation: the ids, the work
  package `target` and `related_target` and the destination link in the `payload`; hiding a caption of an end
  (`from_subject`, `to_subject`) hides the two targets only. A delete preview names the stored ends, which are fields
  of their own, and keeps the other one.
- **The title of an attachment is its file name**; the two hide together, in every attachment result.
- **The target of a work package create is its parent**, so it hangs on `parent_id` and `parent_display_id`; the
  target of an update is the work package itself and stays.
- **The messages of a write name no value.** They say what the tool did; the storage update preview keeps a
  fixed note about Nextcloud storages, which is advice and not the record's value.
- The `target` of a time entry is a work package: hiding `entity_id` or `entity_name` removes the `target`; the
  `parent_target` of a work package or project update goes with `parent_id` (and `parent_display_id` or `parent_name`);
  hiding the work package's own fields
  works through the work package settings as on reads.
- A value that is a part of another visible field (the date inside a visible start time) stays: the fields are
  hidden one by one.

## Read results: copies of a hidden value outside the record

A read result repeats the value of a field in members beside the record, and the same rule applies: the member names
the field it repeats and leaves the result, key and value, when the settings hide that field. An id that a row
carries as its own member (`parent_id`, `from_id`) belongs to that row's entity; a member that echoes the record the
tool is about belongs to that record's entity.

- **The reference of a batch read item** (`get_work_packages`, `id`) goes when the work package `id` or `display_id`
  is hidden, also when it is the reference the caller typed. The item keeps `index`, the position of the first
  occurrence of the reference in `ids`, so the caller can still tell the items apart.
- **Echoes of the record a tool is about** go with its owner: `work_package_id` of the costs by type (a display id
  resolves to an id) with the work package `id` or `display_id`, `attachment_id` of an attachment's content and the
  `download_url` of an attachment with the attachment `id`, `project_id`, `project_name` and `project_identifier` of a
  project configuration, access summary and work package context with the project `id`, `name` and `identifier`,
  `current_user_id` and `current_user_name` of the access summary with the current user's `id` and `name`.
- **Option lists of the work package context** (`available_*` and `selected_type_*` of `get_project_work_package_context`) are the context's own fields: hiding a type's or status's `id` or `name` does not reach them; hide them with the context's own settings.
- **A URL built from the id of its own record** (`url` of an action, capability and query filter, column, operator,
  sort criterion and filter instance schema, `avatar_url` of a user) goes with that record's `id`. The perspective of
  a relation (`queried_perspective`) goes with `from_id`, `to_id` and `type`.
- **An occurrence names two entities**: `recurring_meeting_id` of an occurrence list goes with the recurring meeting
  `id` or the meeting's `recurring_meeting_id`, `start_time` of an occurrence with the `start_time` of either, and
  `meeting_id` of an occurrence with the meeting `id`.
- **The rows of `children` and `ancestors`** are the work packages (or projects) around the record: `href` follows
  the `id` and `display_id`, `title` the `subject`, `display_id` the `display_id` (a project row: `href` follows
  the project `id`, `title` the `name`). The row of the parent also follows `parent_id` and `parent_display_id`
  (project: `parent_id`, `parent_name`). A row with no
  value left is dropped; the data of the record is not edited.
- **A record the server sent without a name** is shown as `Unnamed <kind>` (`Unnamed status`, `Unnamed file link`), never
  under a text built from its id, so hiding `id` leaves nothing of the id behind. The label is display only: roles,
  time entry activities and projects are resolved by the name the server sent, a project allowlist reads that name
  too, and a `search` filter matches the text shown.
  The allowlist now reads the trimmed name in every path (a pattern written against irregular whitespace or a name
  over 255 characters matches as it does for a project the server returned in a list).
- **Not covered:** the filter values of a saved board that the server names by no title or name are shown as the
  reference it sent, which can hold the id of a hidden record.

## Help text `attribute_caption` and `caption`

`attribute_caption` is the label of the attribute and `caption` the text an administrator stored for it (17.0 and
later): two different facts, so each hides on its own through `OPENPROJECT_HIDE_HELP_TEXT_FIELDS`. A pattern that
named only `attribute_caption` hid the stored caption before 0.4.6 and now needs `caption` added.

## Context entities: options are hidden as a whole

The context entities (`project_access`, `project_admin_context`, `project_configuration`, `project_work_package_context`) hide
each listed field of their own result as a whole, including a list of options such as `available_statuses`; the rules of
the entity an option belongs to (for example `status`) are not applied to the options inside such a field.

Supported entities for `OPENPROJECT_HIDE_<ENTITY>_FIELDS`: `project`,
`membership`, `role`, `principal`, `user`, `group`, `project_access`,
`project_admin_context`, `project_configuration`, `project_work_package_context`, `action`, `capability`,
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
