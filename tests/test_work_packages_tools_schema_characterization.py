"""Characterization test: freezes the 15 Work Packages MCP tool schemas.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (trimmed tools register with structured_output=False and have
none, see test_trimming.py). A future relocation of any of these functions to
a different module must leave this file completely unmodified; a diff to it
would mean the move changed the public tool contract, not just its location.
"""

from __future__ import annotations

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "enable_work_package_write": True,
        "enable_project_write": True,
        "enable_membership_write": True,
        "enable_version_write": True,
        "enable_board_write": True,
        "enable_admin_write": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
        "enable_metadata_tools": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_search_work_packages_schema() -> None:
    tool = _tools(create_app(_make_settings()))["search_work_packages"]
    assert (
        tool.description
        == "Search work packages by free text, optionally scoped to a project.\n\nsearch matches only the work package subject and numeric ID (OpenProject's\nnative subject_or_id full-text filter); it does NOT match version,\ncategory, description, or other linked-resource fields. To filter by\nversion, use list_work_packages(version=..., project=...) instead.\n\nIn parallel with that text/id search, a search shaped like a work package\nreference (a numeric id or a display id like \"PROJ-42\", but not a date\nsuch as 2026-10-15) is also resolved directly the same way\nget_work_package does; other text is never looked up as an id. When that\nresolves to a work package that also\nsatisfies every other filter given here (project/status/assignee/dates/\ncustom fields/etc.), it's returned separately as exact_match; never\nfolded into results, and never counted toward total/count/pagination,\nsince a single extra item can't be paginated consistently. Absent (not\npresent in the response at all) when nothing resolves, when the\nresolved item fails a filter, or when it's already present in results\nvia the text match. select applies to exact_match the same way it\napplies to each results row.\n\nWithout project, the search runs globally across every project readable\nunder OPENPROJECT_READ_PROJECTS, not just one project; pass project\nexplicitly to scope results to it.\n\nSet status to restrict results to an exact OpenProject status name or\nnumeric ID, not a meta-value like 'open'/'closed'.\nSet open_only=true to return only open (not-closed) work packages.\nSet assignee_me=true to return only work packages assigned to the current user.\n\nassignee filters by any user (username, id, or \"me\"). assignee_me takes precedence.\n\npriority filters by priority name or numeric ID (case-insensitive).\n\nDate filters, overdue_only/due_within_days, select,\npagination (offset/limit/total), include_sums, and each result's\ncustom_fields/custom_comments (raw-key custom-field values/comments,\ncapped and hide-matched exactly as documented) all work exactly as\ndocumented on list_work_packages; see that tool's docstring for the\nfull field lists and semantics. sort_by and group_by take the same fields\nand are described by their own parameters. One difference: total is the real\nmatching count only when scope is unrestricted or an explicit project\nwas given (list_work_packages's server-side allowed-project filter for\nthe no-project+restricted-scope case does not apply here); otherwise\ntotal/groups/total_sums fall back to this page's data, same safety\nguarantee either way.\n\ncustom_field_filters filters by custom field value(s); see\nlist_work_packages's docstring for the full parameter documentation\n(identical shape and semantics on both tools).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "search": {"title": "Search", "type": "string"},
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "status": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Status",
            },
            "open_only": {"default": False, "title": "Open Only", "type": "boolean"},
            "assignee_me": {"default": False, "title": "Assignee Me", "type": "boolean"},
            "assignee": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Assignee",
            },
            "priority": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Priority",
            },
            "created_on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Created On"},
            "created_between": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Created Between",
            },
            "updated_on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Updated On"},
            "updated_between": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Updated Between",
            },
            "due_on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Due On"},
            "due_between": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Due Between",
            },
            "overdue_only": {"default": False, "title": "Overdue Only", "type": "boolean"},
            "due_within_days": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Due Within Days",
            },
            "sort_by": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": 'Sort criteria as "field:direction" or "field-direction" (e.g. ["status:desc", "priority-asc"]); the direction defaults to asc. Fields: assigned_to, assignee, author, backlog_bucket, category, created_at, done_ratio, due_date, duration, estimated_hours, estimated_time, id, observed_in_versions, percentage_done, position, priority, project, project_phase, remaining_hours, remaining_time, responsible, sprint, start_date, status, story_points, subject, target_versions, type, updated_at, version, or a custom field\'s cf_<id>. Newer columns need an OpenProject release: project_phase 16.1+, sprint 17.4+, backlog_bucket 17.6+, target_versions 17.8+, observed_in_versions 17.9+; target_versions is version under its newer name. sprint and backlog_bucket also need the Backlogs module in a project where you may view sprints.',
                "title": "Sort By",
            },
            "group_by": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "One field to group the results by: assigned_to, assignee, author, backlog_bucket, category, done_ratio, observed_in_versions, percentage_done, priority, project, project_phase, responsible, sprint, status, target_versions, type, version, or a custom field's cf_<id>. Newer columns need an OpenProject release: project_phase 16.1+, sprint 17.4+, backlog_bucket 17.6+, target_versions 17.8+, observed_in_versions 17.9+; target_versions is version under its newer name. sprint and backlog_bucket also need the Backlogs module in a project where you may view sprints.",
                "title": "Group By",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: assignee, author, category, created_at, custom_comments, custom_comments_truncated, custom_fields, custom_fields_truncated, derived_due_date, derived_estimated_time, derived_percentage_done, derived_remaining_time, derived_start_date, description, description_length, description_truncated, display_id, due_date, duration, estimated_time, has_description, has_project_attributes, id, ignore_non_working_days, parent_display_id, parent_id, percentage_done, priority, project, project_phase, readonly, remaining_time, responsible, schedule_manually, spent_time, sprint, start_date, status, subject, target_versions, type, updated_at, version.",
                "title": "Select",
            },
            "include_sums": {"default": False, "title": "Include Sums", "type": "boolean"},
            "custom_field_filters": {
                "anyOf": [
                    {"additionalProperties": {"additionalProperties": True, "type": "object"}, "type": "object"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Custom Field Filters",
            },
        },
        "required": ["search"],
        "title": "search_work_packagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "search",
        "project",
        "status",
        "open_only",
        "assignee_me",
        "assignee",
        "priority",
        "created_on",
        "created_between",
        "updated_on",
        "updated_between",
        "due_on",
        "due_between",
        "overdue_only",
        "due_within_days",
        "sort_by",
        "group_by",
        "offset",
        "limit",
        "select",
        "include_sums",
        "custom_field_filters",
    ]


