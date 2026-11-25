"""Every parameter of every read tool is classified, and every filter is guarded where it runs.

A filter parameter that selects by a hidden field is refused (`filter_policy`). This guard keeps the table complete
without depending on the name of a parameter:

- the registry: every registered tool is a read tool, a write tool or one of the listed mutation tools;
- the parameters: every parameter of every read tool function is a filter (the table of `test_filter_policy`), a
  structural parameter (a container the caller must name, a path, a record), a parameter an own policy guards
  (projects, work packages, the sums), a deferred one with its ticket, a record or parent id, or paging and shaping;
  a stale row fails and no parameter is in two classes;
- the call: the service method behind each filter tool calls `ensure_filter_allowed` with exactly the parameters it
  accepts, before its first `await` and before anything that reads;
- the client-side filters: a function passed to a pagination mechanism, and the condition of a comprehension, in a
  read method is a filter site; a comparison there (other than a presence or paging check) means the tool has a filter
  row. A comparison in a helper the site calls is followed (see the stated boundary below).

Stated boundary: a helper is followed when it is in the service module or imported by name (with or without an alias)
from a followed module (`FOLLOWED_MODULES`); a call through a module attribute (`scope_policy.x`) and any other module
are not, so a filter written there has no comparison for the census to see, and the runtime scan of
`test_filter_on_hidden_field_runtime` covers the parameters of the table by running them. A comparison that changes
inside a known site changes the written text and fails; a new parameter fails the parameter census first.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
from collections.abc import Iterator
from typing import Any

import pytest
from _client_test_helpers import _base_settings
from test_filter_policy import EXPECTED

from openproject_ce_mcp import tools, tools_runtime
from openproject_ce_mcp.app import pagination
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.project_columns import FILTER_RESULT_FIELDS as PROJECT_FILTERS
from openproject_ce_mcp.work_package_columns import FILTER_RESULT_FIELDS as WORK_PACKAGE_FILTERS

SHAPING = frozenset({"offset", "limit", "text_limit", "select"})

CONTAINER = "required or a path the caller names: no unfiltered list exists, the rows tell nothing the argument did not"
AVAILABILITY = "selects what is enabled or shared into a project: no field of the record"
SCHEMA = "picks which schema is returned, not which records"
STRUCTURAL: dict[tuple[str, str], str] = {
    ("list_categories", "project"): CONTAINER,
    ("list_project_memberships", "project"): CONTAINER,
    ("list_user_non_working_times", "user_ref"): CONTAINER,
    ("list_user_working_hours", "user_ref"): CONTAINER,
    ("get_user_working_hours", "user_ref"): CONTAINER,
    ("list_types", "project"): AVAILABILITY,
    ("list_query_filter_instance_schemas", "project"): AVAILABILITY,
    ("get_project_work_package_context", "type"): SCHEMA,
}

_WORK_PACKAGE_QUERY = (
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
    "include_sums",
    "custom_field_filters",
)
OWN_POLICY: dict[str, tuple[str, ...]] = {
    "list_projects": ("search", "custom_field_filters", "sort_by"),
    "list_work_packages": ("project", *_WORK_PACKAGE_QUERY),
    "search_work_packages": (
        "search",
        "project",
        *(p for p in _WORK_PACKAGE_QUERY if p not in ("type", "version", "version_status")),
    ),
    # Aggregates the service masks itself (`_sum_hours`, the size sum): the sum is left out while the field is hidden.
    "list_time_entries": ("include_total_hours",),
    "list_work_package_attachments": ("include_total_size",),
}

# A parameter that selects or orders by a hidden field and has a ticket of its own.
DEFERRED: dict[tuple[str, str], str] = {
    ("get_user", "user"): "OPM-913",
}

# A parameter that names a stored selection: the filters, sort and group of the saved query run server-side, and
# `stored_query_policy` judges the definition of every page (`test_stored_query_service.py`).
STORED_SELECTION: dict[tuple[str, str], str] = {
    ("execute_query", "query_id"): "the saved query's own filters, sort and group, judged on every page",
}

# The record a tool reads, the parent a list is read from, or text it renders: no selection by a field.
NOT_A_FILTER: dict[str, tuple[str, ...]] = {
    "get_attachment": ("attachment_id",),
    "get_attachment_content": (
        "attachment_id",
        "max_bytes",
    ),
    "get_backlog_bucket": ("backlog_bucket_id",),
    "get_board": ("board_id",),
    "get_category": ("category_id",),
    "get_cost_entry": ("cost_entry_id",),
    "get_cost_type": ("cost_type_id",),
    "get_custom_option": ("custom_option_id",),
    "get_document": ("document_id",),
    "get_github_pull_request": ("github_pull_request_id",),
    "get_grid": ("grid_id",),
    "get_group": ("group_id",),
    "get_help_text": ("help_text_id",),
    "get_job_status": ("job_status_id",),
    "get_meeting": ("meeting_id",),
    "get_meeting_agenda_item": ("agenda_item_id",),
    "get_meeting_outcome": ("outcome_id",),
    "get_meeting_section": ("section_id",),
    "get_membership": ("membership_id",),
    "get_my_project_access": ("project",),
    "get_news": ("news_id",),
    "get_post": ("post_id",),
    "get_priority": ("priority_id",),
    "get_project": ("project",),
    "get_project_admin_context": ("project",),
    "get_project_configuration": ("project",),
    "get_project_phase": ("phase_id",),
    "get_project_phase_definition": ("phase_definition_id",),
    "get_project_storage": ("project_storage_id",),
    "get_project_work_package_context": ("project",),
    "get_query_column": ("column_id",),
    "get_query_filter": ("filter_id",),
    "get_query_filter_instance_schema": ("schema_id",),
    "get_query_operator": ("operator_id",),
    "get_query_sort_by": ("sort_by_id",),
    "get_recurring_meeting": ("recurring_meeting_id",),
    "get_sprint": ("sprint_id",),
    "get_status": ("status_id",),
    "get_storage": ("storage_id",),
    "get_time_entry": ("time_entry_id",),
    "get_type": ("type_id",),
    "get_user_working_hours": ("working_hours_id",),
    "get_version": ("version_id",),
    "get_view": ("view_id",),
    "get_wiki_page": ("wiki_page_id",),
    "get_work_package": ("work_package_id",),
    "get_work_package_activities": ("work_package_id",),
    "get_work_package_costs_by_type": ("work_package_id",),
    "get_work_package_relations": ("work_package_id",),
    "get_work_packages": ("ids",),
    "list_capabilities": ("capability_id",),
    "list_meeting_agenda_items": ("meeting_id",),
    "list_meeting_outcomes": ("agenda_item_id",),
    "list_meeting_sections": ("meeting_id",),
    "list_recurring_meeting_occurrences": ("recurring_meeting_id",),
    "list_work_package_attachments": ("work_package_id",),
    "list_work_package_cost_entries": ("work_package_id",),
    "list_work_package_file_links": ("work_package_id",),
    "list_work_package_github_pull_requests": ("work_package_id",),
    "list_work_package_gitlab_issues": ("work_package_id",),
    "list_work_package_gitlab_merge_requests": ("work_package_id",),
    "list_work_package_meeting_agenda_items": ("work_package_id",),
    "list_work_package_reactions": ("work_package_id",),
    "list_work_package_watchers": ("work_package_id",),
    "list_work_package_wiki_links": ("work_package_id",),
    "render_text": (
        "text",
        "format",
    ),
}
READ_TOOLS = sorted({name for names in tools.READ_TOOLS_BY_SCOPE.values() for name in names})
FILTER_TOOLS = sorted({tool for tool, _ in EXPECTED})
# The tool parameter and the parameter of the service method differ for two tools.
SERVICE_PARAMETER = {("list_views", "type"): "view_type", ("get_category", "project"): "project_ref"}


def _function_parameters(function: Any) -> list[str]:
    return [name for name in inspect.signature(function).parameters if name != "ctx"]


def test_every_registered_tool_is_a_read_tool_or_a_write_tool() -> None:
    writes: set[str] = (
        set(tools.ADMIN_WRITE_TOOLS) | set(tools.PERSONAL_MUTATION_TOOLS) | set(tools.ATTACHMENT_UPLOAD_TOOLS)
    )
    for names in tools.WRITE_TOOLS_BY_SCOPE.values():
        writes |= set(names)

    assert set(tools_runtime._TOOL_FUNCTIONS) == set(READ_TOOLS) | writes
    assert not set(READ_TOOLS) & writes


def test_every_parameter_of_every_read_tool_is_classified_exactly_once() -> None:
    classes: dict[tuple[str, str], list[str]] = {}

    def add(key: tuple[str, str], kind: str) -> None:
        classes.setdefault(key, []).append(kind)

    for key in EXPECTED:
        add(key, "filter")
    for key in STRUCTURAL:
        add(key, "structural")
    for tool, names in OWN_POLICY.items():
        for name in names:
            add((tool, name), "own policy")
    for key in DEFERRED:
        add(key, "deferred")
    for key in STORED_SELECTION:
        add(key, "stored selection")
    for tool, names in NOT_A_FILTER.items():
        for name in names:
            add((tool, name), "record or parent")

    existing = {
        (tool, name)
        for tool in READ_TOOLS
        for name in _function_parameters(tools_runtime._TOOL_FUNCTIONS[tool])
        if name not in SHAPING
    }
    assert sorted(existing - set(classes)) == [], "a read tool parameter that no table classifies"
    assert sorted(set(classes) - existing) == [], "a classified row of a parameter that no longer exists"
    assert sorted(key for key, kinds in classes.items() if len(kinds) > 1) == []


def _service_methods(tool: str) -> list[tuple[type, str, ast.AsyncFunctionDef | ast.FunctionDef]]:
    """The service methods a read tool function calls (`client.<service>.<method>(`), with their syntax trees."""
    function = tools_runtime._TOOL_FUNCTIONS[tool]
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    client = OpenProjectClient(_base_settings())
    found: list[tuple[type, str, ast.AsyncFunctionDef | ast.FunctionDef]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "client"
        ):
            service = type(getattr(client, node.func.value.attr))
            method = getattr(service, node.func.attr)
            definition = ast.parse(textwrap.dedent(inspect.getsource(method))).body[0]
            assert isinstance(definition, (ast.AsyncFunctionDef, ast.FunctionDef))
            found.append((service, node.func.attr, definition))
    return found


def _first_await_line(definition: ast.AST) -> int:
    lines = [node.lineno for node in ast.walk(definition) if isinstance(node, ast.Await)]
    return min(lines, default=10**9)


@pytest.mark.parametrize("tool", FILTER_TOOLS)
def test_the_service_behind_a_filter_tool_calls_the_policy_with_its_parameters_before_it_awaits(tool: str) -> None:
    methods = _service_methods(tool)
    assert methods, f"{tool}: no `client.<service>.<method>(` call found: the census cannot see the service"
    guarded = 0
    for service, name, definition in methods:
        accepted = {arg.arg for arg in (*definition.args.args, *definition.args.kwonlyargs)}
        required = {
            parameter
            for (row_tool, parameter) in EXPECTED
            if row_tool == tool and SERVICE_PARAMETER.get((tool, parameter), parameter) in accepted
        }
        if not required:
            continue
        calls = [
            node
            for node in ast.walk(definition)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "ensure_filter_allowed"
        ]
        label = f"{service.__name__}.{name}"
        assert len(calls) == 1, f"{label}: expected one call of the filter policy, found {len(calls)}"
        call = calls[0]
        assert isinstance(call.args[0], ast.Constant) and call.args[0].value == tool, label
        passed = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg != "settings"}
        assert passed == {parameter: SERVICE_PARAMETER.get((tool, parameter), parameter) for parameter in required}, (
            label
        )
        assert call.lineno < _first_await_line(definition), f"{label}: the policy is called after an await"
        guarded += 1
    assert guarded >= 1, f"{tool}: no service method takes a filter parameter of the table"


# ---- the client-side filter sites -------------------------------------------------------------------------------

ARITHMETIC = frozenset({"paginate_server", "clamp_limit", "effective_limit", "collection_exhausted", "page_is_last"})
MECHANISMS = frozenset(
    name
    for name, function in inspect.getmembers(pagination, inspect.isfunction)
    if function.__module__ == pagination.__name__ and not name.startswith("_")
) - ARITHMETIC | {"_fetch_all_pages"}
CALLBACK_KEYWORDS = frozenset({"item_allowed", "item_allowed_bulk"})
# A text match written as a call instead of a comparison.
TEXT_MATCHERS = frozenset(
    {"startswith", "endswith", "find", "index", "count", "match", "search", "fullmatch", "fnmatch", "fnmatchcase"}
)
# Modules besides the service's own whose functions a service method calls to filter.
FOLLOWED_MODULES = (
    "openproject_ce_mcp.app.resolvers.version_query",
    "openproject_ce_mcp.app.services.project_scoped_list",
)


def _is_presence_or_paging(compare: ast.Compare) -> bool:
    """`x is None`, `x is not None` and a comparison with a `len(...)` are checks of presence or of paging."""
    if all(isinstance(op, (ast.Is, ast.IsNot)) for op in compare.ops):
        return True
    return any(
        isinstance(side, ast.Call) and isinstance(side.func, ast.Name) and side.func.id == "len"
        for side in (compare.left, *compare.comparators)
    )


def _loop_conditions(node: ast.For) -> list[ast.expr]:
    """The conditions of a loop that keeps or drops rows: an `if` whose branch continues or appends."""
    found: list[ast.expr] = []
    for inner in ast.walk(node):
        if isinstance(inner, ast.If) and any(
            isinstance(leaf, ast.Continue)
            or (isinstance(leaf, ast.Call) and isinstance(leaf.func, ast.Attribute) and leaf.func.attr == "append")
            for branch in (*inner.body, *inner.orelse)
            for leaf in ast.walk(branch)
        ):
            found.append(inner.test)
    return found


def _callee_name(call: ast.Call) -> str:
    return call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")


def _callable_regions(
    value: ast.expr, function: ast.AST, nested: dict[str, list[ast.AST]], methods: dict[str, ast.AST]
) -> list[ast.AST]:
    """What a value handed to a mechanism runs: a lambda, a nested function or method by name, a lambda assigned to
    a name in the function, or the first argument of `functools.partial`."""
    if isinstance(value, ast.Lambda):
        return [value]
    if isinstance(value, ast.Call) and _callee_name(value) == "partial" and value.args:
        return _callable_regions(value.args[0], function, nested, methods)
    if isinstance(value, ast.Name):
        found: list[ast.AST] = list(nested.get(value.id, []))
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == value.id for t in node.targets):
                found.extend(_callable_regions(node.value, function, nested, methods))
        return found
    if isinstance(value, ast.Attribute) and value.attr in methods:
        return [methods[value.attr]]
    return []


def _regions(function: ast.AST, nested: dict[str, list[ast.AST]], methods: dict[str, ast.AST]) -> list[ast.AST]:
    """The code of one function that decides which records stay: a function or lambda handed to a pagination
    mechanism or to `filter`, the conditions of its comprehensions and of the loops that keep or drop rows."""
    regions: list[ast.AST] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            callee = _callee_name(node)
            handed = [k.value for k in node.keywords if k.arg in CALLBACK_KEYWORDS] if callee in MECHANISMS else []
            if callee == "filter":
                handed = list(node.args[:1])
            for value in handed:
                regions.extend(_callable_regions(value, function, nested, methods))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for generator in node.generators:
                regions.extend(generator.ifs)
        elif isinstance(node, ast.For):
            regions.extend(_loop_conditions(node))
    return regions


def _followed_functions(module: ast.Module) -> dict[str, ast.AST]:
    """The functions the service module imports from a followed module, under the name it imports them by."""
    found: dict[str, ast.AST] = {}
    for name in FOLLOWED_MODULES:
        tree = ast.parse(inspect.getsource(importlib.import_module(name)))
        defined = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in module.body:
            if isinstance(node, ast.ImportFrom) and node.module and name.endswith("." + node.module.split(".")[-1]):
                for alias in node.names:
                    if alias.name in defined:
                        found[alias.asname or alias.name] = defined[alias.name]
    return found


def _nested_functions(function: ast.AST) -> dict[str, list[ast.AST]]:
    found: dict[str, list[ast.AST]] = {}
    for node in ast.walk(function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not function:
            found.setdefault(node.name, []).append(node)
    return found


def counted_comparisons(
    method: ast.AST, module: ast.Module, owner: ast.ClassDef | None, *, follow: bool = False
) -> list[str]:
    """The comparisons and text-match calls that decide a client-side filter of a read method: those in its filter
    regions and in the helpers it calls in the same module (a function by name, a `self` method) or in a followed
    module. Presence and paging checks are left out."""
    methods = {n.name: n for n in owner.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))} if owner else {}
    functions = {n.name: n for n in module.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if follow:
        functions = _followed_functions(module) | functions
    nested: dict[str, list[ast.AST]] = {}

    def callees(node: ast.AST) -> Iterator[ast.AST]:
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self"
            ):
                targets = [methods[call.func.attr]] if call.func.attr in methods else []
            elif isinstance(call.func, ast.Name):
                targets = nested.get(call.func.id) or ([functions[call.func.id]] if call.func.id in functions else [])
            else:
                targets = []
            yield from targets

    # Functions whose own filter regions count: the method and the helpers it calls, with the functions each holds.
    scanned: list[ast.AST] = []
    queue: list[ast.AST] = [method]
    while queue:
        function = queue.pop()
        if any(function is other for other in scanned):
            continue
        scanned.append(function)
        for name, definitions in _nested_functions(function).items():
            nested.setdefault(name, []).extend(d for d in definitions if not any(d is e for e in nested.get(name, [])))
        queue.extend(callees(function))
    pending: list[ast.AST] = [region for function in scanned for region in _regions(function, nested, methods)]
    seen: set[int] = set()
    found: list[str] = []
    while pending:
        region = pending.pop()
        if id(region) in seen:
            continue
        seen.add(id(region))
        for node in ast.walk(region):
            if isinstance(node, ast.Compare) and not _is_presence_or_paging(node):
                found.append(ast.unparse(node))
            elif isinstance(node, ast.Call) and _callee_name(node) in TEXT_MATCHERS:
                found.append(ast.unparse(node))
        pending.extend(callees(region))
    return sorted(set(found))


def _read_sites() -> Iterator[tuple[str, str, list[str]]]:
    for tool in READ_TOOLS:
        for service, name, definition in _service_methods(tool):
            module = ast.parse(inspect.getsource(inspect.getmodule(service)))  # type: ignore[arg-type]
            owner = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == service.__name__)
            compares = counted_comparisons(definition, module, owner, follow=True)
            if compares:
                yield tool, f"{service.__name__}.{name}", compares


# Every comparison of a client-side filter site of a read tool, with what it decides: a filter parameter of the table
# (by name), or one of the kinds below. A new site, a new comparison in a known site, and one that is gone fail.
KINDS = {
    "paging": "counts or skips rows of a page, selects nothing by a field",
    "cache": "membership of a resolved reference in a cache of the call",
    "parent": "the parent record the list is read from (the container the caller named)",
    "schema": "picks the values a schema allows",
    "own policy": "a filter of the work package policy, covered there",
    "presence": "tells whether the caller set a parameter, selects nothing",
    "scope": "the read allowlist of the record, not a parameter of the caller",
    "deferred": "selects by a field and has a ticket of its own (OPM-914 for the inlined images)",
}
CLIENT_SITES: dict[tuple[str, str], dict[str, str]] = {
    ("get_grid", "GridService.get"): {
        "ref not in cache": "cache",
    },
    ("get_project_admin_context", "ProjectAdminService.get_admin_context"): {
        "field.key == 'status'": "schema",
        "field.key.startswith('customField')": "schema",
        "value.href not in uncovered": "schema",
    },
    ("list_backlog_buckets", "BacklogBucketService.list_for_project"): {
        "search.casefold() in (record.summary.name or '').casefold()": "search",
    },
    ("list_backlog_buckets", "BacklogBucketService.list"): {
        "search.casefold() in (record.summary.name or '').casefold()": "search",
    },
    ("list_boards", "BoardService.list"): {
        "project_id_from_href(href, settings=settings) == project_id": "project",
        "search_key in (record.summary.name or '').casefold()": "search",
    },
    ("list_capabilities", "ActionCapabilityService.list_capabilities"): {
        "_context_href(context_link) == self._global_context_href": "scope",
        "scope_policy.project_id_from_href(_context_href(context_link), settings=self._settings) == project_id": "project",
    },
    ("list_documents", "DocumentService.list"): {
        "project_id_from_href(href, settings=settings) == project_id": "project",
        "search_key in (record.summary.title or '').casefold()": "search",
    },
    ("list_grids", "GridService.list"): {
        "ref not in cache": "cache",
    },
    ("list_groups", "GroupService.list_groups"): {
        "search_key in (record.summary.name or '').casefold()": "search",
    },
    ("list_my_open_work_packages", "WorkPackageService.list_my_open"): {
        "skipped < skip_count": "paging",
    },
    ("list_news", "NewsService.list"): {
        "project_id_from_href(href, settings=settings) == project_id": "project",
        "search_key in (record.summary.summary or '').casefold()": "search",
        "search_key in (record.summary.title or '').casefold()": "search",
    },
    ("list_notifications", "NotificationService.list_all"): {
        "skipped < skip_count": "paging",
    },
    ("list_project_storages", "ProjectStorageService.list_project_storages"): {
        "project_id_from_href(href, settings=settings) == project_id": "project",
    },
    ("list_sprints", "SprintService.list_for_project"): {
        "search.casefold() in (record.summary.name or '').casefold()": "search",
    },
    ("list_sprints", "SprintService.list"): {
        "search.casefold() in (record.summary.name or '').casefold()": "search",
    },
    ("list_time_entries", "TimeEntryService.list_all"): {
        "item.get('id') not in new_ids": "paging",
        "linked_id != filter_project_id": "project",
        "normalized.entity_id == resolved_work_package_id": "work_package_id",
        "normalized.entity_type == 'WorkPackage'": "work_package_id",
        "normalized.spent_on < spent_on_from": "spent_on_from",
        "normalized.spent_on > spent_on_to": "spent_on_to",
        "scope_policy.id_from_href(user_link.get('href') if isinstance(user_link, dict) else None) != user_id": "user",
    },
    ("list_users", "UserService.list_users"): {
        "search_key in (record.summary.email or '').casefold()": "search",
        "search_key in (record.summary.login or '').casefold()": "search",
        "search_key in (record.summary.name or '').casefold()": "search",
    },
    ("list_versions", "VersionService.list"): {
        "global_search_key in (record.summary.name or '').casefold()": "search",
        "search_key in (item.name or '').casefold()": "search",
    },
    ("list_views", "ViewService.list"): {
        "(record.summary.type or '').casefold() != view_type.casefold()": "type",
        "project_id_from_href(href, settings=settings) == project_id": "project",
        "search_key in (record.summary.name or '').casefold()": "search",
    },
    ("list_work_package_attachments", "AttachmentService.list_for_work_package_with_images"): {
        "content_type in _INLINE_IMAGE_TYPES": "include_images",
        "record.summary.container_id == resolved_id": "parent",
        "record.summary.container_id == work_package_id": "parent",
        "record.summary.container_type == 'WorkPackage'": "parent",
        "remaining <= 0": "include_images",
    },
    ("list_work_packages", "WorkPackageService.list"): {
        "skipped < skip_count": "paging",
        "value != []": "presence",
    },
    ("search_work_packages", "WorkPackageService.search"): {
        "skipped < skip_count": "paging",
        "value != []": "presence",
    },
}


def test_every_client_side_comparison_is_written_down_with_what_it_decides() -> None:
    found = {(tool, label): set(compares) for tool, label, compares in _read_sites()}

    assert set(found) == set(CLIENT_SITES), (
        sorted(set(found) - set(CLIENT_SITES)),
        sorted(set(CLIENT_SITES) - set(found)),
    )
    for key, written in CLIENT_SITES.items():
        assert found[key] == set(written), (key, sorted(found[key] - set(written)), sorted(set(written) - found[key]))
        for comparison, decides in written.items():
            assert decides in KINDS or (key[0], decides) in EXPECTED, (key, comparison, decides)


# A read tool that calls a client method of its own and no service: its parameters are classified above, and no
# list is filtered in the tool.
FLAT_READ_TOOLS: dict[str, str] = {
    "get_my_project_access": "reads one project's access: the project is the record",
    "get_project_work_package_context": "composes the options of one project; its versions come through a service "
    "method that takes the project as a container",
}


def test_a_read_tool_without_a_service_call_is_written_down() -> None:
    flat = {tool for tool in READ_TOOLS if not _service_methods(tool)}

    assert flat == set(FLAT_READ_TOOLS)


def test_an_own_policy_parameter_is_one_the_policy_knows() -> None:
    """The label `own policy` takes a parameter out of the census, so the policy must really cover it."""
    covered = {
        "list_work_packages": set(WORK_PACKAGE_FILTERS) | {"sort_by", "group_by", "include_sums"},
        "search_work_packages": set(WORK_PACKAGE_FILTERS) | {"sort_by", "group_by", "include_sums"},
        "list_projects": set(PROJECT_FILTERS) | {"sort_by"},
        # Aggregates the service masks itself; their own tests are `test_app_time_entry_service` and
        # `test_app_attachment_service`.
        "list_time_entries": {"include_total_hours"},
        "list_work_package_attachments": {"include_total_size"},
    }

    for tool, parameters in OWN_POLICY.items():
        assert set(parameters) <= covered[tool], (tool, sorted(set(parameters) - covered[tool]))


_PLANTED_MODULE = """
def _matches(record, text):
    return text in record.name.casefold()

