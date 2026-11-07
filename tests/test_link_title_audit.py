"""Every link whose title an adapter reads is classified.

A link title is the name or subject of what the link points to, and a link can point into a
project the read allowlist does not cover. An adapter that starts reading a new link's title
fails this test until the link is classified here with the reason it is safe, so the question is
asked once per link and not after a leak.
"""

from __future__ import annotations

import ast

import pytest
from _source_scan import ADAPTERS, constant_key_reads, matching_nodes, reads_key

_INSTANCE_WIDE = "the resource is seen alike by every user of the instance"
_ANCHOR = "the project the record itself belongs to, which the service checks"
_CHECKED = "the service checks the project of this record or of its other end before it is returned"
_REDUCED = "the service or the adapter reduces it for projects the read scope does not cover"

# link name (camelCase, `_link` suffix removed) -> why reading its title is safe
CLASSIFIED: dict[str, str] = {
    "activity": _INSTANCE_WIDE,
    "assignee": _INSTANCE_WIDE,
    "authSource": _INSTANCE_WIDE,
    "author": _INSTANCE_WIDE,
    "category": _ANCHOR,
    "costType": _INSTANCE_WIDE,
    "defaultAssignee": _INSTANCE_WIDE,
    "definingProject": _CHECKED + " (version policy, per record)",
    "filter": _INSTANCE_WIDE + " (the filter's own name)",
    "githubUser": _INSTANCE_WIDE,
    "gitlabUser": _INSTANCE_WIDE,
    "mergedBy": _INSTANCE_WIDE,
    "operator": _INSTANCE_WIDE,
    "parent": _REDUCED + " (project parent)",
    "phaseDefinition": _INSTANCE_WIDE,
    "presenter": _INSTANCE_WIDE,
    "principal": _INSTANCE_WIDE,
    "priority": _INSTANCE_WIDE,
    "project": _ANCHOR,
    "projectPhase": _ANCHOR,
    "provider": _INSTANCE_WIDE,
    "query": _CHECKED + " (view: its project)",
    "responsible": _INSTANCE_WIDE,
    "self": _INSTANCE_WIDE,
    "status": _INSTANCE_WIDE,
    "storage": _INSTANCE_WIDE,
    "type": _INSTANCE_WIDE,
    "user": _INSTANCE_WIDE,
    "workspace": _CHECKED + " (sprint and backlog bucket policy, per record)",
    "entity": _CHECKED + " (the entity sits in the record's project)",
    "resource": _CHECKED + " (the notification's own project)",
    "from": _CHECKED + " (both relation ends)",
    "to": _CHECKED + " (both relation ends)",
    "column": _INSTANCE_WIDE,
    "context": _CHECKED + " (capability lists are filtered by project)",
}

# `_link_title(<loop variable>)`: the list of links is named where it is read ("file:function")
LOOPS_OVER_LINKS: dict[str, str] = {
    "httpx_time_entry_api.py:normalize_time_entry_activity_raw": _REDUCED + " (activity projects, in the service)",
    "httpx_time_entry_api.py:project_link_title_and_id": "one project link of a time entry, checked per record",
    "httpx_board_api.py:_normalize_query_link_label": _INSTANCE_WIDE + " (the column, group and sort names of a query)",
}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _link_name(argument: ast.expr) -> str | None:
    """The link a `_link_title(...)` argument reads: a string key, or the name of a `<name>_link`
    variable. None for any other spelling."""
    if isinstance(argument, ast.Name):
        return _camel(argument.id.removesuffix("_link")) if argument.id.endswith("_link") else None
    node: ast.expr | None = argument
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def _titled_links(source: str | None = None) -> tuple[dict[str, set[str]], dict[str, int]]:
    """(link name -> files, "file:function" -> line) of every `_link_title(...)` call, the second
    for the calls that pass a loop variable and so cannot be named. Scans the adapters, or the
    given source text when a test plants one."""
    named: dict[str, set[str]] = {}
    unnamed: dict[str, int] = {}
    sources = (
        {"planted.py": source} if source is not None else {p.name: p.read_text() for p in sorted(ADAPTERS.glob("*.py"))}
    )
    for file_name, text in sources.items():
        for function in ast.walk(ast.parse(text)):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if called not in ("_link_title", "link_title"):
                    continue
                name = _link_name(node.args[0])
                if name is None:
                    unnamed.setdefault(f"{file_name}:{function.name}", node.lineno)
                else:
                    named.setdefault(name, set()).add(file_name)
    return named, unnamed