def test_list_work_packages_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_packages"]
    assert (
        tool.description
        == 'List work packages with structured filters and no free-text query requirement.\n\nproject accepts a numeric ID, exact identifier/slug, or project name; the\nparameter is named project, not project_id. There is no generic\nfilters=[...] parameter; each filter is its own named argument (version,\nstatus, assignee, the date filters, etc.), listed below.\n\nversion_status filters by the status of a work package\'s assigned version:\none of \'open\', \'closed\', or \'locked\'. It requires OpenProject 16.4 or\nnewer. A work package with several target versions matches version and\nversion_status when any one of them matches.\n\nassignee filters by any user (username, id, or "me"). assignee_me takes precedence.\n\nstatus/priority filter by exact OpenProject status/priority name or numeric\nID (case-insensitive), not meta-values like \'open\'/\'closed\'; set\nopen_only=true to restrict results to not-closed work packages instead.\n\nDate filters accept YYYY-MM-DD format:\n- created_on/updated_on/due_on: exact date match\n- created_between/updated_between/due_between: inclusive date range [start, end]\nCannot specify both _on and _between for the same field.\n\noverdue_only=true restricts results to work packages with due_date before\ntoday that are not closed (OpenProject\'s own overdue? predicate; there\nis no dedicated overdue API filter, this composes a relative date filter\nwith the open-status meta-filter). due_within_days=N restricts to\ndue_date in [today, today+N days]. Neither can be combined with each\nother or with due_on/due_between (all four constrain the same field).\n\nsort_by and group_by are checked against OpenProject\'s real sortable and\ngroupable work-package columns (the parameters list them with the release\neach newer column needs); an unknown field raises a ValueError listing the\nvalid set instead of only failing once OpenProject itself rejects the\nrequest. A column the instance\'s release lacks is rejected by OpenProject\nand the error names the release it needs. Dates, hours, subject, id and\nthe other columns without a value per group sort fine but cannot be\ngrouped by.\n\nselect restricts each result row to the given fields (e.g. ["id", "subject",\n"status"]); an invalid name returns the allowed set. Common fields: id,\ndisplay_id, subject, type, status, priority, assignee, project, version,\nparent_id, parent_display_id, start_date, due_date, estimated_time,\nspent_time, created_at, updated_at, author, category, description,\nschedule_manually, derived_start_date, derived_due_date, percentage_done,\nderived_percentage_done, readonly, has_project_attributes, ignore_non_working_days,\ncustom_fields, custom_fields_truncated, custom_comments, custom_comments_truncated.\ncustom_fields/custom_comments are selectable/hideable only as a whole\nfield, not by individual custom-field key (per-key filtering is\nOPENPROJECT_HIDE_CUSTOM_FIELDS\' concern, not select\'s).\nparent_display_id is only populated on OpenProject 17.5+ (semantic mode);\nit stays null on older/classic instances even when parent_id is set.\n\ntotal is the real matching count only when the query is provably restricted to OPENPROJECT_READ_PROJECTS\nserver-side: scope is unrestricted, an explicit project was given, or (no project, restricted scope) a\nserver-side filter for the resolved allowed project IDs was sent. Otherwise total falls back to this page\'s item\ncount, and next_offset/truncated are based on whether this page came back full rather than the server\'s own\ntotal, so nothing here ever reveals how many matches exist in projects you can\'t see. Because of this, total can\nread 0 while next_offset is still non-null (a restrictive scope filtered out every match on this page, but the\nraw server page was full); that is not an inconsistency, keep paging via next_offset rather than stopping on a\nlow/zero total. Page until next_offset is null either way.\n\ninclude_sums=true adds server-computed aggregates instead of requiring\nclient-side pagination and summation: groups (one entry per group_by\nvalue, with count and a sums dict of OpenProject\'s fixed summable\nfields: estimated_time, story_points, percentage_done, remaining_time,\noverall_costs, labor_costs, material_costs, plus any custom fields, as\nraw server-formatted values, e.g. ISO 8601 durations and currency\nstrings) and total_sums (the same shape, across all matches). groups is\nonly populated when group_by is also set; total_sums is populated\neither way (a sum over the whole filtered result set even without\ngrouping). Same scope-safety rule as total above: groups/total_sums\ncome back null whenever the query cannot be proven restricted to\nOPENPROJECT_READ_PROJECTS server-side. A group named after a version,\nsprint or backlog bucket defined in a project that\nOPENPROJECT_READ_PROJECTS does not cover keeps its count and sums under\nthe label [outside read scope].\n\nVersion rollup recipe: group_by="status", version="<version id or\nname>", include_sums=true returns per-status progress/time sums for one\nversion\'s work packages, replacing manual pagination + client-side\nsummation.\n\ncustom_fields is a dict keyed by the RAW OpenProject key (e.g.\n"customField12") -- never a friendly name -- with values normalized by\nshape: plain scalars pass through; link-typed values (list/user/version\nformat) become title-only strings (or a list of titles for a multi-value\nfield), matching every other link field in this response; multi-\nparagraph "text"-format values are capped like description (this call\'s\neffective text_limit); a scalar string/link/date-format value is\nindependently capped at ~255 characters. custom_fields_truncated is true\nwhen the dict was capped at 50 entries and/or any individual entry\'s\nvalue was itself capped. custom_comments (keyed the same way, holding a\nfield\'s freeform comment text) and custom_comments_truncated follow the\nidentical shape and caps, independently -- in practice custom_comments\nis always empty/null for work packages on OpenProject\'s stock CE\nbehavior: only Projects opt into per-custom-field comments, work\npackages do not, so this field is present for forward compatibility\nonly. Combined worst case is roughly 250 KB for custom_fields per work\npackage, always finite regardless of how many custom fields exist or\nhow large their values are. get_work_packages (batch) and\nlist_my_open_work_packages return the same custom_fields/custom_comments\nshape and caps, since they reuse this same normalization.\nOPENPROJECT_HIDE_CUSTOM_FIELDS hides individual custom_fields entries by\nmatching ONLY the raw key/wildcard (e.g. "customField12", "customField*")\n-- unlike the write path, which also accepts the custom field\'s friendly\nname, a read-side hide pattern written as a friendly name has no effect.\n\ncustom_field_filters filters results by custom field value(s) -- a dict\nkeyed by "cf_<N>" or "customField<N>" (both forms accepted transparently\nand always normalized to "cf_<N>" on the wire; "cf_<N>" is\nCustomField#column_name, the actual OpenProject filter key, distinct from\n"customField<N>" which is the JSON/PATCH key used by custom_fields\nabove -- do not confuse the two). Each entry\'s value is\n{"operator": "<symbol>", "values": [...]}, e.g.\n{"cf_12": {"operator": "=", "values": ["42"]}}. Learn a field\'s cf_<N> id\nfrom any prior get_work_package call\'s custom_fields dict keys (strip the\n"customField" prefix). Only raw cf_<N>/customField<N> keys are accepted --\nfriendly-name resolution is not supported (a list/search call has no\nsingle project+type context to resolve a name against safely; a friendly\nname is only meaningful for the write path\'s per-call project+type\nschema probe). At most 20 custom-field filters per call, at most 100\nvalues per filter, each value at most 1000 characters.\n\nLegal operators depend on the field\'s format on this instance -- see\ndocs/filters.md\'s "Custom-Field Filters" section for the full\nformat-to-operator matrix, verified against OpenProject CE source. This\ntool validates the key shape and the operator symbol locally (a\nrecognized custom-field operator, not necessarily legal for this\nspecific field\'s format) and rejects hidden fields\n(OPENPROJECT_HIDE_CUSTOM_FIELDS) before any network call; an\noperator/value that is syntactically valid but illegal for the field\'s\nactual format is rejected by OpenProject itself with a clear error\n(surfaced as a ValueError here, not a raw HTTP passthrough) rather than\nvalidated client-side against a live schema -- this keeps list/search\ncalls at their existing single-request cost (no per-call schema probe).\nuser/version-format custom-field filters additionally require project to\nbe set (OpenProject only considers project-scoped custom fields of these\ntwo formats filterable at all; this is not checked locally -- a global,\nno-project user/version CF filter fails server-side with an unhelpful\n"filter not available" error, see docs/filters.md\'s "Global (no-project)\nfiltering constraint" section).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "type": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Type",
            },
            "version": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Version",
            },
            "version_status": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Version Status",
            },
            "open_only": {"default": False, "title": "Open Only", "type": "boolean"},
            "assignee_me": {"default": False, "title": "Assignee Me", "type": "boolean"},
            "assignee": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Assignee",
            },
            "status": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Status",
            },
            "priority": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Priority",
            },
            "created_on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Created On"},
            "created_between": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Created Between",
            },
            "updated_on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Updated On"},
            "updated_between": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Updated Between",
            },
            "due_on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Due On"},
            "due_between": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Due Between",
            },
            "overdue_only": {"default": False, "title": "Overdue Only", "type": "boolean"},
            "due_within_days": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Due Within Days",
            },
            "sort_by": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": 'Sort criteria as "field:direction" or "field-direction" (e.g. ["status:desc", "priority-asc"]); the direction defaults to asc. Fields: assigned_to, assignee, author, backlog_bucket, category, created_at, done_ratio, due_date, duration, estimated_hours, estimated_time, id, observed_in_versions, percentage_done, position, priority, project, project_phase, remaining_hours, remaining_time, responsible, sprint, start_date, status, story_points, subject, target_versions, type, updated_at, version, or a custom field\'s cf_<id>. Newer columns need an OpenProject release: project_phase 16.1+, sprint 17.4+, backlog_bucket 17.6+, target_versions 17.8+, observed_in_versions 17.9+; target_versions is version under its newer name. sprint and backlog_bucket also need the Backlogs module in a project where you may view sprints.',
                "title": "Sort By",
            },
            "group_by": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "One field to group the results by: assigned_to, assignee, author, backlog_bucket, category, done_ratio, observed_in_versions, percentage_done, priority, project, project_phase, responsible, sprint, status, target_versions, type, version, or a custom field's cf_<id>. Newer columns need an OpenProject release: project_phase 16.1+, sprint 17.4+, backlog_bucket 17.6+, target_versions 17.8+, observed_in_versions 17.9+; target_versions is version under its newer name. sprint and backlog_bucket also need the Backlogs module in a project where you may view sprints.",
                "title": "Group By",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: assignee, author, category, created_at, custom_comments, custom_comments_truncated, custom_fields, custom_fields_truncated, derived_due_date, derived_estimated_time, derived_percentage_done, derived_remaining_time, derived_start_date, description, description_length, description_truncated, display_id, due_date, duration, estimated_time, has_description, has_project_attributes, id, ignore_non_working_days, parent_display_id, parent_id, percentage_done, priority, project, project_phase, readonly, remaining_time, responsible, schedule_manually, spent_time, sprint, start_date, status, subject, target_versions, type, updated_at, version.",
                "title": "Select",
            },
            "include_sums": {"default": False, "title": "Include Sums", "type": "boolean"},
            "custom_field_filters": {
                "anyOf": [
                    {"additionalProperties": {"additionalProperties": True, "type": "object"}, "type": "object"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Custom Field Filters",
            },
        },
        "title": "list_work_packagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "project",
        "type",
        "version",
        "version_status",
        "open_only",
        "assignee_me",
        "assignee",
        "status",
        "priority",
        "created_on",
        "created_between",
        "updated_on",
        "updated_between",
        "due_on",
        "due_between",
        "overdue_only",
        "due_within_days",
        "sort_by",
        "group_by",
        "offset",
        "limit",
        "select",
        "include_sums",
        "custom_field_filters",
    ]


