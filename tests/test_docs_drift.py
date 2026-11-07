"""User-facing docs state the tool-group facts the code defines, so a new group,
write flag or console command cannot leave them silently wrong."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from importlib.metadata import distribution
from pathlib import Path

import pytest

from openproject_ce_mcp.config import READ_SCOPE_ENV_VAR, TOOL_GROUPS
from openproject_ce_mcp.server import CE_INSTRUCTIONS, _build_parser
from openproject_ce_mcp.tools import (
    _PROJECT_SCOPED_READ_TOOLS,
    ADDITIONAL_READ_SCOPES_BY_TOOL,
    ATTACHMENT_UPLOAD_TOOLS,
    PERSONAL_MUTATION_TOOLS,
    READ_TOOLS_BY_SCOPE,
    WRITE_TOOLS_BY_SCOPE,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIGURATION = ROOT / "docs" / "configuration.md"
DOC_FILES = [ROOT / "README.md", ROOT / "SECURITY.md", *sorted((ROOT / "docs").glob("*.md"))]

_NUMBER = r"(?<![\w.])(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(?![\w.])"
# Counts of tool groups or group flags go stale with every new group; the docs
# name the groups instead.
_GROUP_COUNT = re.compile(
    "|".join(
        (
            rf"{_NUMBER}\s+(?:core\s+)?tool\s+groups?",
            rf"{_NUMBER}\s+core\s+(?:groups?|read|write)",
            rf"{_NUMBER}\s+(?:individual\s+|project-scoped\s+|core\s+)?(?:read|write)(?:-category)?\s+"
            r"(?:flags?|categor(?:y|ies)|booleans?)",
            rf"{_NUMBER}\s+individual\s+(?:\S+\s+)?(?:booleans?|flags?)",
            rf"{_NUMBER}\s+\S*default\S*\s+categor(?:y|ies)",
            r"\bcore-\d+",
        )
    ),
    re.IGNORECASE,
)


def _prose(path: Path) -> str:
    """The file's text without table rows, whitespace collapsed so a phrase may span lines."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("|")]
    return " ".join(" ".join(lines).split())


def _section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin : text.index(end, begin + len(start))]


@pytest.mark.parametrize(
    "sentence",
    [
        "Each of the 9 tool groups below",
        "the 6 core write-category flags",
        "via 10 individual booleans",
        "The 6 project-scoped write flags default",
        "The 6 core write categories are enabled",
        "the core-6 are",
        "the 5 read-default-`true` categories above",
        "the 9 individual `OPENPROJECT_ENABLE_<GROUP>_READ` flags",
        "The six core groups default",
    ],
)
def test_group_count_pattern_catches_counts(sentence: str) -> None:
    assert _GROUP_COUNT.search(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Three flags control what it does",
        "three MCP installation scopes",
        "the established one-scope-per-domain pattern",
        "3. **Fail-closed project scope**",
        "requires OpenProject 17.3+ for this scope",
        "The extended metadata group adds 12 rarely used tools",
    ],
)
def test_group_count_pattern_ignores_other_numbers(sentence: str) -> None:
    assert not _GROUP_COUNT.search(sentence)


@pytest.mark.parametrize("path", DOC_FILES, ids=lambda path: path.name)
def test_docs_name_groups_instead_of_counting_them(path: Path) -> None:
    assert [match.group(0) for match in _GROUP_COUNT.finditer(_prose(path))] == []


def test_configuration_tables_list_exactly_the_group_flags() -> None:
    documented = set(
        re.findall(
            r"^\| `(OPENPROJECT_ENABLE_\w+_(?:READ|WRITE))`", CONFIGURATION.read_text(encoding="utf-8"), re.MULTILINE
        )
    )
    expected = {group.read_env_var for group in TOOL_GROUPS}
    expected |= {group.write.env_var for group in TOOL_GROUPS if group.write is not None}

    assert documented == expected


def _classified_tools() -> set[str]:
    return (
        set(PERSONAL_MUTATION_TOOLS)
        | set(ATTACHMENT_UPLOAD_TOOLS)
        | {name for names in READ_TOOLS_BY_SCOPE.values() for name in names}
        | {name for names in WRITE_TOOLS_BY_SCOPE.values() for name in names}
    )


