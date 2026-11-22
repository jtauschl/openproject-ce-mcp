"""Every place that turns a caught exception into text, and every service, is accounted for.

A server error reaches the caller as `str(exc)`. The transport already makes that text generic while a hide is
active (`app/transport/errors.py`) and a service renders it by its entity (`app/services/_error_masking.py`), so a
new place that formats a caught exception, or a new service without an entity, has to say why it is safe.

Stated boundary (as the other AST census tests): it finds `str(<name>)` and an interpolated `<name>` for the names
`exc`, `e`, `error` and `err`; a message built through another name or a helper is covered by the transport's
generic text, not by this census.
"""

from __future__ import annotations

import ast
from pathlib import Path

import openproject_ce_mcp
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY

ROOT = Path(openproject_ce_mcp.__file__).parent
NAMES = {"exc", "e", "error", "err"}

# (file, function, expression) -> why the text is safe.
SITES: dict[tuple[str, str, str], str] = {
    ("app/version_gate.py", "call_query_version_gated", "f'{exc}{hint}'"): (
        "keeps `entries` and composes the hint around the server text"
    ),
    ("tools_runtime.py", "_run_tool", "str(exc)"): "forwards the text the transport made generic or a service rendered",
    ("tools_runtime.py", "wrapper", "str(exc)"): "forwards the text the transport made generic or a service rendered",
    ("app/services/work_package_service.py", "_validate_date", "f'{field_name} must be in YYYY-MM-DD format: {exc}'"): (
        "a local ValueError, no server text"
    ),
    ("app/services/work_package_service.py", "fetch_one", "str(e)"): (
        "the error of the decorated `get`, already rendered by its entity"
    ),
    ("app/services/work_package_service.py", "bulk_create", "str(exc)"): (
        "the error of the decorated `create`, already rendered by its entity"
    ),
    ("app/services/work_package_service.py", "bulk_update", "str(exc)"): (
        "the error of the decorated `update`, already rendered by its entity"
    ),
    (
        "app/services/query_metadata_service.py",
        "get_sort_by",
        "str(exc)",
    ): "wraps a local ValueError of the argument parser",
    ("app/services/board_service.py", "_sort_by_hrefs", "str(exc)"): "wraps a local ValueError of the argument parser",
    ("server.py", "_run_server", "str(exc)"): "a settings error, no server text",
    ("server.py", "main", "f'error: {exc}'"): "a settings error printed to the operator's console, no server text",
}

# Service classes that carry no `@redacted_server_errors(entity)`, with the reason.
UNDECORATED: dict[str, str] = {
    "ActionCapabilityService": "reads only and two entities (action, capability): the transport's generic text applies",
    "CostService": "reads only, several entities: the transport's generic text applies",
    "ExtendedMetadataService": "reads only: the transport's generic text applies",
    "GithubGitlabLinkService": "reads only: the transport's generic text applies",
    "ProjectDirectoryService": "internal lookup: its errors are logged, never shown",
    "ProjectAdminService": "reads only: the transport's generic text applies",
    "StatusPriorityTypeService": "reads only, three entities: the transport's generic text applies",
}


def _enclosing(tree: ast.AST) -> dict[ast.AST, str]:
    owner: dict[ast.AST, str] = {}

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            owner[child] = name
            visit(child, name)

    visit(tree, "<module>")
    return owner


def _found() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in sorted(
        [*ROOT.joinpath("app").rglob("*.py"), ROOT / "client.py", ROOT / "tools_runtime.py", ROOT / "server.py"]
    ):
        tree = ast.parse(path.read_text())
        owner = _enclosing(tree)
        for node in ast.walk(tree):
            text = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "str"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in NAMES
            ):
                text = ast.unparse(node)
            elif isinstance(node, ast.JoinedStr) and any(
                isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name) and part.value.id in NAMES
                for part in node.values
            ):
                text = ast.unparse(node)
            if text is not None:
                found.add((str(path.relative_to(ROOT)), owner.get(node, "<module>"), text))
    return found


def test_every_place_that_formats_a_caught_exception_is_accounted_for() -> None:
    found = {site for site in _found() if not site[0].startswith(("setup_cli", "doctor"))}

    assert found - set(SITES) == set(), "a new place formats a caught exception: say why it is safe"
    assert set(SITES) - found == set(), "a row of this table names a place that no longer exists"


def test_every_service_class_has_an_entity_or_a_reason() -> None:
    decorated: dict[str, str] = {}
    classes: set[str] = set()
    for path in sorted(ROOT.joinpath("app/services").glob("*_service.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Service"):
                continue
            classes.add(node.name)
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "redacted_server_errors"
                ):
                    decorated[node.name] = ast.literal_eval(decorator.args[0])

    assert all(entity in HIDE_FIELD_ENV_BY_ENTITY for entity in decorated.values()), "an entity no setting knows"
    assert all(_assigns_settings(ROOT / "app/services" / name) for name in _files_of(decorated)), (
        "the decorator reads `self._settings`: a service that does not assign it fails on the error path only"
    )
    assert classes - set(decorated) == set(UNDECORATED), "a service without an entity and without a reason"
    assert all(UNDECORATED.values())


def _files_of(classes: dict[str, str]) -> set[str]:
    return {
        path.name
        for path in ROOT.joinpath("app/services").glob("*_service.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef) and node.name in classes
    }


def _assigns_settings(path: Path) -> bool:
    return "self._settings = " in path.read_text()