def test_get_work_package_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_work_package"]
    assert (
        tool.description
        == 'Get a work package by id, including its full description.\n\nThe description is returned in full by default (single work packages are not\ntruncated). Pass ``text_limit`` to cap it at that many characters; when the\ntext is cut, ``description_truncated`` is true and ``description_length``\nreports the real length. This same ``text_limit`` also caps any\n"text"-format custom field value in ``custom_fields`` (see\nlist_work_packages\'s docstring for the full custom_fields/custom_comments\nshape and hide-matching rules) -- but a scalar string/link/date-format\ncustom field value is capped independently at ~255 characters regardless\nof ``text_limit``, including when ``text_limit=None`` (the default here):\n"single work packages are not truncated" applies to description and CF\ntext-format values, not to that separate, always-on scalar cap.\n\nselect restricts the response to the given fields (e.g. ["id", "subject",\n"status"]); an invalid name returns the allowed set.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: ancestors, ancestors_truncated, assignee, author, category, children, children_truncated, created_at, custom_comments, custom_comments_truncated, custom_fields, custom_fields_truncated, derived_due_date, derived_estimated_time, derived_percentage_done, derived_remaining_time, derived_start_date, description, description_length, description_truncated, display_id, due_date, duration, estimated_time, has_project_attributes, id, ignore_non_working_days, lock_version, parent_display_id, parent_id, percentage_done, priority, project, project_phase, readonly, remaining_time, responsible, schedule_manually, spent_time, sprint, start_date, status, subject, target_versions, type, updated_at, version.",
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "get_work_packageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "text_limit", "select"]


def test_get_work_packages_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_work_packages"]
    assert (
        tool.description
        == 'Get several work packages by id in one batch call.\n\nFetches work packages in parallel and returns per-item results.\nFailed fetches are reported individually without stopping the batch.\nMaximum 100 IDs per batch.\n\nids: internal ids (e.g., 952) or display_ids (e.g., "PROJ-51"),\nnot UI display numbers. Duplicate IDs are automatically deduplicated.\n\nselect restricts each result\'s work_package to the given fields (e.g.\n["id", "subject", "status"]); an invalid name returns the allowed set.\nThe id/success/error fields on each result are always included regardless\nof select, so you can still tell which items succeeded; listing success or\nerror in select is accepted and changes nothing, while id doubles as a\nselectable work_package field.\n\nFor batches with many full-detail items, set text_limit and/or select\nproactively; an unbounded batch of large work packages can exceed the\ntool-result size limit and get redirected to a file.\n\nEach item\'s work_package carries the same custom_fields/custom_comments\nshape and caps as get_work_package; see list_work_packages\'s docstring\nfor the full details (raw-key values, per-field caps, and the\nOPENPROJECT_HIDE_CUSTOM_FIELDS key-only hide-matching asymmetry). With\nmany items, an unbounded custom_fields/custom_comments per item adds to\nthe same size-limit risk text_limit/select address above.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "ids": {"items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "title": "Ids", "type": "array"},
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: ancestors, ancestors_truncated, assignee, author, category, children, children_truncated, created_at, custom_comments, custom_comments_truncated, custom_fields, custom_fields_truncated, derived_due_date, derived_estimated_time, derived_percentage_done, derived_remaining_time, derived_start_date, description, description_length, description_truncated, display_id, due_date, duration, error, estimated_time, has_project_attributes, id, ignore_non_working_days, lock_version, parent_display_id, parent_id, percentage_done, priority, project, project_phase, readonly, remaining_time, responsible, schedule_manually, spent_time, sprint, start_date, status, subject, success, target_versions, type, updated_at, version.",
                "title": "Select",
            },
        },
        "required": ["ids"],
        "title": "get_work_packagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["ids", "text_limit", "select"]


