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
        == "Search work packages by free text, optionally scoped to a project.\n\nsearch matches only the work package subject and numeric ID (OpenProject's\nnative subject_or_id full-text filter) — it does NOT match version,\ncategory, description, or other linked-resource fields. To filter by\nversion, use list_work_packages(version=..., project=...) instead.\n\nIn parallel with that text/id search, search is always also resolved\ndirectly (numeric id or display id like \"PROJ-42\") the same way\nget_work_package does. When that resolves to a work package that also\nsatisfies every other filter given here (project/status/assignee/dates/\ncustom fields/etc.), it's returned separately as exact_match — never\nfolded into results, and never counted toward total/count/pagination,\nsince a single extra item can't be paginated consistently. Absent (not\npresent in the response at all) when nothing resolves, when the\nresolved item fails a filter, or when it's already present in results\nvia the text match. select applies to exact_match the same way it\napplies to each results row.\n\nWithout project, the search runs globally across every project readable\nunder OPENPROJECT_READ_PROJECTS, not just one project — pass project\nexplicitly to scope results to it.\n\nSet status to restrict results to an exact OpenProject status name or\nnumeric ID — not a meta-value like 'open'/'closed'.\nSet open_only=true to return only open (not-closed) work packages.\nSet assignee_me=true to return only work packages assigned to the current user.\n\nassignee filters by any user (username, id, or \"me\"). assignee_me takes precedence.\n\npriority filters by priority name or numeric ID (case-insensitive).\n\nDate filters, overdue_only/due_within_days, sort_by/group_by, select,\npagination (offset/limit/total), include_sums, and each result's\ncustom_fields/custom_comments (raw-key custom-field values/comments,\ncapped and hide-matched exactly as documented) all work exactly as\ndocumented on list_work_packages — see that tool's docstring for the\nfull field lists and semantics. One difference: total is the real\nmatching count only when scope is unrestricted or an explicit project\nwas given (list_work_packages's server-side allowed-project filter for\nthe no-project+restricted-scope case does not apply here); otherwise\ntotal/groups/total_sums fall back to this page's data, same safety\nguarantee either way.\n\ncustom_field_filters filters by custom field value(s); see\nlist_work_packages's docstring for the full parameter documentation\n(identical shape and semantics on both tools).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "search": {
                "title": "Search",
                "type": "string",
            },
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status",
            },
            "open_only": {
                "default": False,
                "title": "Open Only",
                "type": "boolean",
            },
            "assignee_me": {
                "default": False,
                "title": "Assignee Me",
                "type": "boolean",
            },
            "assignee": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Assignee",
            },
            "priority": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Priority",
            },
            "created_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Created On",
            },
            "created_between": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Created Between",
            },
            "updated_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Updated On",
            },
            "updated_between": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Updated Between",
            },
            "due_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due On",
            },
            "due_between": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due Between",
            },
            "overdue_only": {
                "default": False,
                "title": "Overdue Only",
                "type": "boolean",
            },
            "due_within_days": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due Within Days",
            },
            "sort_by": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Sort By",
            },
            "group_by": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Group By",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
            },
            "include_sums": {
                "default": False,
                "title": "Include Sums",
                "type": "boolean",
            },
            "custom_field_filters": {
                "anyOf": [
                    {
                        "additionalProperties": {
                            "additionalProperties": True,
                            "type": "object",
                        },
                        "type": "object",
                    },
                    {
                        "type": "null",
                    },
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
        == 'List work packages with structured filters and no free-text query requirement.\n\nproject accepts a numeric ID, exact identifier/slug, or project name; the\nparameter is named project, not project_id. There is no generic\nfilters=[...] parameter — each filter is its own named argument (version,\nstatus, assignee, the date filters, etc.), listed below.\n\nversion_status filters by the status of a work package\'s assigned version:\none of \'open\', \'closed\', or \'locked\'.\n\nassignee filters by any user (username, id, or "me"). assignee_me takes precedence.\n\nstatus/priority filter by exact OpenProject status/priority name or numeric\nID (case-insensitive) — not meta-values like \'open\'/\'closed\'; set\nopen_only=true to restrict results to not-closed work packages instead.\n\nDate filters accept YYYY-MM-DD format:\n- created_on/updated_on/due_on: exact date match\n- created_between/updated_between/due_between: inclusive date range [start, end]\nCannot specify both _on and _between for the same field.\n\noverdue_only=true restricts results to work packages with due_date before\ntoday that are not closed (OpenProject\'s own overdue? predicate — there\nis no dedicated overdue API filter, this composes a relative date filter\nwith the open-status meta-filter). due_within_days=N restricts to\ndue_date in [today, today+N days]. Neither can be combined with each\nother or with due_on/due_between (all four constrain the same field).\n\nsort_by accepts a list of sort criteria in format "field:direction"\n(e.g., ["status:desc", "priority:asc"]). Direction defaults to "asc" if omitted.\nEach field is checked against OpenProject\'s real sortable work-package\ncolumns (id, project, subject, type, status, priority, author, assigned_to,\nresponsible, updated_at, category, version, start_date, due_date,\nestimated_time, remaining_time, done_ratio, created_at, duration,\nproject_phase, story_points, or a custom field\'s cf_<id> identifier) —\nan unknown field raises a ValueError listing the valid set instead of\nonly failing once OpenProject itself rejects the request.\n\ngroup_by accepts one field name to group results by (e.g., "status",\n"assigned_to"), checked the same way against OpenProject\'s actual\ngroupable columns (a subset of the sortable ones above — notably\nstart_date/due_date/estimated_time/remaining_time/duration/created_at/\nupdated_at sort fine but cannot be grouped by).\n\nselect restricts each result row to the given fields (e.g. ["id", "subject",\n"status"]); an invalid name returns the allowed set. Common fields: id,\ndisplay_id, subject, type, status, priority, assignee, project, version,\nparent_id, parent_display_id, start_date, due_date, estimated_time,\nspent_time, created_at, updated_at, author, category, description,\nschedule_manually, derived_start_date, derived_due_date, percentage_done,\nderived_percentage_done, readonly, ignore_non_working_days, custom_fields,\ncustom_fields_truncated, custom_comments, custom_comments_truncated.\ncustom_fields/custom_comments are selectable/hideable only as a whole\nfield, not by individual custom-field key (per-key filtering is\nOPENPROJECT_HIDE_CUSTOM_FIELDS\' concern, not select\'s).\nparent_display_id is only populated on OpenProject 17.5+ (semantic mode);\nit stays null on older/classic instances even when parent_id is set.\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call\'s offset to page past the cap. total is the real\nmatching count only when the query is provably restricted to\nOPENPROJECT_READ_PROJECTS server-side — scope is unrestricted, an explicit\nproject was given, or (no project, restricted scope) a server-side filter for\nthe resolved allowed project IDs was sent. Otherwise total falls back to this\npage\'s item count, and next_offset/truncated are based on whether this page\ncame back full rather than the server\'s own total, so nothing here ever\nreveals how many matches exist in projects you can\'t see. Because of this,\ntotal can read 0 while next_offset is still non-null (a restrictive scope\nfiltered out every match on this page, but the raw server page was full) —\nthat is not an inconsistency, keep paging via next_offset rather than\nstopping on a low/zero total. Page until next_offset is null either way.\n\ninclude_sums=true adds server-computed aggregates instead of requiring\nclient-side pagination and summation: groups (one entry per group_by\nvalue, with count and a sums dict of OpenProject\'s fixed summable\nfields — estimated_time, story_points, percentage_done, remaining_time,\noverall_costs, labor_costs, material_costs, plus any custom fields — as\nraw server-formatted values, e.g. ISO 8601 durations and currency\nstrings) and total_sums (the same shape, across all matches). groups is\nonly populated when group_by is also set; total_sums is populated\neither way (a sum over the whole filtered result set even without\ngrouping). Same scope-safety rule as total above: groups/total_sums\ncome back null whenever the query cannot be proven restricted to\nOPENPROJECT_READ_PROJECTS server-side.\n\nVersion rollup recipe: group_by="status", version="<version id or\nname>", include_sums=true returns per-status progress/time sums for one\nversion\'s work packages, replacing manual pagination + client-side\nsummation.\n\ncustom_fields is a dict keyed by the RAW OpenProject key (e.g.\n"customField12") -- never a friendly name -- with values normalized by\nshape: plain scalars pass through; link-typed values (list/user/version\nformat) become title-only strings (or a list of titles for a multi-value\nfield), matching every other link field in this response; multi-\nparagraph "text"-format values are capped like description (this call\'s\neffective text_limit); a scalar string/link/date-format value is\nindependently capped at ~255 characters. custom_fields_truncated is true\nwhen the dict was capped at 50 entries and/or any individual entry\'s\nvalue was itself capped. custom_comments (keyed the same way, holding a\nfield\'s freeform comment text) and custom_comments_truncated follow the\nidentical shape and caps, independently -- in practice custom_comments\nis always empty/null for work packages on OpenProject\'s stock CE\nbehavior: only Projects opt into per-custom-field comments, work\npackages do not, so this field is present for forward compatibility\nonly. Combined worst case is roughly 250 KB for custom_fields per work\npackage, always finite regardless of how many custom fields exist or\nhow large their values are. get_work_packages (batch) and\nlist_my_open_work_packages return the same custom_fields/custom_comments\nshape and caps, since they reuse this same normalization.\nOPENPROJECT_HIDE_CUSTOM_FIELDS hides individual custom_fields entries by\nmatching ONLY the raw key/wildcard (e.g. "customField12", "customField*")\n-- unlike the write path, which also accepts the custom field\'s friendly\nname, a read-side hide pattern written as a friendly name has no effect.\n\ncustom_field_filters filters results by custom field value(s) -- a dict\nkeyed by "cf_<N>" or "customField<N>" (both forms accepted transparently\nand always normalized to "cf_<N>" on the wire; "cf_<N>" is\nCustomField#column_name, the actual OpenProject filter key, distinct from\n"customField<N>" which is the JSON/PATCH key used by custom_fields\nabove -- do not confuse the two). Each entry\'s value is\n{"operator": "<symbol>", "values": [...]}, e.g.\n{"cf_12": {"operator": "=", "values": ["42"]}}. Learn a field\'s cf_<N> id\nfrom any prior get_work_package call\'s custom_fields dict keys (strip the\n"customField" prefix). Only raw cf_<N>/customField<N> keys are accepted --\nfriendly-name resolution is not supported (a list/search call has no\nsingle project+type context to resolve a name against safely; a friendly\nname is only meaningful for the write path\'s per-call project+type\nschema probe). At most 20 custom-field filters per call, at most 100\nvalues per filter, each value at most 1000 characters.\n\nLegal operators depend on the field\'s format on this instance -- see\ndocs/filters.md\'s "Custom-Field Filters" section for the full\nformat-to-operator matrix, verified against OpenProject CE source. This\ntool validates the key shape and the operator symbol locally (a\nrecognized custom-field operator, not necessarily legal for this\nspecific field\'s format) and rejects hidden fields\n(OPENPROJECT_HIDE_CUSTOM_FIELDS) before any network call; an\noperator/value that is syntactically valid but illegal for the field\'s\nactual format is rejected by OpenProject itself with a clear error\n(surfaced as a ValueError here, not a raw HTTP passthrough) rather than\nvalidated client-side against a live schema -- this keeps list/search\ncalls at their existing single-request cost (no per-call schema probe).\nuser/version-format custom-field filters additionally require project to\nbe set (OpenProject only considers project-scoped custom fields of these\ntwo formats filterable at all; this is not checked locally -- a global,\nno-project user/version CF filter fails server-side with an unhelpful\n"filter not available" error, see docs/filters.md\'s "Global (no-project)\nfiltering constraint" section).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
            "type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Type",
            },
            "version": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Version",
            },
            "version_status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Version Status",
            },
            "open_only": {
                "default": False,
                "title": "Open Only",
                "type": "boolean",
            },
            "assignee_me": {
                "default": False,
                "title": "Assignee Me",
                "type": "boolean",
            },
            "assignee": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Assignee",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status",
            },
            "priority": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Priority",
            },
            "created_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Created On",
            },
            "created_between": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Created Between",
            },
            "updated_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Updated On",
            },
            "updated_between": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Updated Between",
            },
            "due_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due On",
            },
            "due_between": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due Between",
            },
            "overdue_only": {
                "default": False,
                "title": "Overdue Only",
                "type": "boolean",
            },
            "due_within_days": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due Within Days",
            },
            "sort_by": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Sort By",
            },
            "group_by": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Group By",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
            },
            "include_sums": {
                "default": False,
                "title": "Include Sums",
                "type": "boolean",
            },
            "custom_field_filters": {
                "anyOf": [
                    {
                        "additionalProperties": {
                            "additionalProperties": True,
                            "type": "object",
                        },
                        "type": "object",
                    },
                    {
                        "type": "null",
                    },
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
        == 'Get a work package by id, including its full description.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"),\nnot UI display number (e.g., 51) — the same value list_work_packages/\nsearch_work_packages return as each row\'s `id` field.\n\nThe description is returned in full by default (single work packages are not\ntruncated). Pass ``text_limit`` to cap it at that many characters; when the\ntext is cut, ``description_truncated`` is true and ``description_length``\nreports the real length. This same ``text_limit`` also caps any\n"text"-format custom field value in ``custom_fields`` (see\nlist_work_packages\'s docstring for the full custom_fields/custom_comments\nshape and hide-matching rules) -- but a scalar string/link/date-format\ncustom field value is capped independently at ~255 characters regardless\nof ``text_limit``, including when ``text_limit=None`` (the default here):\n"single work packages are not truncated" applies to description and CF\ntext-format values, not to that separate, always-on scalar cap.\n\nselect restricts the response to the given fields (e.g. ["id", "subject",\n"status"]); an invalid name returns the allowed set.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
        == 'Get multiple work packages by ID in a single batch call.\n\nFetches work packages in parallel and returns per-item results.\nFailed fetches are reported individually without stopping the batch.\nMaximum 100 IDs per batch.\n\nids: internal ids (e.g., 952) or display_ids (e.g., "PROJ-51"),\nnot UI display numbers. Duplicate IDs are automatically deduplicated.\n\nselect restricts each result\'s work_package to the given fields (e.g.\n["id", "subject", "status"]); an invalid name returns the allowed set.\nThe id/success/error fields on each result are always included regardless\nof select, so you can still tell which items succeeded.\n\nFor batches with many full-detail items, set text_limit and/or select\nproactively — an unbounded batch of large work packages can exceed the\ntool-result size limit and get redirected to a file.\n\nEach item\'s work_package carries the same custom_fields/custom_comments\nshape and caps as get_work_package — see list_work_packages\'s docstring\nfor the full details (raw-key values, per-field caps, and the\nOPENPROJECT_HIDE_CUSTOM_FIELDS key-only hide-matching asymmetry). With\nmany items, an unbounded custom_fields/custom_comments per item adds to\nthe same size-limit risk text_limit/select address above.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "ids": {
                "items": {
                    "anyOf": [
                        {
                            "type": "integer",
                        },
                        {
                            "type": "string",
                        },
                    ],
                },
                "title": "Ids",
                "type": "array",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
        == "Prepare or create a work package.\n\nThe tool validates the payload first. Set confirm=true to write.\nassignee: 'me' or numeric user id (e.g., 42). Call list_users to find ids. parent: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number to nest the new work package under a parent.\nestimated_time, remaining_time, duration accept ISO8601 duration strings (e.g., 'PT8H' for 8 hours, 'PT1H30M' for 1.5 hours, 'P1D' for 1 day, 'P2W' for 2 weeks).\ndue_date falling on a non-working day (e.g. a weekend) can be silently moved forward to the\nnext working day by OpenProject — compare the request and the returned `result.due_date` if\nthe exact calendar date matters. This server does not expose a way to opt out of that shift\n(OpenProject's own `ignoreNonWorkingDays` flag is not a write parameter here).\nA rejected validation preview is not a tool error; inspect `ready` and\n`validation_errors` in the result rather than the MCP error envelope.\nIf you issue multiple create_work_package/create_subtask calls concurrently, OpenProject assigns IDs in\nserver completion order, not call order — use bulk_create_work_packages instead when relative\nID/creation order across a batch matters.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
            "type": {
                "title": "Type",
                "type": "string",
            },
            "subject": {
                "title": "Subject",
                "type": "string",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description",
            },
            "version": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Version",
            },
            "project_phase": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project Phase",
            },
            "assignee": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Assignee",
            },
            "responsible": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Responsible",
            },
            "priority": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Priority",
            },
            "category": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Category",
            },
            "custom_fields": {
                "anyOf": [
                    {
                        "additionalProperties": True,
                        "type": "object",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Custom Fields",
            },
            "parent": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Parent",
            },
            "start_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Start Date",
            },
            "due_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due Date",
            },
            "estimated_time": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Estimated Time",
            },
            "remaining_time": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Remaining Time",
            },
            "duration": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Duration",
            },
            "confirm": {
                "default": False,
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
        == "Prepare or update a work package.\n\nThe tool validates the patch first. Set confirm=true to write.\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\nassignee: 'me' or numeric user id (e.g., 42). Call list_users to find ids. parent re-parents the work package (numeric id or a PROJ-123 reference); pass 'none' to remove the parent and make it top-level. version accepts a version name/id, or 'none' to unassign the version. sprint accepts a Backlogs sprint name/id (requires the Backlogs module and OpenProject 17.3+), or 'none' to unassign it. Pass 'none' to assignee, responsible, category or project_phase to unassign that field. Omitted fields stay unchanged.\nestimated_time, remaining_time, duration accept ISO8601 duration strings (e.g., 'PT8H' for 8 hours, 'PT1H30M' for 1.5 hours, 'P1D' for 1 day); omit to leave unchanged, or pass 'none' to clear the field. percentage_done is an integer 0-100.\nSetting status to a closed status auto-fills percentage_done=100 and remaining_time=PT0H when you\ndon't supply them explicitly and OpenProject's schema reports those fields as writable (on instances\nusing status-based progress calculation, OpenProject already derives them itself and this is skipped).\nOn such an instance, explicitly passing percentage_done together with a closing status is rejected\nwith a hard validation error (percentageDone is not writable there) rather than silently ignored —\nomit percentage_done and let OpenProject derive it instead.\ndue_date's non-working-day shift and the confirm/preview contract work exactly as documented\non create_work_package.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "subject": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Subject",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description",
            },
            "type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Type",
            },
            "version": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Version",
            },
            "sprint": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Sprint",
            },
            "project_phase": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project Phase",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status",
            },
            "assignee": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Assignee",
            },
            "responsible": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Responsible",
            },
            "priority": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Priority",
            },
            "category": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Category",
            },
            "custom_fields": {
                "anyOf": [
                    {
                        "additionalProperties": True,
                        "type": "object",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Custom Fields",
            },
            "parent": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Parent",
            },
            "start_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Start Date",
            },
            "due_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due Date",
            },
            "estimated_time": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Estimated Time",
            },
            "remaining_time": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Remaining Time",
            },
            "duration": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Duration",
            },
            "percentage_done": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Percentage Done",
            },
            "confirm": {
                "default": False,
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
        == "Create multiple work packages in one call.\n\nNew items have no identifier field to set (unlike `bulk_update_work_packages`'s\n`work_package_id`) — each result item is matched back to its input purely by `index`.\n\nEach item in `items` must contain `project`, `type`, and `subject`. Optional fields per item:\n`description`, `version`, `project_phase`, `assignee`, `responsible`, `priority`, `category`,\n`custom_fields`, `parent_work_package_id` (or `parent`, an alias for the same field, matching\n`create_work_package`'s naming — do not specify both on the same item), `start_date`\n(YYYY-MM-DD), `due_date` (YYYY-MM-DD), `estimated_time`, `remaining_time`, `duration`\n(ISO8601 duration strings, e.g. 'PT8H' or 'P1D'). An item containing any other key is\nrejected with an indexed validation error rather than silently dropping the unrecognized field.\ndue_date falling on a non-working day (e.g. a weekend) can be silently moved forward to the\nnext working day by OpenProject — compare the request and the returned item's\n`result.result.due_date` if the exact calendar date matters. This server does not expose a\nway to opt out of that shift (OpenProject's own `ignoreNonWorkingDays` flag is not a write\nparameter here).\n\nWith confirm=false (default) all items are validated and a preview is returned.\nWith confirm=true all items are created. Failed items are reported in the result — the operation\ncontinues for remaining items regardless of individual failures. A rejected\nitem's validation is not a tool error; inspect each item's `success`,\n`error`, and nested `result` rather than the MCP error envelope.\n\nselect restricts each item's nested result to the given fields (e.g.\n[\"ready\", \"work_package_id\"]); an invalid name returns the allowed set. The\nindex/success/error fields on each item are always included regardless of\nselect, so you can still tell which items succeeded. For batches with many\nitems or long descriptions, set select proactively — an unconfirmed preview\nechoes each item's full proposed payload, and an unbounded batch can exceed\nthe tool-result size limit and get redirected to a file.\n\nA per-item timeout is reported as that item's failure and does not stop\nthe loop. If this call is cancelled outright (e.g. the host cancels the\nrequest), items already created beforehand remain on the server; items not\nyet attempted are not created. No result summary is returned in that case\n(the call ends via cancellation, not a normal return) — use\nlist_work_packages/get_work_package afterward to determine what was\nactually written. This operation is not atomic; OpenProject CE has no\nbatch/transaction endpoint.\n\nItems are processed strictly sequentially in list order, and each result's index reflects that order —\nuse this tool instead of parallel create_work_package/create_subtask calls whenever the relative order\nof a batch matters.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "items": {
                "items": {
                    "additionalProperties": True,
                    "type": "object",
                },
                "title": "Items",
                "type": "array",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
            },
            "confirm": {
                "default": False,
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
        == "Update multiple work packages in one call.\n\nEach item's identifier field is `work_package_id`, not `id` — e.g.\n{\"work_package_id\": 952, \"status\": \"Closed\"}.\n\nEach item in `items` must contain `work_package_id`. At least one other field must be present per item.\nOptional fields per item: `subject`, `description`, `type`, `version`, `sprint` (Backlogs sprint\nname/id, requires the Backlogs module and OpenProject 17.3+), `project_phase`, `status`,\n`assignee`, `responsible`, `priority`, `category`, `custom_fields`, `parent_work_package_id` (or\n`parent`, an alias for the same field, matching `update_work_package`'s naming — do not specify\nboth on the same item), `start_date` (YYYY-MM-DD), `due_date` (YYYY-MM-DD), `estimated_time`,\n`remaining_time`, `duration` (ISO8601 duration strings, e.g. 'PT8H' or 'P1D'; pass 'none' to clear\none of these), `percentage_done` (integer 0-100). Pass 'none' to `version`, `sprint`,\n`project_phase`, `assignee`, `responsible`, `category`, `parent_work_package_id`, or `parent` to\nclear that field on the item, same as `update_work_package`. An item containing any other key is\nrejected with an indexed validation error rather than silently dropping the unrecognized field.\nSetting an item's status to a closed status auto-fills percentage_done=100 and remaining_time=PT0H\nwhen that item doesn't supply them explicitly and OpenProject's schema reports those fields as\nwritable. On an instance using status-based progress calculation, explicitly passing\npercentage_done together with a closing status on the same item is rejected with a hard,\nindexed validation error (percentageDone is not writable there) rather than silently ignored —\nomit percentage_done on that item and let OpenProject derive it instead.\n\ndue_date's non-working-day shift, the confirm/preview contract, select's item-trimming\nbehavior, and cancellation/atomicity semantics all work exactly as documented on\nbulk_create_work_packages — only the affected result field differs\n(`result.result.due_date` here too).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "items": {
                "items": {
                    "additionalProperties": True,
                    "type": "object",
                },
                "title": "Items",
                "type": "array",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
            },
            "confirm": {
                "default": False,
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
        == 'Prepare or delete a work package.\n\nThe tool previews the target first. Set confirm=true to delete.\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "confirm": {
                "default": False,
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
        == 'Prepare or create a subtask under an existing work package.\n\nThe tool validates the payload first. Set confirm=true to write.\nparent_work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"),\nnot UI display number (e.g., 51) — the same value list_work_packages/\nget_work_package return as each row\'s `id` field (and as `parent_id`/\n`parent_display_id` on a child work package).\nConcurrent calls to this tool (or create_work_package) do not preserve call order in the resulting IDs;\nuse bulk_create_work_packages when order across several new items matters.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "parent_work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Parent Work Package Id",
            },
            "type": {
                "title": "Type",
                "type": "string",
            },
            "subject": {
                "title": "Subject",
                "type": "string",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description",
            },
            "version": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Version",
            },
            "project_phase": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project Phase",
            },
            "assignee": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Assignee",
            },
            "responsible": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Responsible",
            },
            "priority": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Priority",
            },
            "category": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Category",
            },
            "custom_fields": {
                "anyOf": [
                    {
                        "additionalProperties": True,
                        "type": "object",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Custom Fields",
            },
            "start_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Start Date",
            },
            "due_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Due Date",
            },
            "confirm": {
                "default": False,
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
        == "Prepare or add a comment to a work package.\n\nThe tool only writes when confirm=true. notify=false avoids change emails by default.\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\nThe result never includes `details`/`created_at`, even on an ordinary,\nnon-aggregated comment: OpenProject can aggregate a new comment into an\nexisting, more recent journal entry (e.g. a prior status change) instead\nof always creating a fresh one, which would otherwise surface that\nunrelated change's details and timestamp here — and there is no reliable\nway to tell an aggregated response from a fresh one, so both fields are\nomitted unconditionally rather than only when aggregation is suspected.\n`user` is normally populated, but on rare cases where OpenProject's own\nwrite response omits it, a best-effort follow-up lookup fills it in; if\nthat also comes back empty, `user` stays null even though the comment was\nsaved successfully.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "comment": {
                "title": "Comment",
                "type": "string",
            },
            "internal": {
                "default": False,
                "title": "Internal",
                "type": "boolean",
            },
            "notify": {
                "default": False,
                "title": "Notify",
                "type": "boolean",
            },
            "confirm": {
                "default": False,
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
        == "List the current user's open assigned work packages.\n\nselect fields: id, subject, due_date (see server instructions for\nselect's general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap. This query has no\nproject scope of its own, so total is the real matching count only when\nOPENPROJECT_READ_PROJECTS is unrestricted (\"*\"); under a restricted scope,\ntotal always falls back to this page's item count, and next_offset/truncated\nare based on whether this page came back full rather than the server's own\ntotal, so nothing here ever reveals how many matches exist in projects you\ncan't see. Page until next_offset is null either way.\n\nEach result row also carries custom_fields/custom_comments (not listed\nunder \"select fields\" above since they are selectable/hideable only as a\nwhole field, like every other field) with the same shape, caps, and\nOPENPROJECT_HIDE_CUSTOM_FIELDS key-only hide-matching as\nlist_work_packages -- see that tool's docstring for the full details.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
        == "Get the activity log for a work package, most recent first.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\n\nComments are returned in full by default (this is one work package's own\nhistory, not an open-ended multi-row list — same rationale as\nget_work_package). Pass ``text_limit`` to cap each comment at that many\ncharacters; when a comment is cut, ``comment_truncated`` is true and\n``comment_length`` reports its real length.\n\nselect fields: id, type, created_at (see server instructions for select's general semantics).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
        == "List emoji reactions across a work package's comment activities.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\n\nselect fields: reaction, count (see server instructions for select's general semantics).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
        == "Toggle an emoji reaction on a work package comment activity.\n\nAdds the reaction if absent, removes it if already present. `reaction` is\none of: thumbs_up, thumbs_down, grinning_face_with_smiling_eyes,\nconfused_face, heart, party_popper, rocket, eyes. Set confirm=true to apply\nit; call without confirm=true first to get a preview.\n"
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
            "activity_id": {
                "title": "Activity Id",
                "type": "integer",
            },
            "reaction": {
                "title": "Reaction",
                "type": "string",
            },
            "confirm": {
                "default": False,
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
