"""The version floors of the code, the tool descriptions and `docs/tools.md` agree with the catalog.

`tools/api-check/floor_catalog.py` lists every floor with the OpenProject routes behind it; `check_api.py` proves those
routes against the pinned sources (offline, where the sources are, not in CI). This test holds the places that cannot
read the sources. Every `call_version_gated` floor and every hand-built "requires OpenProject X.Y or newer" message in
`app/` is in the catalog and every entry is used; a gate whose `feature` or `floor` is no literal fails unless it is one
of the two column-floor sites (`COMPUTED_SITES`); any other reference to a gate function (an alias, a `partial` with
other keywords) fails; the column floor tables equal the catalog. The versions a tool docstring or a `docs/tools.md`
tool row names are floors of that tool or behaviour versions listed in `NOT_A_ROUTE_FLOOR` (some with a source proof,
checked by `check_api.py`); the column floors of an entity are named in the `sort_by` and `group_by` parameter
descriptions of its tools and nowhere else. Each floor of a tool is named in its description and on its row of
`docs/tools.md`.

Limits, stated on purpose: the catalog's `tools` lists are not derived from the code, so a new tool that reuses an
existing gate and names no floor passes until someone adds it; a message is found only when worded "OpenProject X.Y or
newer", "OpenProject X.Y or later" or "OpenProject X.Y+" (majors 16 to 29) or built from a placeholder in that
wording (not built with `.format`, `%` or concatenation), and message floors are keyed by file and release, not by
feature; a floor in the prose of `docs/tools.md` (section introductions, the page introduction), in `docs/filters.md`,
`docs/installation.md`, `docs/configuration.md` or `docs/architecture.md` is not read; a release with a patch level
("17.9.1") is not taken for a floor.
"""

from __future__ import annotations

import ast
import inspect
import re
import typing
from pathlib import Path

import floor_catalog as catalog  # tests/conftest.py puts tools/api-check on sys.path
import pytest

from openproject_ce_mcp import project_columns, tools, tools_runtime, work_package_columns

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "openproject_ce_mcp" / "app"
DOCS = ROOT / "docs" / "tools.md"

_RELEASE = re.compile(r"(?<![\d.])((?:1[6-9]|2\d)\.\d{1,2})(?!\d|\.\d)")
_MESSAGE_WORDING = r"(?: or newer| or later|\+)"
_MESSAGE_FLOOR = re.compile(rf"OpenProject ((?:1[6-9]|2\d)\.\d{{1,2}}){_MESSAGE_WORDING}")
_MESSAGE_PLACEHOLDER = re.compile(rf"OpenProject \{{\}}{_MESSAGE_WORDING}")
_GATES = {"call_version_gated", "call_query_version_gated"}
COLUMN_PARAMETERS = ("sort_by", "group_by")
# The gate functions themselves word the floor of whatever they are given.
_GATE_MODULE = "app/version_gate.py"


def _key(release: str) -> tuple[int, ...]:
    return tuple(int(part) for part in release.split("."))


def _docstring_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                nodes.add(id(body[0].value))
    return nodes


# Floors computed from a table, not literals: the sort and group columns of two services, held by `COLUMNS`. A site is
# the file with the unparsed `feature` and `floor` of the `functools.partial` that wraps the gate.
_COLUMN_SITE = ("f'the {column} column'", "floor")
COMPUTED_SITES = [
    ("app/services/project_service.py", *_COLUMN_SITE),
    ("app/services/work_package_service.py", *_COLUMN_SITE),
]


def _gate_name(node: ast.AST) -> str:
    name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
    return name if name in _GATES else ""


