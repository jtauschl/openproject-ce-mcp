"""User-facing docs state the tool-group facts the code defines, so a new group,
write flag or console command cannot leave them silently wrong."""

from __future__ import annotations

import argparse
import re
from importlib.metadata import distribution
from pathlib import Path

import pytest

from openproject_ce_mcp.config import TOOL_GROUPS
from openproject_ce_mcp.server import CE_INSTRUCTIONS, _build_parser

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