def _table_rows(header: str) -> list[list[str]]:
    text = CONFIGURATION.read_text(encoding="utf-8")
    table = text[text.index(header) :].split("\n\n", 1)[0].splitlines()[2:]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in table]


def _backticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def _duplicates(names: list[str]) -> list[str]:
    return sorted(name for name, count in Counter(names).items() if count > 1)


def _write_env_var(key: str) -> str:
    write = next(group.write for group in TOOL_GROUPS if group.key == key)
    assert write is not None
    return write.env_var


def test_tools_per_switch_lists_exactly_the_tools_each_switch_registers() -> None:
    rows = _table_rows("| Switch | Tools |")
    switches = [switch.strip("`") for switch, _ in rows]
    documented = {switch.strip("`"): _backticked(tools) for switch, tools in rows}

    expected: dict[str, list[str]] = {}
    for group in TOOL_GROUPS:
        expected[group.read_env_var] = [
            name for scope in group.read_scopes for name in READ_TOOLS_BY_SCOPE.get(scope, ())
        ]
        if group.write is not None:
            expected[group.write.env_var] = list(WRITE_TOOLS_BY_SCOPE.get(group.key, ()))
    expected[_write_env_var("personal")] += PERSONAL_MUTATION_TOOLS
    expected[_write_env_var("work_package")] += ATTACHMENT_UPLOAD_TOOLS

    assert _duplicates(switches) == []
    assert [tools for _, tools in rows if not re.fullmatch(r"`\w+`(?:, `\w+`)*", tools)] == []
    assert sorted({name for names in documented.values() for name in names} - _classified_tools()) == []
    assert {switch: _duplicates(names) for switch, names in documented.items() if _duplicates(names)} == {}
    assert {name for names in expected.values() for name in names} == _classified_tools()
    assert {switch: set(names) for switch, names in documented.items()} == {
        switch: set(names) for switch, names in expected.items()
    }


def test_configuration_lists_exactly_the_read_tools_registered_without_read_projects() -> None:
    sentence = _section(_prose(CONFIGURATION), "register only these project-independent tools:", ".")
    documented = _backticked(sentence)

    core_read_tools: set[str] = set()
    other_read_tools: set[str] = set()
    for group in TOOL_GROUPS:
        names = {name for scope in group.read_scopes for name in READ_TOOLS_BY_SCOPE.get(scope, ())}
        if group.write is not None and group.write.project_scoped:
            core_read_tools |= names
        else:
            other_read_tools |= names

    assert _duplicates(documented) == []
    assert set(documented) == core_read_tools - _PROJECT_SCOPED_READ_TOOLS
    assert sorted(other_read_tools & _PROJECT_SCOPED_READ_TOOLS) == []


def test_configuration_lists_exactly_the_tools_needing_another_setting() -> None:
    rows = _table_rows("| Tool | Also requires |")
    names = [name for tools, _ in rows for name in _backticked(tools)]
    documented = {name: set(_backticked(requires)) for tools, requires in rows for name in _backticked(tools)}

    # The server refuses a write flag without its read flag, so a group's own
    # read scope is never an extra requirement.
    home_read_scopes: dict[str, set[str]] = {}
    for group in TOOL_GROUPS:
        home_tools = [name for scope in group.read_scopes for name in READ_TOOLS_BY_SCOPE.get(scope, ())]
        for name in [*home_tools, *WRITE_TOOLS_BY_SCOPE.get(group.key, ())]:
            home_read_scopes[name] = set(group.read_scopes)
    expected = {
        name: {READ_SCOPE_ENV_VAR[scope] for scope in extra}
        for name, scopes in ADDITIONAL_READ_SCOPES_BY_TOOL.items()
        if (extra := scopes - home_read_scopes[name])
    }
    for name in ATTACHMENT_UPLOAD_TOOLS:
        expected[name] = {"OPENPROJECT_ATTACHMENT_ROOT"}

    assert _duplicates(names) == []
    assert sorted(set(names) - _classified_tools()) == []
    assert documented == expected


def test_configuration_names_every_opt_in_group_in_its_explanation() -> None:
    explanation = _section(
        " ".join(CONFIGURATION.read_text(encoding="utf-8").split()), "## Tool Groups", "| Variable |"
    )

    for group in TOOL_GROUPS:
        if not group.read_default:
            assert group.read_env_var in explanation, group.key