# `payload.get("title")`, `["title"]` and the display id reads that are not a `_link_title` call:
# "file:function" -> why reading it is safe
_OWN = "the record's own title, not a link"
_INSTANCE = "names a resource every user of the instance sees alike"
_REDUCED_BY_SERVICE = "the service leaves it out for a project the read scope does not cover"
OTHER_TITLE_READS: dict[str, str] = {
    "httpx_backlog_bucket_api.py:_defining_workspace_link": "the defining project, checked per record by the policy",
    "httpx_sprint_api.py:_defining_workspace_link": "the defining project, checked per record by the policy",
    "httpx_board_api.py:_normalize_filter_values": "reduced to the href unless the filter is on a resource everyone sees alike",
    "httpx_document_api.py:normalize_document": _OWN,
    "httpx_emoji_reaction_api.py:normalize_emoji_reaction": _INSTANCE + " (a user)",
    "httpx_github_gitlab_link_api.py:normalize_github_pull_request_raw": _OWN,
    "httpx_github_gitlab_link_api.py:normalize_gitlab_issue_raw": _OWN,
    "httpx_github_gitlab_link_api.py:normalize_gitlab_merge_request_raw": _OWN,
    "httpx_meeting_agenda_item_api.py:normalize_meeting_agenda_item": _OWN,
    "httpx_meeting_api.py:normalize_meeting": _OWN,
    "httpx_meeting_section_api.py:normalize_meeting_section": _OWN,
    "httpx_membership_api.py:normalize_membership": _INSTANCE + " (a user, group or role)",
    "httpx_news_api.py:normalize_news": _OWN,
    "httpx_project_api.py:normalize_project_detail": _REDUCED_BY_SERVICE + " (ancestors)",
    "httpx_project_api.py:normalize_option_value": "an allowed value; versions of an uncovered project are left out by the work package context and the admin context",
    "httpx_project_api.py:normalize_project_field_schema": "an allowed value; see normalize_option_value",
    "httpx_project_storage_api.py:normalize_project_storage_detail": _INSTANCE + " (a storage)",
    "httpx_query_metadata_api.py:normalize_query_filter": _INSTANCE + " (a filter name)",
    "httpx_query_metadata_api.py:normalize_query_column": _INSTANCE + " (a column name)",
    "httpx_query_metadata_api.py:normalize_query_operator": _INSTANCE + " (an operator name)",
    "httpx_query_metadata_api.py:normalize_query_sort_by": _INSTANCE + " (a sort option)",
    "httpx_recurring_meeting_api.py:normalize_recurring_meeting": _OWN,
    "httpx_recurring_meeting_api.py:_record": _OWN,
    "httpx_user_non_working_time_api.py:normalize_user_non_working_time": _OWN,
    "httpx_user_working_hours_api.py:normalize_user_working_hours": _OWN,
    "httpx_wiki_page_api.py:normalize_wiki_page": _OWN,
    "httpx_work_package_picker_api.py:normalize_relation_candidate": "the service keeps a candidate only when the read scope covers its project",
    "_custom_fields.py:link_title_with_meta": "the helper behind the scoped custom field titles; every caller passes a link already judged",
    "httpx_work_package_api.py:normalize_work_package_summary": _REDUCED_BY_SERVICE + " (the parent's display id)",
    "httpx_work_package_api.py:normalize_work_package_detail": _REDUCED_BY_SERVICE
    + " (children, ancestors and parent)",
    "_text.py:link_title": "the helper itself; every call is classified by link name above",
}


def _other_title_reads() -> dict[str, int]:
    return constant_key_reads(("title", "displayId", "display_id"))


def test_every_other_read_of_a_title_or_display_id_is_classified() -> None:
    found = _other_title_reads()

    assert len(found) >= 20, "the scan found too few title reads to be reading the adapters"
    unclassified = {name: line for name, line in found.items() if name not in OTHER_TITLE_READS}
    assert unclassified == {}, "classify these functions in OTHER_TITLE_READS with the reason the read is safe"


def test_no_other_title_read_classification_outlives_the_read() -> None:
    assert sorted(set(OTHER_TITLE_READS) - set(_other_title_reads())) == []


def test_every_link_whose_title_an_adapter_reads_is_classified() -> None:
    found, unnamed = _titled_links()

    assert len(found) > 25, "the scan found too few links to be reading the adapters"
    unclassified = {name: sorted(files) for name, files in found.items() if name not in CLASSIFIED}
    assert unclassified == {}, "classify these links in CLASSIFIED with the reason their title is safe"
    assert {k: v for k, v in unnamed.items() if k not in LOOPS_OVER_LINKS} == {}, "classify these in LOOPS_OVER_LINKS"