def test_create_work_package_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_work_package"]
    assert (
        tool.description
        == "Create a work package.\n\nThe tool validates the payload first.\nassignee: 'me' or numeric user id (e.g., 42). Call list_users to find ids. parent: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number to nest the new work package under a parent.\nestimated_time, remaining_time, duration accept ISO8601 duration strings (e.g., 'PT8H' for 8 hours, 'PT1H30M' for 1.5 hours, 'P1D' for 1 day, 'P2W' for 2 weeks).\ntarget_versions accepts a list of version names/ids to assign multiple target versions at once\n(OpenProject's multi-version feature); omit it, or pass [], to create with no target version\nassigned. target_versions and version write the same underlying data and cannot be used together\nin one call.\ndue_date falling on a non-working day (e.g. a weekend) can be silently moved forward to the\nnext working day by OpenProject; compare the request and the returned `result.due_date` if\nthe exact calendar date matters. This server does not expose a way to opt out of that shift\n(OpenProject's own `ignoreNonWorkingDays` flag is not a write parameter here).\nA rejected validation preview is not a tool error; inspect `ready` and\n`validation_errors` in the result rather than the MCP error envelope.\nIf you issue multiple create_work_package/create_subtask calls concurrently, OpenProject assigns IDs in\nserver completion order, not call order; use bulk_create_work_packages instead when relative\nID/creation order across a batch matters.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "type": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Type"},
            "subject": {"title": "Subject", "type": "string"},
            "description": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Description"},
            "version": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Version",
            },
            "target_versions": {
                "anyOf": [
                    {"items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Target Versions",
            },
            "project_phase": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Project Phase",
            },
            "assignee": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Assignee",
            },
            "responsible": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Responsible",
            },
            "priority": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Priority",
            },
            "category": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Category",
            },
            "custom_fields": {
                "anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}],
                "default": None,
                "title": "Custom Fields",
            },
            "parent": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Parent",
            },
            "start_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Start Date"},
            "due_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Due Date"},
            "estimated_time": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Estimated Time",
            },
            "remaining_time": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Remaining Time",
            },
            "duration": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Duration"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project", "type", "subject"],
        "title": "create_work_packageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "project",
        "type",
        "subject",
        "description",
        "version",
        "target_versions",
        "project_phase",
        "assignee",
        "responsible",
        "priority",
        "category",
        "custom_fields",
        "parent",
        "start_date",
        "due_date",
        "estimated_time",
        "remaining_time",
        "duration",
        "confirm",
    ]