class Service:
    async def list_things(self, *, search=None):
        rows = await self._api.list()
        return [row for row in rows if self._allowed(row) and _matches(row, search)]

    async def list_lambda(self, *, search=None):
        return await scan_records_and_paginate(item_allowed=lambda record: record.name == search)

    async def list_nested(self, *, search=None):
        def keep(record):
            return self._helper(record, search)
        return await scan_and_paginate(item_allowed=keep)

    def _helper(self, record, text):
        return record.title.lower().startswith(text) or record.state != text

    async def list_presence(self, *, project=None):
        rows = [row for row in await self._api.list() if row is not None and len(row) > 1]
        return rows

    async def list_variable(self, *, search=None):
        allowed = lambda record: record.name == search
        return await scan_records_and_paginate(item_allowed=allowed)

    async def list_partial(self, *, search=None):
        return await scan_records_and_paginate(item_allowed=functools.partial(self._helper, text=search))

    async def list_loop(self, *, search=None):
        kept = []
        for row in await self._api.list():
            if row.name != search:
                continue
            kept.append(row)
        return kept

    async def list_filter_call(self, *, search=None):
        return list(filter(lambda row: row.name.endswith(search), await self._api.list()))

    async def list_inner_helper(self, *, search=None):
        return await fetch_version_page(item_allowed=lambda record: _outer(record, search))