def _is_literal_text(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _code_floors() -> tuple[set[tuple[str, str]], set[tuple[str, str]], list[tuple[str, str, str]], set[str]]:
    """The (feature, floor) of every literal gate, the (file, floor) of every hand-built message in `app/`, the
    (file, feature, floor) of every gate whose `feature` or `floor` is no string literal, and every other reference to
    a gate function or message built from a placeholder."""
    gates: set[tuple[str, str]] = set()
    messages: set[tuple[str, str]] = set()
    computed: list[tuple[str, str, str]] = []
    stray: set[str] = set()
    for path in sorted(APP.rglob("*.py")):
        relative = "app/" + path.relative_to(APP).as_posix()
        if relative == _GATE_MODULE:
            continue
        tree = ast.parse(path.read_text())
        docstrings = _docstring_nodes(tree)
        accounted: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                wrapped = (
                    node.args[0]
                    if node.args
                    and getattr(func, "attr", getattr(func, "id", "")) == "partial"
                    and _gate_name(node.args[0])
                    else None
                )
                if not (_gate_name(func) or wrapped):
                    continue
                accounted.add(id(wrapped if wrapped is not None else func))
                keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
                feature, floor = keywords.get("feature"), keywords.get("floor")
                if _is_literal_text(feature) and _is_literal_text(floor):
                    gates.add((feature.value, floor.value))  # type: ignore[union-attr]
                else:
                    computed.append(
                        (
                            relative,
                            ast.unparse(feature) if feature else "<none>",
                            ast.unparse(floor) if floor else "<none>",
                        )
                    )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                messages |= {(relative, release) for release in _MESSAGE_FLOOR.findall(node.value)}
            elif isinstance(node, ast.JoinedStr):
                text = "".join(
                    part.value if isinstance(part, ast.Constant) else "{}"
                    for part in node.values  # type: ignore[union-attr]
                )
                if _MESSAGE_PLACEHOLDER.search(text):
                    stray.add(f"{relative}: {ast.unparse(node)}")
        for node in ast.walk(tree):
            if _gate_name(node) and id(node) not in accounted:
                stray.add(f"{relative}: {ast.unparse(node)}")
            elif isinstance(node, ast.alias) and node.name in _GATES and node.asname:
                stray.add(f"{relative}: import {node.name} as {node.asname}")
    return gates, messages, computed, stray


def _declared(tool: str) -> set[str]:
    return {floor.floor for floor in catalog.FLOORS if tool in floor.tools}


def _behaviour(tool: str) -> set[str]:
    return {release for name, release in (*catalog.NOT_A_ROUTE_FLOOR, *catalog.DESCRIPTION_MENTIONS) if name == tool}


def _field_descriptions(hint: object) -> list[str]:
    texts = [meta.description for meta in getattr(hint, "__metadata__", ()) if getattr(meta, "description", None)]
    for argument in typing.get_args(hint):
        texts += _field_descriptions(argument)
    return texts


def _parameter_descriptions(function: object) -> dict[str, str]:
    hints = typing.get_type_hints(function, include_extras=True)
    return {name: " ".join(_field_descriptions(hint)) for name, hint in hints.items() if name != "return"}


def _columns(tool: str) -> set[str]:
    entity = catalog.COLUMN_TOOLS.get(tool)
    return {column.floor for column in catalog.COLUMNS if column.entity == entity}


def _described() -> dict[str, tuple[set[str], dict[str, set[str]]]]:
    """Per tool: the releases its docstring names, and those each parameter description names."""
    assert tools.READ_TOOLS_BY_SCOPE and tools_runtime._TOOL_FUNCTIONS, "no tool is registered"
    described = {}
    for name, function in tools_runtime._TOOL_FUNCTIONS.items():
        in_docstring = set(_RELEASE.findall(inspect.getdoc(function) or ""))
        in_parameters = {
            parameter: set(_RELEASE.findall(text)) for parameter, text in _parameter_descriptions(function).items()
        }
        named = in_docstring.union(*in_parameters.values())
        if named or _declared(name) or name in catalog.COLUMN_TOOLS:
            described[name] = (in_docstring, in_parameters)
    return described


def _documented() -> dict[str, set[str]]:
    """Per tool row of `docs/tools.md`: the releases the row names."""
    rows: dict[str, set[str]] = {}
    for line in DOCS.read_text().splitlines():
        match = re.match(r"\| `([a-z_]+)` \|", line)
        if match:
            assert match.group(1) not in rows, f"docs/tools.md has two rows for {match.group(1)}"
            rows[match.group(1)] = set(_RELEASE.findall(line))
    return rows


def test_every_floor_is_the_newest_release_of_its_routes_or_says_why_it_is_higher() -> None:
    for floor in catalog.FLOORS:
        label = (floor.feature, floor.floor)
        assert floor.routes, label
        newest = max((route.release for route in floor.routes), key=_key)
        assert floor.kind in {catalog.GATE, catalog.MESSAGE}, label
        assert bool(floor.files) == (floor.kind == catalog.MESSAGE), label
        if floor.reason:
            assert _key(floor.floor) > _key(newest), (label, "a reason is for a floor above its routes")
        else:
            assert floor.floor == newest, (label, newest)


def test_no_floor_is_listed_twice_and_every_tool_it_names_exists() -> None:
    pairs = [(floor.feature, floor.floor) for floor in catalog.FLOORS]
    assert len(pairs) == len(set(pairs))
    registered = set(tools_runtime._TOOL_FUNCTIONS)
    for floor in catalog.FLOORS:
        assert set(floor.tools) <= registered, (floor.feature, floor.tools)
    assert {tool for tool, _ in catalog.NOT_A_ROUTE_FLOOR} <= registered
    assert set(catalog.COLUMN_TOOLS) <= registered


def test_every_gate_and_message_floor_of_the_code_is_in_the_catalog_and_every_entry_is_used() -> None:
    gates, messages, computed, stray = _code_floors()
    catalogued_gates = {(floor.feature, floor.floor) for floor in catalog.FLOORS if floor.kind == catalog.GATE}
    catalogued_messages = {
        (file, floor.floor) for floor in catalog.FLOORS if floor.kind == catalog.MESSAGE for file in floor.files
    }
    mentions = {
        (file, release): feature
        for (file, release), feature in catalog.MENTIONS.items()
        if any(floor.feature == feature and floor.floor == release for floor in catalog.FLOORS)
    }

    assert gates == catalogued_gates
    assert sorted(computed) == sorted(COMPUTED_SITES), sorted(computed)
    assert not stray, sorted(stray)
    assert catalogued_messages <= messages, sorted(catalogued_messages - messages)
    assert messages - catalogued_messages == set(mentions), sorted(messages - catalogued_messages - set(mentions))
    assert set(mentions) == set(catalog.MENTIONS), "a mention names a feature and release that no entry has"


def test_a_behaviour_proof_and_a_description_mention_belong_to_a_listed_version() -> None:
    for (tool, release), route in catalog.BEHAVIOUR_ROUTES.items():
        assert (tool, release) in catalog.NOT_A_ROUTE_FLOOR, (tool, release)
        assert route.release == release, (tool, release, route.release)
    for (tool, release), feature in catalog.DESCRIPTION_MENTIONS.items():
        assert any(floor.feature == feature and floor.floor == release for floor in catalog.FLOORS), (tool, release)
        assert (tool, release) not in catalog.NOT_A_ROUTE_FLOOR, "a mention is not a behaviour version"


def test_the_column_floor_tables_equal_the_catalog() -> None:
    in_catalog = {
        entity: {column.column: column.floor for column in catalog.COLUMNS if column.entity == entity}
        for entity in ("project", "work_package")
    }

    assert project_columns.COLUMN_FLOORS == in_catalog["project"]
    assert work_package_columns.COLUMN_FLOORS == in_catalog["work_package"]
    for column in catalog.COLUMNS:
        assert bool(column.routes) != bool(column.gap), (column.entity, column.column, "routes or the gap, one of them")
        newest = max((route.release for route in column.routes), key=_key, default=column.floor)
        assert _key(column.floor) >= _key(newest)
        assert bool(column.reason) == (_key(column.floor) > _key(newest)) or not column.routes, column.column


@pytest.mark.parametrize("tool", sorted(_described()))
def test_a_tool_description_names_the_floors_of_the_tool_and_nothing_else(tool: str) -> None:
    in_docstring, in_parameters = _described()[tool]
    declared = _declared(tool)
    allowed = declared | _behaviour(tool)
    columns = _columns(tool)
    named = in_docstring.union(*in_parameters.values())

    assert declared <= named, f"{tool}: its description does not name the floor {sorted(declared - named)}"
    assert in_docstring <= allowed, (
        f"{tool}: the docstring names {sorted(in_docstring - allowed)}, which is no floor of the tool "
        "(add it to NOT_A_ROUTE_FLOOR with what it changes, or fix the number)"
    )
    for parameter, releases in in_parameters.items():
        permitted = allowed | (columns if parameter in COLUMN_PARAMETERS else set())
        assert releases <= permitted, (
            f"{tool}: the description of {parameter} names {sorted(releases - permitted)}, which is no floor of the "
            "tool (add it to NOT_A_ROUTE_FLOOR with what it changes, or fix the number)"
        )
    if columns:
        sorting = [parameter for parameter in COLUMN_PARAMETERS if parameter in in_parameters]
        assert sorting, f"{tool}: it has neither sort_by nor group_by"
        for parameter in sorting:
            assert columns <= in_parameters[parameter], (
                f"{tool}: {parameter} lacks the column floors {sorted(columns - in_parameters[parameter])}"
            )


def test_every_behaviour_entry_is_still_named_by_its_tool_or_its_docs_row() -> None:
    described, documented = _described(), _documented()
    stale = [
        (tool, release)
        for tool, release in (*catalog.NOT_A_ROUTE_FLOOR, *catalog.DESCRIPTION_MENTIONS)
        if release
        not in described.get(tool, (set(), {}))[0].union(*described.get(tool, (set(), {}))[1].values())
        | documented.get(tool, set())
    ]

    assert stale == []


@pytest.mark.parametrize("tool", sorted(_documented()))
def test_a_docs_row_names_only_floors_of_its_tool(tool: str) -> None:
    named = _documented()[tool]
    allowed = _declared(tool) | _behaviour(tool)

    assert named <= allowed, f"docs/tools.md row of {tool} names {sorted(named - allowed)}"


@pytest.mark.parametrize("tool", sorted({tool for floor in catalog.FLOORS for tool in floor.tools}))
def test_the_docs_row_of_a_tool_names_every_floor_of_the_tool(tool: str) -> None:
    missing = _declared(tool) - _documented()[tool]

    assert not missing, f"docs/tools.md names no {sorted(missing)} on the row of {tool}"


def test_the_check_finds_a_wrong_floor_a_missing_entry_and_a_stray_number() -> None:
    assert _RELEASE.findall("needs OpenProject 17.4+, tested on 17.9.1 and 3.11") == ["17.4"]
    assert _RELEASE.findall("from v18.2, not 117.4 or 17.456") == ["18.2"]
    assert _MESSAGE_FLOOR.findall("require the Backlogs module and OpenProject 17.3 or newer. OpenProject 17.6+ x") == [
        "17.3",
        "17.6",
    ]
    assert _MESSAGE_FLOOR.findall("OpenProject 17.4 and 17.5 add a user a second time") == []
    assert _MESSAGE_FLOOR.findall("needs OpenProject 18.2 or later") == ["18.2"]
    assert _MESSAGE_PLACEHOLDER.search("requires OpenProject {} or newer.")
    assert _key("17.10") > _key("17.9")
