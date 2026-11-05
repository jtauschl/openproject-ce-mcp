"""The closest-name hint of a rejected unknown argument.

The expected texts are exact: the hint is the only thing a caller reads before its retry.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp import types
from test_tool_contract_snapshot import _all_scopes_enabled_settings, _live_catalog

from openproject_ce_mcp.argument_hint import suggest_argument
from openproject_ce_mcp.server import create_app


async def _dispatch(mcp: Any, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    params = types.CallToolRequestParams(name=name, arguments=arguments)
    entry = mcp._lowlevel_server.get_request_handler("tools/call")
    assert entry is not None
    return await entry.handler(None, params)


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


@pytest.fixture(scope="module")
def live_tools() -> dict[str, Any]:
    return _live_catalog()


def _suggest(tools: dict[str, Any], tool: str, name: str) -> str | None:
    schema = tools[tool].input_schema
    return suggest_argument(name, set(schema["properties"]), schema.get("required", []))


@pytest.mark.parametrize(
    ("tool", "name", "expected"),
    [
        pytest.param("get_work_package", "id", "work_package_id", id="id-one-required-id"),
        pytest.param("update_work_package", "id", "work_package_id", id="id-ignores-expect-display-id"),
        pytest.param("get_version", "id", "version_id", id="id-version"),
        pytest.param("create_work_package", "id", None, id="id-no-required-id"),
        pytest.param("list_time_entries", "id", None, id="id-only-optional-id-is-a-filter"),
        pytest.param("create_time_entry", "id", None, id="id-optional-id-beside-required-others"),
        pytest.param("update_work_package", "display_id", None, id="display-id-is-not-a-typo-of-the-guard"),
        pytest.param("get_project_storage", "project_id", None, id="project-id-never-lands-on-project-storage-id"),
        pytest.param("update_group", "user_ids", None, id="plural-never-lands-on-add-user-ids"),
        pytest.param("create_work_package", "parent_id", "parent", id="entity-id-rule-for-parent"),
        pytest.param("create_version", "parent", None, id="different-word-is-no-typo-of-project"),
        pytest.param("list_projects", "section", None, id="different-word-is-no-typo-of-select"),
        pytest.param("create_work_package_relation", "id", None, id="id-two-required-ids-relation"),
        pytest.param("set_work_package_watcher", "id", None, id="id-two-required-ids-watcher"),
        pytest.param("delete_work_package_wiki_link", "id", None, id="id-two-required-ids-wiki-link"),
        pytest.param("get_work_packages", "ids", "work_package_ids", id="ids-one-list"),
        pytest.param("create_group", "ids", "user_ids", id="ids-create-group"),
        pytest.param("update_group", "ids", None, id="ids-two-lists"),
        pytest.param("get_work_package", "ids", None, id="ids-no-list"),
        pytest.param("create_work_package", "project_id", "project", id="entity-id-to-entity"),
        pytest.param("search_work_packages", "project_id", "project", id="search-project-id"),
        pytest.param("search_work_packages", "query", "search", id="query-synonym"),
        pytest.param("search_work_packages", "text", "search", id="text-synonym"),
        pytest.param("execute_query", "query", None, id="synonym-target-missing-is-never-suggested"),
        pytest.param("get_work_package", "text", None, id="text-without-search"),
        pytest.param("search_work_packages", "exact_match", None, id="exact-match-is-a-result-field"),
        pytest.param("create_work_package", "subjct", "subject", id="typo"),
        pytest.param("get_work_package", "work_packge_id", "work_package_id", id="typo-in-id-stem"),
        pytest.param("delete_version", "confirmed", "confirm", id="typo-just-above-the-cutoff"),
        pytest.param("get_work_package", "nothing_alike_here", None, id="nothing-close"),
        pytest.param("list_sprints", "project_id", "project", id="project-id-rule-before-difflib"),
        pytest.param("get_sprint", "project_id", None, id="project-id-never-lands-on-another-id"),
        pytest.param("create_subtask", "work_package_ids", None, id="plural-never-lands-on-parent-id"),
    ],
)
def test_the_suggestion_for_an_unknown_name(
    live_tools: dict[str, Any], tool: str, name: str, expected: str | None
) -> None:
    assert _suggest(live_tools, tool, name) == expected


def test_a_suggestion_is_always_one_of_the_allowed_names(live_tools: dict[str, Any]) -> None:
    probes = [
        "id",
        "ids",
        "project_id",
        "query",
        "text",
        "exact_match",
        "work_package_ids",
        "subjct",
        "version_ids",
        "parent",
        "section",
    ]
    for tool, definition in live_tools.items():
        schema = definition.input_schema
        allowed = set(schema["properties"])
        for name in probes:
            suggestion = suggest_argument(name, allowed, schema.get("required", []))
            assert suggestion is None or suggestion in allowed, (tool, name, suggestion)


_ODD_NAMES = ["", "_id", "_ids", "id ", " id", "a b", "x\ny", "ID", "Id", "ids\n", "é_id", "a" * 100_000]


def test_odd_names_get_no_hint_and_never_raise(live_tools: dict[str, Any]) -> None:
    for tool, definition in live_tools.items():
        schema = definition.input_schema
        allowed = set(schema["properties"])
        for name in _ODD_NAMES:
            suggestion = suggest_argument(name, allowed, schema.get("required", []))
            assert suggestion is None or suggestion in allowed, (tool, name[:20], suggestion)


# Words that mean something else on a tool must not be offered another tool argument. The pairs below are
# the only suggestions the catalog-wide audit of these probes produces; each is a plausible typo or the
# scheme's own counterpart.
_DIFFERENT_WORDS = [
    *("parent", "section", "duration", "sprint", "date", "start", "user", "task_id", "relation_id"),
    *("interval", "internal", "relation", "lang"),
]
_EXPECTED_PAIRS = {("parent_id", "parent"), ("section", "section_id"), ("sprint", "sprint_id"), ("user_id", "user")}
# Different words that sit at or above the 0.85 cutoff by letter overlap alone. None is a plausible call on
# its tool and the full allowed list follows the hint; lowering the cutoff would add more, raising it drops
# real typos such as `confirmed`, so the pairs are listed rather than special-cased.
_ACCEPTED_MISSES = {
    ("interval", "internal"),
    ("internal", "interval"),
    ("relation", "reaction"),
    ("lang", "lag"),
}


def test_a_different_word_is_not_offered_another_argument(live_tools: dict[str, Any]) -> None:
    pairs = set()
    for definition in live_tools.values():
        schema = definition.input_schema
        allowed = set(schema["properties"])
        for name in [*_DIFFERENT_WORDS, "parent_id", "user_id"]:
            if name in allowed:
                continue
            suggestion = suggest_argument(name, allowed, schema.get("required", []))
            if suggestion:
                pairs.add((name, suggestion))
    assert pairs <= _EXPECTED_PAIRS | _ACCEPTED_MISSES, pairs - _EXPECTED_PAIRS - _ACCEPTED_MISSES


def test_no_tool_names_a_plural_work_package_list_ids(live_tools: dict[str, Any]) -> None:
    offenders = [tool for tool, definition in live_tools.items() if "ids" in definition.input_schema["properties"]]
    assert offenders == []


def test_every_plural_id_argument_is_a_list(live_tools: dict[str, Any]) -> None:
    wrong = [
        f"{tool}.{name}"
        for tool, definition in live_tools.items()
        for name, schema in definition.input_schema["properties"].items()
        if name.endswith("_ids")
        and schema.get("type") != "array"
        and not any(option.get("type") == "array" for option in schema.get("anyOf", []))
    ]
    assert wrong == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "arguments", "unknown"),
    [
        pytest.param("get_work_package", {"id": "TST-1"}, "id (did you mean work_package_id?)", id="id"),
        pytest.param("get_work_packages", {"ids": [1]}, "ids (did you mean work_package_ids?)", id="ids"),
        pytest.param(
            "create_work_package",
            {"project_id": 1, "type": "Task", "subject": "s"},
            "project_id (did you mean project?)",
            id="project-id",
        ),
        pytest.param(
            "search_work_packages",
            {"query": "q", "project_id": "TST", "exact_match": True},
            "exact_match, project_id (did you mean project?), query (did you mean search?)",
            id="the-ticket-call",
        ),
        pytest.param("set_work_package_watcher", {"id": 1}, "id", id="ambiguous-id-stays-bare"),
    ],
)
async def test_the_rejection_names_the_closest_allowed_argument(
    tool: str, arguments: dict[str, Any], unknown: str
) -> None:
    mcp = create_app(_all_scopes_enabled_settings())

    result = await _dispatch(mcp, tool, arguments)

    assert result.is_error is True
    text = _text(result)
    prefix = f"[VALIDATION_FAILED] Unknown argument(s) for tool '{tool}': {unknown}. Allowed arguments: "
    assert text.startswith(prefix), text
    allowed = sorted(next(t for t in await mcp.list_tools() if t.name == tool).input_schema["properties"])
    assert text == prefix + ", ".join(allowed)


@pytest.mark.asyncio
async def test_a_rejected_call_sends_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    sent: list[httpx.Request] = []

    async def _record(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        sent.append(request)
        raise AssertionError("a rejected call must not reach the network")

    monkeypatch.setattr(httpx.AsyncClient, "send", _record)
    mcp = create_app(_all_scopes_enabled_settings())

    result = await _dispatch(mcp, "get_work_package", {"id": "TST-1"})

    assert result.is_error is True
    assert sent == []


def test_the_renamed_argument_is_required_and_the_old_one_is_gone(live_tools: dict[str, Any]) -> None:
    schema = live_tools["get_work_packages"].input_schema

    assert schema["required"] == ["work_package_ids"]
    assert "ids" not in schema["properties"]