def _outer(record, text):
    def inner(row):
        return row.title == text
    return [r for r in record.rows if inner(r)]
"""


def _planted(method: str) -> list[str]:
    module = ast.parse(_PLANTED_MODULE)
    owner = next(n for n in module.body if isinstance(n, ast.ClassDef))
    definition = next(n for n in owner.body if getattr(n, "name", "") == method)
    return counted_comparisons(definition, module, owner)


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("list_things", ["text in record.name.casefold()"]),
        ("list_lambda", ["record.name == search"]),
        ("list_nested", ["record.state != text", "record.title.lower().startswith(text)"]),
        ("list_presence", []),
        ("list_variable", ["record.name == search"]),
        ("list_partial", ["record.state != text", "record.title.lower().startswith(text)"]),
        ("list_loop", ["row.name != search"]),
        ("list_filter_call", ["row.name.endswith(search)"]),
        ("list_inner_helper", ["row.title == text"]),
    ],
)
def test_the_census_finds_each_planted_shape_of_a_client_side_filter(method: str, expected: list[str]) -> None:
    assert _planted(method) == expected


def test_a_site_that_is_not_in_the_written_table_is_reported() -> None:
    planted = {("list_planets", "PlanetService.list")}

    assert planted - set(CLIENT_SITES) == planted


def test_the_mechanisms_are_the_functions_of_the_pagination_module_that_take_a_list_or_a_callback() -> None:
    assert MECHANISMS == {
        "fetch_bounded_and_paginate",
        "scan_and_paginate",
        "scan_records_and_paginate",
        "paginate_client",
        "paginate_all",
        "_fetch_all_pages",
    }