def test_security_names_every_opt_in_read_flag() -> None:
    security = _prose(ROOT / "SECURITY.md")

    for group in TOOL_GROUPS:
        if not group.read_default:
            short = group.read_env_var.removeprefix("OPENPROJECT_ENABLE")
            assert group.read_env_var in security or f"`{short}`" in security, group.key


def test_quick_mode_description_names_every_write_it_asks_and_leaves_alone() -> None:
    quick = _section(_prose(CONFIGURATION), "**`configure` / `configure --quick`**", "**`configure --advanced`**")
    asked = _section(quick, "write category (", "), mapped")

    for group in TOOL_GROUPS:
        if group.write is None:
            continue
        if group.write.project_scoped:
            assert f"{group.key.replace('_', ' ')}s" in asked, group.key
        else:
            assert group.write.env_var in quick, group.key


def test_installation_lists_exactly_the_console_commands() -> None:
    scripts = {
        entry_point.name
        for entry_point in distribution("openproject-ce-mcp").entry_points
        if entry_point.group == "console_scripts"
    }
    installation = _prose(ROOT / "docs" / "installation.md")
    commands_sentence = installation[installation.index("console commands") :].split(".", 1)[0]
    subcommands_sentence = installation[installation.index("The subcommands") :].split(";", 1)[0]

    assert installation.count("console command") == 1
    assert set(re.findall(r"`([^`]+)`", commands_sentence)) == scripts
    subcommands = next(
        action.choices for action in _build_parser()._actions if isinstance(action, argparse._SubParsersAction)
    )
    assert set(re.findall(r"`([^`]+)`", subcommands_sentence)) == {f"openproject-ce-mcp {name}" for name in subcommands}


def test_server_instructions_name_every_opt_in_group() -> None:
    for group in TOOL_GROUPS:
        if not group.read_default:
            assert group.read_env_var in CE_INSTRUCTIONS, group.key


def _instructions_section(title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", CE_INSTRUCTIONS, re.DOTALL | re.MULTILINE)
    assert match, title
    return match.group(1)


def test_server_instructions_name_every_field_the_update_validator_clears() -> None:
    import ast

    import openproject_ce_mcp.tools_work_packages as module

    function = next(
        node
        for node in ast.walk(ast.parse(Path(module.__file__).read_text()))
        if isinstance(node, ast.FunctionDef) and node.name == "_validate_work_package_update_fields"
    )
    returned = next(node.value for node in ast.walk(function) if isinstance(node, ast.Return))
    assert isinstance(returned, ast.Dict)
    clearable = {
        key.value
        for key, value in zip(returned.keys, returned.values, strict=True)
        if isinstance(key, ast.Constant)
        and isinstance(value, ast.Call)
        and any(keyword.arg == "sentinel" for keyword in value.keywords)
    }
    assert {"assignee", "sprint", "estimated_time", "duration", "parent"} <= clearable

    section = _instructions_section("Clearing an assigned field")
    named = re.search(r"work-package (.*?), and project `parent`", section, re.DOTALL)
    assert named
    assert set(re.findall(r"`([^`]+)`", named.group(1))) == clearable
    assert "`bulk_update_work_packages`" in section
    assert '`description` is cleared with `""`' in section.replace("\n", " ")


def test_server_instructions_name_the_one_project_field_that_takes_none() -> None:
    import ast

    import openproject_ce_mcp.tools_projects as module

    function = next(
        node
        for node in ast.walk(ast.parse(Path(module.__file__).read_text()))
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == "update_project"
    )
    clearable = [
        target.id
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and any(keyword.arg == "sentinel" for keyword in node.value.keywords)
        for target in node.targets
        if isinstance(target, ast.Name)
    ]
    assert clearable == ["safe_parent"]
    assert "and project `parent`" in _instructions_section("Clearing an assigned field")


def test_server_instructions_state_that_opt_in_write_tools_need_their_write_flag() -> None:
    opt_in_writes = [group.write for group in TOOL_GROUPS if not group.read_default and group.write is not None]
    assert opt_in_writes
    for write in opt_in_writes:
        assert write.default is False, write.env_var
        assert re.fullmatch(r"OPENPROJECT_ENABLE_[A-Z_]+_WRITE", write.env_var), write.env_var
    assert "`OPENPROJECT_ENABLE_*_WRITE` flag (default off)" in _instructions_section("Some tool groups are opt-in")