def test_update_work_package_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_work_package"]
    assert (
        tool.description
        == "Update a work package.\n\nThe tool validates the patch first.\ndescription is Markdown and replaces the whole text; pass \"\" to clear it. assignee: 'me' or numeric user id (e.g., 42). Call list_users to find ids. parent re-parents the work package (numeric id or a PROJ-123 reference); pass 'none' to remove the parent and make it top-level. version accepts a version name/id, or 'none' to unassign the version. sprint accepts a Backlogs sprint name/id (requires the Backlogs module and OpenProject 17.3+), or 'none' to unassign it. Pass 'none' to assignee, responsible, category or project_phase to unassign that field. Omitted fields stay unchanged.\ntarget_versions accepts a list of version names/ids to assign multiple target versions at once\n(OpenProject's multi-version feature); pass [] to clear all. target_versions and version write\nthe same underlying data and cannot be used together in one call. If this work package already\nhas more than one target version, version alone is rejected; use target_versions instead.\nA change of version, target_versions, sprint or a version custom field is refused while the work\npackage holds such an assignment in a project OPENPROJECT_READ_PROJECTS does not cover, because the\nchange would remove it.\nestimated_time, remaining_time, duration accept ISO8601 duration strings (e.g., 'PT8H' for 8 hours, 'PT1H30M' for 1.5 hours, 'P1D' for 1 day); omit to leave unchanged, or pass 'none' to clear the field. percentage_done is an integer 0-100.\nSetting status to a closed status auto-fills percentage_done=100 and remaining_time=PT0H when you\ndon't supply them explicitly and OpenProject's schema reports those fields as writable (on instances\nusing status-based progress calculation, OpenProject already derives them itself and this is skipped).\nOn such an instance, explicitly passing percentage_done together with a closing status is rejected\nwith a hard validation error (percentageDone is not writable there) rather than silently ignored;\nomit percentage_done and let OpenProject derive it instead.\ndue_date's non-working-day shift and the confirm/preview contract work exactly as documented\non create_work_package.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "subject": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Subject"},
            "description": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Description"},
            "type": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Type",
            },
            "version": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Version",
            },
            "target_versions": {
                "anyOf": [
                    {"items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Target Versions",
            },
            "sprint": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Sprint",
            },
            "project_phase": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Project Phase",
            },
            "status": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Status",
            },
            "assignee": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Assignee",
            },
            "responsible": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Responsible",
            },
            "priority": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Priority",
            },
            "category": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Category",
            },
            "custom_fields": {
                "anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}],
                "default": None,
                "title": "Custom Fields",
            },
            "parent": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Parent",
            },
            "start_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Start Date"},
            "due_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Due Date"},
            "estimated_time": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Estimated Time",
            },
            "remaining_time": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Remaining Time",
            },
            "duration": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Duration"},
            "percentage_done": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Percentage Done",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["work_package_id"],
        "title": "update_work_packageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "work_package_id",
        "subject",
        "description",
        "type",
        "version",
        "target_versions",
        "sprint",
        "project_phase",
        "status",
        "assignee",
        "responsible",
        "priority",
        "category",
        "custom_fields",
        "parent",
        "start_date",
        "due_date",
        "estimated_time",
        "remaining_time",
        "duration",
        "percentage_done",
        "confirm",
    ]


