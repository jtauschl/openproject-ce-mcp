"""What every tool definition tells an agent: shared parameters carry their shared
meaning, the fully described tools describe every parameter, descriptions keep
the claims the changelog promises, and no description is filler that only
restates a name."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import re
import typing
from pathlib import Path

import pytest

from openproject_ce_mcp import tool_params
from openproject_ce_mcp.app.errors import OpenProjectError
from openproject_ce_mcp.config import TOOL_GROUPS, Settings
from openproject_ce_mcp.models import VersionSummary, WorkPackageDetail, WorkPackageWriteResult
from openproject_ce_mcp.server import create_app

SRC = Path(__file__).resolve().parents[1] / "src" / "openproject_ce_mcp"

# Writes that process a list of items one by one and keep the items written
# before a failure, so their confirm parameter has to say so.
PER_ITEM_WRITES = {
    "bulk_create_work_packages",  # tools_work_packages.py: items are created one by one
    "bulk_update_work_packages",  # tools_work_packages.py: items are updated one by one
}

# Tools whose limit does not page: it bounds a single listing, so it has its
# own description and there is no offset next to it.
LIMIT_EXCEPTIONS = {
    "list_work_package_activities",
    "list_recurring_meeting_occurrences",
    "list_work_package_available_relation_candidates",
}

# Tools whose parameters all carry a description: the ones whose descriptions
# were thinnest, plus tools added since.
FULLY_DESCRIBED_TOOLS = {
    "copy_project",
    "create_board",
    "create_container_attachment",
    "create_grid",
    "create_group",
    "create_meeting_agenda_item",
    "create_membership",
    "create_news",
    "create_project",
    "create_recurring_meeting",
    "create_user",
    "create_version",
    "create_work_package_attachment",
    "delete_attachment",
    "delete_board",
    "delete_file_link",
    "delete_group",
    "delete_membership",
    "delete_news",
    "delete_project",
    "delete_relation",
    "delete_time_entry",
    "delete_user",
    "delete_version",
    "end_recurring_meeting",
    "get_group",
    "get_meeting",
    "get_meeting_agenda_item",
    "get_meeting_section",
    "get_membership",
    "get_project_configuration",
    "get_query_filter",
    "get_query_sort_by",
    "get_user_working_hours",
    "list_categories",
    "list_notifications",
    "list_work_package_file_links",
    "list_work_package_reactions",
    "set_project_favorite",
    "set_user_locked",
    "update_board",
    "update_document",
    "update_grid",
    "update_group",
    "update_meeting",
    "update_meeting_agenda_item",
    "update_meeting_section",
    "update_membership",
    "update_my_preferences",
    "update_news",
    "update_project",
    "update_reminder",
    "update_storage",
    "update_user",
    "update_user_working_hours",
    "update_version",
    "update_work_package_comment",
}

# Claims a changelog entry promises for a tool's definition. Location None is
# the tool description, otherwise the named parameter's schema description.
# Whitespace is normalized on both sides, so rewording around a phrase stays free.
_IRREVERSIBLE = (None, "cannot be undone")
PROMISED_CLAIMS: dict[str, list[tuple[str | None, str]]] = {
    "get_project": [("project", "a unique part of a name or identifier also matches")],
    "set_project_favorite": [("project", "a unique part of a name or identifier also matches")],
    "list_sprints": [("project", "a unique part of a name or identifier also matches"), (None, "17.3")],
    "get_sprint": [(None, "17.3")],
    "get_meeting_agenda_item": [(None, "Requires OpenProject 17.6+")],
    "create_meeting": [
        (None, "so passing either is rejected"),
        ("participant_user_refs", "exactly these participants"),
    ],
    "update_meeting": [("participant_user_refs", "Change the participants in OpenProject")],
    "create_meeting_agenda_item": [(None, "Requires OpenProject 17.6+")],
    "update_meeting_agenda_item": [(None, "Requires OpenProject 17.6+")],
    "delete_meeting_agenda_item": [(None, "Requires OpenProject 17.6+"), _IRREVERSIBLE],
    "get_meeting_section": [(None, "Requires OpenProject 17.6+")],
    "create_meeting_section": [(None, "Requires OpenProject 17.6+")],
    "update_meeting_section": [(None, "Requires OpenProject 17.6+")],
    "delete_meeting_section": [(None, "Requires OpenProject 17.6+"), _IRREVERSIBLE],
    "list_work_package_meeting_agenda_items": [(None, "Requires OpenProject 17.7+")],
    "update_recurring_meeting": [
        (None, "Already created future occurrences move"),
        (None, "can delete cancelled occurrences"),
    ],
    "cancel_recurring_meeting_occurrence": [(None, "init_recurring_meeting_occurrence restores it")],
    "init_recurring_meeting_occurrence": [(None, "17.4 and 17.5")],
    "create_storage": [(None, "only the values of provider_type and authentication_method are pre-checked here")],
    "delete_storage": [(None, "also tries to delete that project folder"), _IRREVERSIBLE],
    "update_user_non_working_time": [(None, "the preview does not look it up")],
    "set_work_package_watcher": [(None, "previews are NOT symmetric")],
    "list_work_packages": [
        (None, "It requires OpenProject 16.4"),
        (None, "observed_in_version filters by a version a bug was observed in"),
        (None, "OpenProject 17.9+, rejected by older servers"),
    ],
    "list_work_package_wiki_links": [(None, "Requires OpenProject 17.5+"), (None, "Known OpenProject server bug")],
    "create_work_package_wiki_link": [(None, "Requires OpenProject 17.7+")],
    "delete_work_package_wiki_link": [
        (None, "Requires OpenProject 17.6+"),
        (None, "fails with an [OPENPROJECT_UNAVAILABLE] whenever list_work_package_wiki_links does"),
        (None, "Only relation links"),
        (None, '"Manage wiki page links" permission'),
        _IRREVERSIBLE,
    ],
    "bulk_create_work_packages": [
        (None, "These are write-result fields"),
        (None, "selected as result.<field>"),
        (None, "observed_in_versions needs OpenProject 17.9+"),
    ],
    "bulk_update_work_packages": [
        (None, "select names write-result fields"),
        (None, "selected as result.<field>"),
        (None, "observed_in_versions needs OpenProject 17.9+"),
    ],
    "update_work_package_comment": [
        (None, "Editing may notify people"),
        (None, "no comment-version history or recovery"),
        (None, "notifications for this comment unread again"),
    ],
    "list_meetings": [("title", "Requires OpenProject 17.9+")],
    "end_recurring_meeting": [
        (None, "Requires OpenProject 17.8+"),
        (None, "deletes the already created future occurrences"),
        (None, "which a repeated call sends again"),
    ],
    "create_work_package": [(None, "observed_in_versions accepts"), (None, "OpenProject 17.9+")],
    "update_work_package": [(None, "observed_in_versions accepts"), (None, "OpenProject 17.9+")],
    "create_subtask": [(None, "observed_in_versions accepts"), (None, "OpenProject 17.9+")],
    "delete_meeting": [
        (None, "Deleting a one-time meeting cannot be undone"),
        (None, "init_recurring_meeting_occurrence restores it"),
        (None, "The template meeting of a recurring series is rejected"),
    ],
    "delete_file_link": [_IRREVERSIBLE, (None, "the file itself stays in the external storage")],
    "delete_attachment": [_IRREVERSIBLE],
    "delete_board": [_IRREVERSIBLE],
    "delete_grid": [_IRREVERSIBLE],
    "delete_group": [_IRREVERSIBLE],
    "delete_meeting_outcome": [_IRREVERSIBLE],
    "delete_membership": [_IRREVERSIBLE],
    "delete_news": [_IRREVERSIBLE],
    "delete_project": [_IRREVERSIBLE],
    "delete_recurring_meeting": [_IRREVERSIBLE],
    "delete_relation": [_IRREVERSIBLE],
    "delete_reminder": [_IRREVERSIBLE],
    "delete_time_entry": [_IRREVERSIBLE],
    "delete_user": [_IRREVERSIBLE],
    "delete_user_non_working_time": [_IRREVERSIBLE],
    "delete_user_working_hours": [_IRREVERSIBLE],
    "delete_version": [_IRREVERSIBLE],
    "delete_work_package": [_IRREVERSIBLE],
}

_TRACKER_ID = re.compile(r"\bOPM-\d+")


def _description(alias: object) -> str:
    return next(meta.description for meta in typing.get_args(alias)[1:] if getattr(meta, "description", None))


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict]:
    env = {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "token",
        "OPENPROJECT_READ_PROJECTS": "*",
        "OPENPROJECT_WRITE_PROJECTS": "*",
        "OPENPROJECT_ATTACHMENT_ROOT": str(tmp_path_factory.mktemp("attachments")),
        "OPENPROJECT_ENABLE_EXTENDED_READ": "true",
        "OPENPROJECT_ENABLE_METADATA_TOOLS": "true",
    }
    for group in TOOL_GROUPS:
        env[group.read_env_var] = "true"
        if group.write is not None:
            env[group.write.env_var] = "true"
    tools = asyncio.run(create_app(Settings.from_env(env)).list_tools())
    return {tool.name: tool.model_dump(by_alias=True, exclude_none=True, mode="json") for tool in tools}


def _properties(tool: dict) -> dict[str, dict]:
    return tool["inputSchema"].get("properties", {})


def test_every_confirm_states_the_preview_contract_of_its_tool(catalog: dict[str, dict]) -> None:
    expected = {
        name: _description(tool_params.BulkConfirm if name in PER_ITEM_WRITES else tool_params.Confirm)
        for name, tool in catalog.items()
        if "confirm" in _properties(tool)
    }

    actual = {name: _properties(catalog[name])["confirm"].get("description") for name in expected}

    assert actual == expected
    assert PER_ITEM_WRITES <= set(expected)


def test_shared_parameters_carry_their_shared_meaning(catalog: dict[str, dict]) -> None:
    shared = {
        "offset": _description(tool_params.Offset),
        "limit": _description(tool_params.Limit),
        "work_package_id": _description(tool_params.WorkPackageRef),
        "project": _description(tool_params.ProjectRef),
    }
    exceptions = {("limit", name) for name in LIMIT_EXCEPTIONS}

    mismatched = sorted(
        (param, name)
        for name, tool in catalog.items()
        for param, text in shared.items()
        if param in _properties(tool)
        and (param, name) not in exceptions
        and _properties(tool)[param].get("description") != text
    )

    assert mismatched == []


def test_a_limit_without_offset_is_a_documented_exception(catalog: dict[str, dict]) -> None:
    unpaged = {
        name for name, tool in catalog.items() if "limit" in _properties(tool) and "offset" not in _properties(tool)
    }
    shared_limit = _description(tool_params.Limit)

    assert unpaged == LIMIT_EXCEPTIONS
    for name in LIMIT_EXCEPTIONS:
        own = _properties(catalog[name])["limit"].get("description")
        assert own and own != shared_limit, name


def test_the_fully_described_tools_describe_every_parameter(catalog: dict[str, dict]) -> None:
    undescribed = sorted(
        f"{name}.{param}"
        for name in FULLY_DESCRIBED_TOOLS
        for param, schema in _properties(catalog[name]).items()
        if not schema.get("description")
    )

    assert undescribed == []


_TOOL_NAME_VERBS = "list|get|create|update|delete|set|cancel|init|execute|mark|toggle|copy|search|render|bulk_create|bulk_update|end|add"
_TOOL_NAME_RE = re.compile(rf"\b(?:{_TOOL_NAME_VERBS})_[a-z][a-z_]*[a-z]\b")

# Descriptions that tell an agent a tool does not exist, so it does not look for one.
NAMED_AS_MISSING = {
    "get_gitlab_issue",
    "get_gitlab_merge_request",
    "list_cost_types",
    "list_forums",
    "list_posts",
}


def _all_texts(tool: dict) -> list[str]:
    return [tool.get("description", ""), *_schema_descriptions(tool.get("inputSchema"))]


def test_no_em_dash_reaches_the_wire(catalog: dict[str, dict]) -> None:
    with_dash = sorted(name for name, tool in catalog.items() if any("\u2014" in text for text in _all_texts(tool)))

    assert with_dash == []


def test_no_em_dash_in_the_server_instructions() -> None:
    from openproject_ce_mcp.server import CE_INSTRUCTIONS

    assert "\u2014" not in CE_INSTRUCTIONS


def test_descriptions_name_only_tools_that_exist(catalog: dict[str, dict]) -> None:
    parameters = {param for tool in catalog.values() for param in _properties(tool)}
    unknown = sorted(
        f"{name}: {ref}"
        for name, tool in catalog.items()
        for text in _all_texts(tool)
        for ref in set(_TOOL_NAME_RE.findall(text))
        if ref not in catalog and ref not in parameters and ref not in NAMED_AS_MISSING
    )

    assert unknown == []


def _error_classes(base: type[OpenProjectError]) -> list[type[OpenProjectError]]:
    return [base, *(cls for sub in base.__subclasses__() for cls in _error_classes(sub))]


def test_descriptions_name_only_error_codes_the_server_returns(catalog: dict[str, dict]) -> None:
    returned = {cls.code for cls in _error_classes(OpenProjectError)} | {"INTERNAL_ERROR"}
    cited = {
        code
        for tool in catalog.values()
        for text in _all_texts(tool)
        for code in re.findall(r"\[([A-Za-z_]{3,})\]", text)
    }

    assert cited
    assert cited <= returned


def _normalized(text: str) -> str:
    return " ".join(text.split())


def test_descriptions_keep_their_promised_claims(catalog: dict[str, dict]) -> None:
    missing = []
    for name, claims in PROMISED_CLAIMS.items():
        for location, phrase in claims:
            source = (
                catalog[name].get("description", "")
                if location is None
                else (_properties(catalog[name])[location].get("description", ""))
            )
            if _normalized(phrase) not in _normalized(source):
                missing.append((name, location, phrase))

    assert missing == []


def test_every_delete_tool_says_whether_it_can_be_undone() -> None:
    delete_tools = {name for name in PROMISED_CLAIMS if name.startswith("delete_")}
    claimed = {
        name for name, claims in PROMISED_CLAIMS.items() if any("cannot be undone" in phrase for _, phrase in claims)
    }

    assert delete_tools == claimed


def test_the_catalog_has_no_unlisted_delete_tool(catalog: dict[str, dict]) -> None:
    assert {name for name in catalog if name.startswith("delete_")} == {
        name for name in PROMISED_CLAIMS if name.startswith("delete_")
    }


def _schema_descriptions(schema: object) -> typing.Iterator[str]:
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "description" and isinstance(value, str):
                yield value
            else:
                yield from _schema_descriptions(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _schema_descriptions(item)


def test_no_tracker_id_reaches_the_wire(catalog: dict[str, dict]) -> None:
    found = sorted(
        name
        for name, tool in catalog.items()
        for text in (
            tool.get("description", ""),
            *_schema_descriptions(tool["inputSchema"]),
        )
        if _TRACKER_ID.search(text)
    )

    assert found == []


def _words(text: str) -> str:
    return " ".join(w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w != "the")


def test_no_parameter_description_only_restates_its_name(catalog: dict[str, dict]) -> None:
    restating = sorted(
        f"{name}.{param}"
        for name, tool in catalog.items()
        for param, schema in _properties(tool).items()
        if "description" in schema and _words(schema["description"]) in {_words(param), _words(schema.get("title", ""))}
    )

    assert restating == []


def test_no_write_tool_opens_with_prepare(catalog: dict[str, dict]) -> None:
    assert [name for name, tool in catalog.items() if tool.get("description", "").startswith("Prepare or")] == []


def _select_call(call: ast.Call, *, positional: tuple[str, ...]) -> dict[str, str]:
    named = dict(zip(positional, (ast.unparse(arg) for arg in call.args), strict=False))
    named.update({kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg is not None})
    return named


def _select_sources() -> dict[str, tuple[dict[str, str] | None, dict[str, str] | None]]:
    """Per tool: the arguments, by name, of its select schema and of the validator its body calls."""
    found: dict[str, tuple[dict[str, str] | None, dict[str, str] | None]] = {}
    for path in SRC.glob("tools_*.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            select = next((arg for arg in node.args.args + node.args.kwonlyargs if arg.arg == "select"), None)
            if select is None:
                continue
            schema = next(
                (
                    _select_call(call, positional=("row_type",))
                    for call in ast.walk(select.annotation)
                    if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "select_field"
                ),
                None,
            )
            validated = next(
                (
                    _select_call(call, positional=("select", "row_type"))
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_validate_select"
                ),
                None,
            )
            if validated is not None:
                validated.pop("select", None)
            found[node.name] = (schema, validated)
    return found


def test_select_schema_names_the_fields_its_validator_accepts() -> None:
    sources = _select_sources()

    assert len(sources) >= 30
    assert {name: pair for name, pair in sources.items() if pair[0] != pair[1]} == {}


def _field_names(row_type: type) -> set[str]:
    return {field.name for field in dataclasses.fields(row_type)}


def _allowed_lists(description: str) -> list[str]:
    return description.rsplit("Allowed: ", 1)[1].removesuffix(".").split("; ")


def test_select_description_lists_the_complete_allowed_set(catalog: dict[str, dict]) -> None:
    (plain,) = _allowed_lists(_properties(catalog["list_versions"])["select"]["description"])

    assert set(plain.split(", ")) == _field_names(VersionSummary)


@pytest.mark.parametrize("tool", sorted(PER_ITEM_WRITES))
def test_bulk_select_description_lists_top_level_and_nested_fields(catalog: dict[str, dict], tool: str) -> None:
    top_level, nested = _allowed_lists(_properties(catalog[tool])["select"]["description"])
    prefix, nested_fields = nested.split(" for ", 1)

    unfilled = {"parent_target"} if tool == "bulk_create_work_packages" else set()
    assert set(top_level.split(", ")) == _field_names(WorkPackageWriteResult) - unfilled | {"index", "success", "error"}
    assert prefix == "result.<field>"
    assert set(nested_fields.split(", ")) == _field_names(WorkPackageDetail)
