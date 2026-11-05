"""A tool description never sends the caller to a tool that its own configuration does not register.

Every tool name a description or parameter description mentions must be registered in the
configuration that the mentioning tool needs, with every flag that is on by default also on. The
minimal flags of a tool are found by switching flags off while the tool stays registered, so the
check follows the real registration logic and needs no table of scopes. A flag that is on by
default and that an operator switches off is not checked, and the project allowlists are set.
"""

from __future__ import annotations

import re
from functools import cache

import pytest

from openproject_ce_mcp.config import TOOL_GROUPS, Settings
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.tools import enabled_tool_names

_FLAGS = tuple(
    dict.fromkeys(
        attr
        for group in TOOL_GROUPS
        for attr in (group.read_attr, group.write.attr if group.write is not None else None)
        if attr is not None
    )
)

# A write flag needs its matching read flag: the configuration refuses to start without it.
_READ_FLAG_OF = {group.write.attr: group.read_attr for group in TOOL_GROUPS if group.write is not None}

# Tools a description names to say that no such tool exists.
_NAMED_AS_ABSENT = frozenset(
    {"list_cost_types", "list_forums", "list_posts", "get_gitlab_issue", "get_gitlab_merge_request"}
)


def _settings(on: frozenset[str]) -> Settings:
    return Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("*",),
        write_projects=("*",),
        attachment_root="/tmp",
        **{flag: flag in on for flag in _FLAGS},
    )


@cache
def _registered(on: frozenset[str]) -> frozenset[str]:
    return frozenset(enabled_tool_names(_settings(on)))


def _startable(on: frozenset[str]) -> bool:
    return all(read in on for write, read in _READ_FLAG_OF.items() if write in on)


@cache
def _minimal_flags(tool: str) -> frozenset[str]:
    on = frozenset(_FLAGS)
    assert tool in _registered(on)
    shrunk = True
    while shrunk:
        shrunk = False
        for flag in sorted(on):
            smaller = on - {flag}
            if _startable(smaller) and tool in _registered(smaller):
                on, shrunk = smaller, True
    return on


def _descriptions(node: object) -> list[str]:
    if isinstance(node, dict):
        own = [node["description"]] if isinstance(node.get("description"), str) else []
        return [*own, *(text for value in node.values() for text in _descriptions(value))]
    if isinstance(node, list):
        return [text for value in node for text in _descriptions(value)]
    return []


def _texts(tool: object) -> list[str]:
    return [getattr(tool, "description", None) or "", *_descriptions(getattr(tool, "parameters", None) or {})]


def _tool_name_pattern(registered: frozenset[str]) -> re.Pattern[str]:
    verbs = sorted({name.split("_")[0] for name in registered})
    return re.compile(rf"\b(?:{'|'.join(verbs)})_[a-z][a-z_]*[a-z]\b")


_TOOL_NAME = _tool_name_pattern(_registered(frozenset(_FLAGS)))


def _mentions() -> dict[str, set[str]]:
    mcp = create_app(_settings(frozenset(_FLAGS)))
    tools = mcp._tool_manager.list_tools()
    parameter_names = {name for tool in tools for name in (tool.parameters or {}).get("properties", {})}
    mentions: dict[str, set[str]] = {}
    for tool in tools:
        found = {name for text in _texts(tool) for name in _TOOL_NAME.findall(text)}
        found -= {tool.name, *_NAMED_AS_ABSENT, *(parameter_names - _registered(frozenset(_FLAGS)))}
        if found:
            mentions[tool.name] = found
    return mentions


_DEFAULT_FLAGS = frozenset(
    attr
    for group in TOOL_GROUPS
    for attr, default in (
        (group.read_attr, group.read_default),
        *(((group.write.attr, group.write.default),) if group.write is not None else ()),
    )
    if default
)
_MENTIONS = _mentions()
_ALL = _registered(frozenset(_FLAGS))


def test_the_derivation_finds_references() -> None:
    assert any(_MENTIONS.values())


def test_a_tool_named_as_absent_is_not_registered() -> None:
    assert not _NAMED_AS_ABSENT & _ALL


@pytest.mark.parametrize("tool", sorted(_MENTIONS))
def test_every_mentioned_tool_is_a_registered_tool(tool: str) -> None:
    assert _MENTIONS[tool] <= _ALL


@pytest.mark.parametrize("tool", sorted(_MENTIONS))
def test_a_mentioned_tool_is_registered_wherever_the_mentioning_tool_is(tool: str) -> None:
    registered = _registered(_DEFAULT_FLAGS | _minimal_flags(tool))
    assert _MENTIONS[tool] <= registered, sorted(_MENTIONS[tool] - registered)


def test_the_rejected_assignee_message_names_only_tools_registered_by_default() -> None:
    from openproject_ce_mcp.tools_validation import _validate_optional_user_ref

    with pytest.raises(ValueError, match="numeric user id") as raised:
        _validate_optional_user_ref("Alice")
    named = set(_TOOL_NAME.findall(str(raised.value)))
    assert named
    assert named <= _registered(_DEFAULT_FLAGS)
