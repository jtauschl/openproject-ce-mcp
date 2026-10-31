"""Structural guard: a project scope decision never reads a project's name or a link's title.

The guard is syntactic. It sees a display value read in a scope-deciding policy module and in the arguments of a call
into one; a name routed through an alias, a partial or an earlier assignment is out of its reach. The candidate
builders cannot be handed a name by signature, and the behavioral tests of the scope policy show that a pattern equal
to a name alone is denied.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from openproject_ce_mcp.app.policies import scope

APP = Path(scope.__file__).resolve().parents[1]
PACKAGE = APP.parent
POLICIES = APP / "policies"
DISPLAY_KEYS = {"name", "title"}

EXPECTED_DECIDING_POLICIES = {
    "activity_policy",
    "backlog_bucket_policy",
    "board_policy",
    "document_policy",
    "grid_policy",
    "news_policy",
    "project_policy",
    "project_storage_policy",
    "rendered_text_policy",
    "scope",
    "sprint_policy",
    "version_policy",
    "work_package_policy",
}
EXPECTED_CALL_SITES = {
    "app/resolvers/project_query.py",
    "app/resolvers/version_resolver.py",
    "app/services/backlog_bucket_service.py",
    "app/services/board_service.py",
    "app/services/grid_service.py",
    "app/services/project_service.py",
    "app/services/sprint_service.py",
}


def _display_reads(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            key = node.slice.value
        elif isinstance(node, ast.Attribute):
            key = node.attr
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            key = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            key = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
        elif isinstance(node, ast.Dict):
            lines += [k.lineno for k in node.keys if isinstance(k, ast.Constant) and k.value in DISPLAY_KEYS]
        if key in DISPLAY_KEYS:
            lines.append(node.lineno)
    return sorted(lines)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_scope(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        parts = (node.module or "").split(".") if node.module else []
        if node.level == 1 and (parts == ["scope"] or (not parts and any(a.name == "scope" for a in node.names))):
            return True
        if node.level == 0 and parts[-2:] == ["policies", "scope"]:
            return True
        if node.level == 0 and parts[-1:] == ["policies"] and any(a.name == "scope" for a in node.names):
            return True
    return False


def _deciding_policies() -> set[str]:
    return {"scope"} | {path.stem for path in POLICIES.glob("*.py") if _imports_scope(_parse(path))}


def _policy_bindings(tree: ast.Module, deciding: set[str]) -> tuple[set[str], set[str]]:
    """The local names a module binds to a deciding policy module, and to a function of one."""
    modules: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if alias.asname and "policies" in parts[:-1] and parts[-1] in deciding:
                    modules.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            parts = (node.module or "").split(".")
            if "policies" not in parts:
                continue
            below = parts[parts.index("policies") + 1 :]
            for alias in node.names:
                bound = alias.asname or alias.name
                if not below and alias.name in deciding:
                    modules.add(bound)
                elif below and below[0] in deciding:
                    functions.add(bound)
    return modules, functions


def _decision_call_reads(tree: ast.Module, deciding: set[str]) -> list[int]:
    modules, functions = _policy_bindings(tree, deciding)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        while isinstance(callee, ast.Attribute):
            callee = callee.value
        decides = isinstance(callee, ast.Name) and (
            callee.id in modules or (callee.id in functions and callee is node.func)
        )
        if decides:
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                lines += _display_reads(argument)
    return sorted(lines)


def _call_site_modules() -> list[Path]:
    deciding = _deciding_policies()
    return sorted(
        path
        for path in PACKAGE.rglob("*.py")
        if POLICIES not in path.parents and any(_policy_bindings(_parse(path), deciding))
    )


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def test_the_deciding_policies_are_exactly_the_ones_built_on_the_scope_api() -> None:
    assert _deciding_policies() == EXPECTED_DECIDING_POLICIES


def test_the_call_sites_of_the_deciding_policies_include_every_known_decider() -> None:
    assert EXPECTED_CALL_SITES <= {_relative(path) for path in _call_site_modules()}


DECIDING_MODULES = [POLICIES / f"{stem}.py" for stem in sorted(EXPECTED_DECIDING_POLICIES)] + [
    APP / "services" / "project_directory_service.py"
]


@pytest.mark.parametrize("path", DECIDING_MODULES, ids=lambda path: path.name)
def test_no_scope_deciding_module_reads_a_name_or_title(path: Path) -> None:
    assert _display_reads(_parse(path)) == []


@pytest.mark.parametrize("path", _call_site_modules(), ids=_relative)
def test_no_call_into_a_deciding_policy_is_given_a_name_or_title(path: Path) -> None:
    assert _decision_call_reads(_parse(path), _deciding_policies()) == []


@pytest.mark.parametrize(
    "source",
    [
        'record["name"]',
        'record["title"]',
        'record.get("name")',
        'record.get("title", "")',
        "record.name",
        "record.title",
        'getattr(record, "name")',
        'getattr(record, "title", None)',
        '{"name": 1}',
        '{"id": 1, "title": 2}',
    ],
)
def test_the_detector_sees_every_form_of_reading_a_display_value(source: str) -> None:
    assert _display_reads(ast.parse(source)) != []


@pytest.mark.parametrize(
    "source",
    [
        'record["identifier"]',
        'record.get("id")',
        "record.identifier",
        'getattr(record, "identifier")',
        '{"id": 1, "identifier": 2}',
        "record[key]",
    ],
)
def test_the_detector_ignores_everything_that_is_not_a_display_value(source: str) -> None:
    assert _display_reads(ast.parse(source)) == []


_IMPORTS = (
    "from ..policies import scope as scope_policy\n"
    "from ..policies.project_policy import ensure_project_read_allowed as allowed\n"
    "from ..policies import hidden_fields\n"
)
_ABSOLUTE_IMPORTS = (
    "from openproject_ce_mcp.app.policies import scope as scope_policy\n"
    "from openproject_ce_mcp.app.policies.project_policy import ensure_project_read_allowed as allowed\n"
    "import openproject_ce_mcp.app.policies.grid_policy as grids\n"
)


@pytest.mark.parametrize(
    "call",
    [
        "scope_policy.project_record_candidates(1, ref.name)",
        'scope_policy.project_payload_candidates({"identifier": "a", "name": "b"})',
        'allowed({"id": 1}, settings=getattr(ref, "name"))',
        'allowed(payload["title"], settings=s)',
        "payload_allowed(lambda: allowed({}, settings=ref.name))",
    ],
)
def test_the_call_site_check_flags_a_name_given_to_a_deciding_policy(call: str) -> None:
    tree = ast.parse(_IMPORTS + call)

    assert _decision_call_reads(tree, EXPECTED_DECIDING_POLICIES) != []


@pytest.mark.parametrize(
    "call",
    [
        "scope_policy.project_record_candidates(1, ref.name)",
        'allowed({"id": 1}, settings=ref.title)',
        "grids.ensure_grid_allowed(ref.name)",
    ],
)
def test_the_call_site_check_follows_absolute_imports_of_a_deciding_policy(call: str) -> None:
    tree = ast.parse(_ABSOLUTE_IMPORTS + call)

    assert _decision_call_reads(tree, EXPECTED_DECIDING_POLICIES) != []


@pytest.mark.parametrize(
    "source",
    [
        "from . import scope\n",
        "from .scope import ensure_project_link_allowed\n",
        "from openproject_ce_mcp.app.policies import scope\n",
        "from openproject_ce_mcp.app.policies.scope import payload_allowed\n",
    ],
)
def test_a_policy_module_importing_the_scope_api_is_a_deciding_one(source: str) -> None:
    assert _imports_scope(ast.parse(source))


def test_a_policy_module_not_importing_the_scope_api_is_not_a_deciding_one() -> None:
    assert not _imports_scope(ast.parse("from . import hidden_fields\nfrom .access import ensure_read_enabled\n"))


@pytest.mark.parametrize(
    "statement",
    [
        "scope_policy.project_record_candidates(1, ref.identifier)",
        "label = record.name",
        'hidden_fields.apply_hidden_fields("project", record.name)',
        "other.allowed(record.name)",
    ],
)
def test_the_call_site_check_leaves_other_reads_of_a_name_alone(statement: str) -> None:
    tree = ast.parse(_IMPORTS + statement)

    assert _decision_call_reads(tree, EXPECTED_DECIDING_POLICIES) == []


@pytest.mark.parametrize(
    "builder",
    [
        scope.project_record_candidates,
        scope.project_payload_candidates,
        scope.project_link_candidates,
        scope.project_known_by_id_allowed,
        scope.project_named_by_link_allowed,
    ],
    ids=lambda builder: builder.__name__,
)
def test_no_candidate_builder_takes_a_name_or_title(builder) -> None:
    assert not DISPLAY_KEYS & set(inspect.signature(builder).parameters)