def test_no_classification_outlives_the_link_it_describes() -> None:
    named, unnamed = _titled_links()

    assert sorted(set(CLASSIFIED) - set(named)) == []
    assert sorted(set(LOOPS_OVER_LINKS) - set(unnamed)) == []


@pytest.mark.parametrize(
    ("source", "name"),
    [
        ('_link_title(links.get("parent"))', "parent"),
        ('link_title(payload["_links"]["version"])', "version"),
        ("_link_title(project_link)", "project"),
        ("_link_title(default_assignee_link)", "defaultAssignee"),
    ],
)
def test_the_scan_names_the_link_in_every_spelling_the_adapters_use(source: str, name: str) -> None:
    call = ast.parse(source).body[0].value  # type: ignore[attr-defined]

    assert _link_name(call.args[0]) == name


def test_the_scan_refuses_a_spelling_it_cannot_name() -> None:
    call = ast.parse("_link_title(links.get(key))").body[0].value  # type: ignore[attr-defined]

    assert _link_name(call.args[0]) is None


# The links of a work package whose resource is defined in a project: a title reaches a result only
# through the helpers that keep it for a reference the service judged visible.
WORK_PACKAGE_ADAPTER = "httpx_work_package_api.py"
CUSTOM_FIELDS_MODULE = "_custom_fields.py"
UNBOUND_WORK_PACKAGE_LINKS = {
    "type",
    "status",
    "priority",
    "projectPhase",
    "assignee",
    "responsible",
    "project",
    "author",
    "category",
}
# "file:function" -> how many `["title"]`/`.get("title")` reads the function holds, and why
WORK_PACKAGE_TITLE_READS = {
    f"{CUSTOM_FIELDS_MODULE}:link_title_with_meta": 1,
    f"{WORK_PACKAGE_ADAPTER}:normalize_work_package_summary": 1,  # counts the titled target version links
    f"{WORK_PACKAGE_ADAPTER}:normalize_work_package_detail": 2,  # children and ancestors, reduced by the service
}


def _bound_links_read_plainly(source: str | None = None) -> set[str]:
    named, _ = _titled_links(source)
    return {
        name
        for name, files in named.items()
        if WORK_PACKAGE_ADAPTER in files or CUSTOM_FIELDS_MODULE in files or "planted.py" in files
    } - (UNBOUND_WORK_PACKAGE_LINKS)


def test_the_work_package_adapter_reads_a_link_with_a_defining_project_only_through_the_scoped_helpers() -> None:
    assert _bound_links_read_plainly() == set()


@pytest.mark.parametrize(
    "source",
    [
        '_link_title(links.get("sprint"))',
        '_link_title(links.get("version"))',
        '_link_title(links["targetVersions"])',
        "_link_title(observed_in_versions_link)",
    ],
)
def test_a_plain_title_read_of_a_version_or_sprint_link_is_found(source: str) -> None:
    assert _bound_links_read_plainly(f"def normalize(links):\n    return {source}\n") != set()


def _work_package_title_reads(source: str | None = None) -> dict[str, int]:
    nodes = matching_nodes(reads_key(("title",)), source=source) if source else matching_nodes(reads_key(("title",)))
    return {
        name: len(found)
        for name, found in nodes.items()
        if name.startswith((WORK_PACKAGE_ADAPTER, CUSTOM_FIELDS_MODULE)) or source
    }


def test_the_work_package_adapter_holds_no_title_read_besides_the_known_ones() -> None:
    assert _work_package_title_reads() == WORK_PACKAGE_TITLE_READS


@pytest.mark.parametrize(
    "read", ['links.get("sprint", {}).get("title")', 'links["sprint"]["title"]', 'link.get("title")']
)
def test_a_title_read_in_a_function_is_counted(read: str) -> None:
    planted = f"def normalize(links, link):\n    return {read}\n"

    assert _work_package_title_reads(planted) == {"planted.py:normalize": 1}


# Links the server renders with an href only, whatever the link's role: reading their title yields
# nothing. "file" -> link names. Verified against the representers of 16.0 to 17.9.
TITLELESS_BY_THE_SERVER = {"httpx_activity_api.py": {"user"}}


def test_no_adapter_reads_the_title_of_a_link_the_server_renders_without_one() -> None:
    named, _ = _titled_links()

    offenders = {
        (file, link) for link, files in named.items() for file in files if link in TITLELESS_BY_THE_SERVER.get(file, ())
    }
    assert offenders == set()


def test_a_title_read_of_a_titleless_link_is_found() -> None:
    named, _ = _titled_links('def normalize(links):\n    return _link_title(links.get("user"))\n')

    assert named == {"user": {"planted.py"}}