def test_bulk_create_work_packages_schema() -> None:
    tool = _tools(create_app(_make_settings()))["bulk_create_work_packages"]
    assert (
        tool.description
        == "Create multiple work packages in one call.\n\nNew items have no identifier field to set (unlike `bulk_update_work_packages`'s\n`work_package_id`); each result item is matched back to its input purely by `index`.\n\nEach item in `items` must contain `project`, `type`, and `subject`. Optional fields per item:\n`description`, `version`, `target_versions` (a list of version names/ids for OpenProject's\nmulti-version feature; cannot be combined with `version` on the same item), `project_phase`,\n`assignee`, `responsible`, `priority`, `category`,\n`custom_fields`, `parent_work_package_id` (or `parent`, an alias for the same field, matching\n`create_work_package`'s naming; do not specify both on the same item), `start_date`\n(YYYY-MM-DD), `due_date` (YYYY-MM-DD), `estimated_time`, `remaining_time`, `duration`\n(ISO8601 duration strings, e.g. 'PT8H' or 'P1D'). An item containing any other key is\nrejected with an indexed validation error rather than silently dropping the unrecognized field.\ndue_date falling on a non-working day (e.g. a weekend) can be silently moved forward to the\nnext working day by OpenProject; compare the request and the returned item's\n`result.result.due_date` if the exact calendar date matters. This server does not expose a\nway to opt out of that shift (OpenProject's own `ignoreNonWorkingDays` flag is not a write\nparameter here).\n\nA rejected item's validation is not a tool error; inspect each item's `success`,\n`error`, and nested `result` rather than the MCP error envelope.\n\nselect restricts each item's nested result to the given fields (e.g.\n[\"ready\", \"work_package_id\"]); an invalid name returns the allowed set.\nThese are write-result fields (work_package_id, ready, state, ...), not work\npackage fields: `display_id` and the rest come with `result`, the full\nwritten work package. The index/success/error fields on each item are always\nincluded regardless of select, so you can still tell which items succeeded;\nlisting them in select is accepted and changes nothing. For batches with many\nitems or long descriptions, set select proactively; an unconfirmed preview\nechoes each item's full proposed payload, and an unbounded batch can exceed\nthe tool-result size limit and get redirected to a file.\n\nA per-item timeout is reported as that item's failure and does not stop\nthe loop. If this call is cancelled outright (e.g. the host cancels the\nrequest), items already created beforehand remain on the server; items not\nyet attempted are not created. No result summary is returned in that case\n(the call ends via cancellation, not a normal return); use\nlist_work_packages/get_work_package afterward to determine what was\nactually written. This operation is not atomic; OpenProject CE has no\nbatch/transaction endpoint.\n\nItems are processed strictly sequentially in list order, and each result's index reflects that order;\nuse this tool instead of parallel create_work_package/create_subtask calls whenever the relative order\nof a batch matters.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "$defs": {
            "BulkCreateWorkPackageItem": {
                "additionalProperties": False,
                "description": "One work package of `bulk_create_work_packages`; a key outside this list is rejected, and so is\na value of the wrong JSON type (a boolean for a subject, a number for a description).",
                "properties": {
                    "project": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}],
                        "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                        "title": "Project",
                    },
                    "type": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Type"},
                    "subject": {"title": "Subject", "type": "string"},
                    "description": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Description"},
                    "version": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Version",
                    },
                    "target_versions": {
                        "anyOf": [
                            {"items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "type": "array"},
                            {"type": "null"},
                        ],
                        "title": "Target Versions",
                    },
                    "project_phase": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Project Phase",
                    },
                    "assignee": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Assignee",
                    },
                    "responsible": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Responsible",
                    },
                    "priority": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Priority",
                    },
                    "category": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Category",
                    },
                    "custom_fields": {
                        "anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}],
                        "title": "Custom Fields",
                    },
                    "parent": {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}], "title": "Parent"},
                    "parent_work_package_id": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                        "title": "Parent Work Package Id",
                    },
                    "start_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Start Date"},
                    "due_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Due Date"},
                    "estimated_time": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Estimated Time"},
                    "remaining_time": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Remaining Time"},
                    "duration": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Duration"},
                },
                "required": ["project", "type", "subject"],
                "title": "BulkCreateWorkPackageItem",
                "type": "object",
            }
        },
        "properties": {
            "items": {"items": {"$ref": "#/$defs/BulkCreateWorkPackageItem"}, "title": "Items", "type": "array"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: action, error, index, message, payload, project, ready, result, state, success, validation_errors, work_package_id.",
                "title": "Select",
            },
            "confirm": {
                "default": False,
                "description": "false: preview of every item, nothing changes. true: attempts every item; get the user's approval of the preview first. Failed items are reported per item; items already written are not undone.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["items"],
        "title": "bulk_create_work_packagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["items", "select", "confirm"]


def test_bulk_update_work_packages_schema() -> None:
    tool = _tools(create_app(_make_settings()))["bulk_update_work_packages"]
    assert (
        tool.description
        == "Update multiple work packages in one call.\n\nEach item's identifier field is `work_package_id`, not `id`, e.g.\n{\"work_package_id\": 952, \"status\": \"Closed\"}.\n\nEach item in `items` must contain `work_package_id`. At least one other field must be present per item.\nOptional fields per item: `subject`, `description` (\"\" clears it), `type`, `version`, `target_versions` (a list\nof version names/ids for OpenProject's multi-version feature; pass [] to clear all; cannot be\ncombined with `version` on the same item; rejected if the item's work package already has more\nthan one target version assigned), `sprint` (Backlogs sprint\nname/id, requires the Backlogs module and OpenProject 17.3+), `project_phase`, `status`,\n`assignee`, `responsible`, `priority`, `category`, `custom_fields`, `parent_work_package_id` (or\n`parent`, an alias for the same field, matching `update_work_package`'s naming; do not specify\nboth on the same item), `start_date` (YYYY-MM-DD), `due_date` (YYYY-MM-DD), `estimated_time`,\n`remaining_time`, `duration` (ISO8601 duration strings, e.g. 'PT8H' or 'P1D'; pass 'none' to clear\none of these), `percentage_done` (integer 0-100). Pass 'none' to `version`, `sprint`,\n`project_phase`, `assignee`, `responsible`, `category`, `parent_work_package_id`, or `parent` to\nclear that field on the item, same as `update_work_package`. An item containing any other key is\nrejected with an indexed validation error rather than silently dropping the unrecognized field.\nSetting an item's status to a closed status auto-fills percentage_done=100 and remaining_time=PT0H\nwhen that item doesn't supply them explicitly and OpenProject's schema reports those fields as\nwritable. On an instance using status-based progress calculation, explicitly passing\npercentage_done together with a closing status on the same item is rejected with a hard,\nindexed validation error (percentageDone is not writable there) rather than silently ignored;\nomit percentage_done on that item and let OpenProject derive it instead.\n\ndue_date's non-working-day shift, the confirm/preview contract, select's item-trimming\nbehavior, and cancellation/atomicity semantics all work exactly as documented on\nbulk_create_work_packages; only the affected result field differs\n(`result.result.due_date` here too). As there, select names write-result\nfields (work_package_id, ready, state, ...), not work package fields:\n`display_id` and the rest come with `result`, the full written work package.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "$defs": {
            "BulkUpdateWorkPackageItem": {
                "additionalProperties": False,
                "description": "One change of `bulk_update_work_packages`; a key outside this list is rejected, and so is a\nvalue of the wrong JSON type.",
                "properties": {
                    "work_package_id": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}],
                        "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                        "title": "Work Package Id",
                    },
                    "subject": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Subject"},
                    "description": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Description"},
                    "type": {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}], "title": "Type"},
                    "version": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Version",
                    },
                    "target_versions": {
                        "anyOf": [
                            {"items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "type": "array"},
                            {"type": "null"},
                        ],
                        "title": "Target Versions",
                    },
                    "sprint": {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}], "title": "Sprint"},
                    "project_phase": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Project Phase",
                    },
                    "status": {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}], "title": "Status"},
                    "assignee": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Assignee",
                    },
                    "responsible": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Responsible",
                    },
                    "priority": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Priority",
                    },
                    "category": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "title": "Category",
                    },
                    "custom_fields": {
                        "anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}],
                        "title": "Custom Fields",
                    },
                    "parent": {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}], "title": "Parent"},
                    "parent_work_package_id": {
                        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                        "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                        "title": "Parent Work Package Id",
                    },
                    "start_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Start Date"},
                    "due_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Due Date"},
                    "estimated_time": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Estimated Time"},
                    "remaining_time": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Remaining Time"},
                    "duration": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Duration"},
                    "percentage_done": {"anyOf": [{"type": "integer"}, {"type": "null"}], "title": "Percentage Done"},
                },
                "required": ["work_package_id"],
                "title": "BulkUpdateWorkPackageItem",
                "type": "object",
            }
        },
        "properties": {
            "items": {"items": {"$ref": "#/$defs/BulkUpdateWorkPackageItem"}, "title": "Items", "type": "array"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: action, error, index, message, payload, project, ready, result, state, success, validation_errors, work_package_id.",
                "title": "Select",
            },
            "confirm": {
                "default": False,
                "description": "false: preview of every item, nothing changes. true: attempts every item; get the user's approval of the preview first. Failed items are reported per item; items already written are not undone.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["items"],
        "title": "bulk_update_work_packagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["items", "select", "confirm"]


def test_delete_work_package_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_work_package"]
    assert (
        tool.description
        == "Delete a work package with its time and cost entries, relations, attachments and history.\n\nThis cannot be undone. Up to 17.6 all its descendants are deleted too; 17.7+ only those you may delete,\nthe others lose their parent.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["work_package_id"],
        "title": "delete_work_packageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "confirm"]


def test_create_subtask_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_subtask"]
    assert (
        tool.description
        == "Create a subtask under an existing work package.\n\nThe tool validates the payload first.\nConcurrent calls to this tool (or create_work_package) do not preserve call order in the resulting IDs;\nuse bulk_create_work_packages when order across several new items matters.\ntarget_versions accepts a list of version names/ids to assign multiple target versions at once\n(OpenProject's multi-version feature). target_versions and version write the same underlying\ndata and cannot be used together in one call.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "parent_work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Parent Work Package Id",
            },
            "type": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Type"},
            "subject": {"title": "Subject", "type": "string"},
            "description": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Description"},
            "version": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Version",
            },
            "target_versions": {
                "anyOf": [
                    {"items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Target Versions",
            },
            "project_phase": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Project Phase",
            },
            "assignee": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Assignee",
            },
            "responsible": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Responsible",
            },
            "priority": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Priority",
            },
            "category": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Category",
            },
            "custom_fields": {
                "anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}],
                "default": None,
                "title": "Custom Fields",
            },
            "start_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Start Date"},
            "due_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Due Date"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["parent_work_package_id", "type", "subject"],
        "title": "create_subtaskArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "parent_work_package_id",
        "type",
        "subject",
        "description",
        "version",
        "target_versions",
        "project_phase",
        "assignee",
        "responsible",
        "priority",
        "category",
        "custom_fields",
        "start_date",
        "due_date",
        "confirm",
    ]


