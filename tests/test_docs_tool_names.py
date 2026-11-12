"""A tool-shaped name in a backticked span of the user-facing docs is a tool the server registers.

A tool that is removed or renamed cannot linger in the README or the docs: the CHANGELOG is the one place where old
names stay, as history. Three kinds of name are not tool references and need no entry: a parameter name of a registered
tool, a public method of an application service (the architecture doc describes the code), and a tool the docs name to
say that it does not exist (the set the description check shares).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import pytest
from test_tool_description_references import _ALL, _FLAGS, _NAMED_AS_ABSENT, _TOOL_NAME, _settings

from openproject_ce_mcp.app import services
from openproject_ce_mcp.server import create_app

ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
_FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
_SPAN = re.compile(r"`([^`\n]+)`")
_TOOL_SHAPED = re.compile(rf"^{_TOOL_NAME.pattern}$")

_PARAMETER_NAMES = frozenset(
    name
    for tool in create_app(_settings(frozenset(_FLAGS)))._tool_manager.list_tools()
    for name in (tool.parameters or {}).get("properties", {})
)


def _service_method_names() -> frozenset[str]:
    # architecture.md describes the code, so its backticked snake_case names include application service methods.
    names: set[str] = set()
    for module_info in pkgutil.iter_modules(services.__path__, f"{services.__name__}."):
        module = importlib.import_module(module_info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__:
                names.update(
                    name for name, _ in inspect.getmembers(cls, inspect.isfunction) if not name.startswith("_")
                )
    return frozenset(names)


_SERVICE_METHOD_NAMES = _service_method_names()


def _tool_shaped_names(path: Path) -> set[str]:
    prose = _FENCE.sub("", path.read_text(encoding="utf-8"))
    return {span for span in _SPAN.findall(prose) if _TOOL_SHAPED.match(span)}


def test_the_guard_reads_tool_names_from_the_docs() -> None:
    assert "list_projects" in _tool_shaped_names(ROOT / "docs" / "tools.md")


@pytest.mark.parametrize("path", DOC_FILES, ids=lambda path: path.name)
def test_every_tool_named_in_the_docs_is_registered(path: Path) -> None:
    unknown = _tool_shaped_names(path) - _ALL - _PARAMETER_NAMES - _SERVICE_METHOD_NAMES - _NAMED_AS_ABSENT
    assert not unknown, sorted(unknown)