def test_add_work_package_comment_schema() -> None:
    tool = _tools(create_app(_make_settings()))["add_work_package_comment"]
    assert (
        tool.description
        == "Add a comment to a work package.\n\nnotify=false avoids change emails by default.\nThe result never includes `details`/`created_at`, even on an ordinary,\nnon-aggregated comment: OpenProject can aggregate a new comment into an\nexisting, more recent journal entry (e.g. a prior status change) instead\nof always creating a fresh one, which would otherwise surface that\nunrelated change's details and timestamp here, and there is no reliable\nway to tell an aggregated response from a fresh one, so both fields are\nomitted unconditionally rather than only when aggregation is suspected;\n`details_omitted` is true.\n`user` is normally populated, but on rare cases where OpenProject's own\nwrite response omits it, a best-effort follow-up lookup fills it in; if\nthat also comes back empty, `user` stays null even though the comment was\nsaved successfully.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "comment": {"title": "Comment", "type": "string"},
            "internal": {"default": False, "title": "Internal", "type": "boolean"},
            "notify": {"default": False, "title": "Notify", "type": "boolean"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["work_package_id", "comment"],
        "title": "add_work_package_commentArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "comment", "internal", "notify", "confirm"]


def test_list_my_open_work_packages_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_my_open_work_packages"]
    assert (
        tool.description
        == "List the current user's open assigned work packages.\n\nThis query has no project scope of its own, so total is the real matching count only when\nOPENPROJECT_READ_PROJECTS is unrestricted (\"*\"); under a restricted scope, total always falls back to this\npage's item count, and next_offset/truncated are based on whether this page came back full rather than the\nserver's own total, so nothing here ever reveals how many matches exist in projects you can't see. Page until\nnext_offset is null either way.\n\nEach result row also carries custom_fields/custom_comments, selectable or\nhideable only as a whole field like every other field, with the same\nshape, caps, and OPENPROJECT_HIDE_CUSTOM_FIELDS key-only hide-matching as\nlist_work_packages -- see that tool's docstring for the full details.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: assignee, author, category, created_at, custom_comments, custom_comments_truncated, custom_fields, custom_fields_truncated, derived_due_date, derived_estimated_time, derived_percentage_done, derived_remaining_time, derived_start_date, description, description_length, description_truncated, display_id, due_date, duration, estimated_time, has_description, has_project_attributes, id, ignore_non_working_days, parent_display_id, parent_id, percentage_done, priority, project, project_phase, readonly, remaining_time, responsible, schedule_manually, spent_time, sprint, start_date, status, subject, target_versions, type, updated_at, version.",
                "title": "Select",
            },
        },
        "title": "list_my_open_work_packagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["offset", "limit", "select"]


def test_get_work_package_activities_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_work_package_activities"]
    assert (
        tool.description
        == "Get the activity log for a work package, most recent first.\n\nComments are returned in full by default (this is one work package's own\nhistory, not an open-ended multi-row list; same rationale as\nget_work_package). Pass ``text_limit`` to cap each comment at that many\ncharacters; when a comment is cut, ``comment_truncated`` is true and\n``comment_length`` reports its real length.\n\nWhen OPENPROJECT_READ_PROJECTS is not `*`, or a work package or custom field\nis hidden, change details are left out and ``details_omitted`` is true:\nOpenProject returns them as text in the API user's language with no\nstructure to check against the read scope or the hidden fields, and the\ntext can name parents, projects and versions of projects outside it and\ncarry the values of hidden fields. Comments, user and time are\nunaffected.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Number of most recent activities, capped at OPENPROJECT_MAX_PAGE_SIZE. Not paged.",
                "title": "Limit",
            },
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: comment, comment_length, comment_truncated, created_at, details, details_omitted, details_truncated, id, type, user, version.",
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "get_work_package_activitiesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "limit", "text_limit", "select"]


def test_list_work_package_reactions_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_reactions"]
    assert (
        tool.description
        == "List emoji reactions across a work package's comment activities.\n\nOne row per comment and reaction, without the activity id, so a reaction can repeat."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: count, emoji, reaction, users.",
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_reactionsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "select"]


def test_toggle_activity_emoji_reaction_schema() -> None:
    tool = _tools(create_app(_make_settings()))["toggle_activity_emoji_reaction"]
    assert (
        tool.description
        == "Toggle an emoji reaction on a work package comment activity.\n\nAdds the reaction if absent, removes it if already present. `reaction` is\none of: thumbs_up, thumbs_down, grinning_face_with_smiling_eyes,\nconfused_face, heart, party_popper, rocket, eyes.\n"
    )
    assert tool.output_schema == {
        "$defs": {
            "EmojiReactionListResult": {
                "properties": {
                    "count": {
                        "title": "Count",
                        "type": "integer",
                    },
                    "results": {
                        "items": {
                            "$ref": "#/$defs/EmojiReactionSummary",
                        },
                        "title": "Results",
                        "type": "array",
                    },
                },
                "required": ["count", "results"],
                "title": "EmojiReactionListResult",
                "type": "object",
            },
            "EmojiReactionSummary": {
                "properties": {
                    "reaction": {
                        "title": "Reaction",
                        "type": "string",
                    },
                    "emoji": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Emoji",
                    },
                    "count": {
                        "title": "Count",
                        "type": "integer",
                    },
                    "users": {
                        "items": {
                            "type": "string",
                        },
                        "title": "Users",
                        "type": "array",
                    },
                },
                "required": ["reaction", "emoji", "count", "users"],
                "title": "EmojiReactionSummary",
                "type": "object",
            },
        },
        "properties": {
            "action": {
                "title": "Action",
                "type": "string",
            },
            "state": {
                "enum": ["rejected", "invalid", "preview", "confirmed"],
                "title": "State",
                "type": "string",
            },
            "ready": {
                "title": "Ready",
                "type": "boolean",
            },
            "message": {
                "title": "Message",
                "type": "string",
            },
            "activity_id": {
                "title": "Activity Id",
                "type": "integer",
            },
            "reaction": {
                "title": "Reaction",
                "type": "string",
            },
            "result": {
                "anyOf": [
                    {
                        "$ref": "#/$defs/EmojiReactionListResult",
                    },
                    {
                        "type": "null",
                    },
                ],
            },
        },
        "required": ["action", "state", "ready", "message", "activity_id", "reaction", "result"],
        "title": "EmojiReactionWriteResult",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "activity_id": {"title": "Activity Id", "type": "integer"},
            "reaction": {"title": "Reaction", "type": "string"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["activity_id", "reaction"],
        "title": "toggle_activity_emoji_reactionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["activity_id", "reaction", "confirm"]
