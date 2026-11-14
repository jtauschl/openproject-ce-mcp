"""A rejected name reference tells the caller which values would have been accepted.

The resolvers and services that match a caller's name against a set they already hold append `offered_clause`
(not found) or `candidates_clause` (ambiguous) to the error. This guard has two halves. `SITES` is the contract: every
place in `app/` that builds a not-found, not-allowed or ambiguous error for a reference is listed with the tests that
prove the clause, or with the reason it offers none. The AST scan is the net: it finds every such error whose message
carries a placeholder and fails for a site missing from the table, so a new resolver cannot join without saying
which of the two it is.

Limits, stated on purpose: the scan reads message literals, so a message assembled in a variable is not seen; the
proving tests live next to the fakes of each component and are named here, a rename fails the table.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from openproject_ce_mcp.app.offered_values import (
    OFFERED_LIMIT,
    candidates_clause,
    offered_clause,
    offered_names,
    trim_text,
)

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "openproject_ce_mcp" / "app"
UNIT_TESTS = ROOT / "tests" / "unit"

_PATTERN = re.compile(r"not found|is not allowed|is not available|is ambiguous")
_ERRORS = {"InvalidInputError", "NotFoundError"}

OFFERS = "offers"
EXEMPT = "exempt"

# (module under app/, function) -> (kind, proving tests or the reason nothing is offered)
SITES: dict[tuple[str, str], tuple[str, tuple[str, ...] | str]] = {
    ("resolvers/status_priority_type_resolver.py", "resolve_status_id"): (
        OFFERS,
        ("test_an_unknown_status_names_the_allowed_statuses",),
    ),
    ("resolvers/status_priority_type_resolver.py", "resolve_priority_id"): (
        OFFERS,
        ("test_an_unknown_priority_names_the_allowed_priorities",),
    ),
    ("resolvers/type_resolver.py", "resolve_id"): (
        OFFERS,
        (
            "test_an_unknown_type_names_the_allowed_types_of_the_project",
            "test_an_ambiguous_type_name_names_its_candidates",
        ),
    ),
    ("resolvers/version_resolver.py", "resolve_id"): (
        OFFERS,
        (
            "test_an_unknown_version_name_in_a_project_names_the_allowed_versions",
            "test_a_version_id_that_is_not_available_names_the_allowed_versions",
            "test_an_unknown_version_name_without_a_project_names_the_allowed_versions",
        ),
    ),
    ("resolvers/version_resolver.py", "_ambiguous_version"): (
        OFFERS,
        ("test_an_ambiguous_version_name_names_its_candidates",),
    ),
    ("resolvers/sprint_resolver.py", "resolve_id"): (
        OFFERS,
        (
            "test_an_unknown_sprint_names_the_allowed_sprints_of_every_page_read",
            "test_an_ambiguous_sprint_name_names_its_candidates",
        ),
    ),
    ("resolvers/principal_resolver.py", "resolve_id"): (
        OFFERS,
        ("test_an_ambiguous_principal_names_its_candidates_and_an_unknown_one_offers_nothing",),
    ),
    ("services/membership_service.py", "_resolve_role_hrefs"): (
        OFFERS,
        ("test_an_unknown_role_names_the_allowed_roles_and_an_ambiguous_one_its_candidates",),
    ),
    ("services/time_entry_service.py", "_resolve_activity_id"): (
        OFFERS,
        (
            "test_an_unknown_activity_name_is_refused_with_the_allowed_names",
            "test_an_ambiguous_activity_name_names_its_candidates",
        ),
    ),
    ("services/_schema_write_helpers.py", "_not_allowed"): (
        OFFERS,
        (
            "test_a_value_the_schema_does_not_allow_names_the_allowed_values_in_the_order_offered",
            "test_a_custom_field_option_that_is_not_allowed_names_the_allowed_values",
        ),
    ),
    ("services/_schema_write_helpers.py", "_ambiguous"): (
        OFFERS,
        ("test_a_title_shared_by_two_allowed_values_is_ambiguous_and_names_both",),
    ),
    ("services/_schema_write_helpers.py", "resolve_custom_field_key"): (
        OFFERS,
        (
            "test_a_custom_field_that_is_not_available_names_the_available_custom_fields",
            "test_a_hidden_custom_field_is_not_among_the_names_a_refusal_offers",
            "test_an_unknown_custom_field_does_not_offer_a_field_the_settings_hide",
        ),
    ),
    ("services/project_service.py", "_resolve_status_href"): (
        OFFERS,
        ("test_an_unknown_project_status_names_the_allowed_statuses",),
    ),
    ("resolvers/project_resolver.py", "_resolve_record_uncached"): (
        EXEMPT,
        "the set is every project the token can see; the message points at list_projects",
    ),
    ("resolvers/project_resolver.py", "_resolve_by_name_record"): (
        EXEMPT,
        "the set is every project the token can see; the message points at list_projects",
    ),
    ("resolvers/project_resolver.py", "_ambiguous_error"): (
        EXEMPT,
        "already names up to 10 candidates with identifier, id and name",
    ),
    ("resolvers/work_package_resolver.py", "resolve_record"): (
        EXEMPT,
        "a work package is named by id or display id, not by a name from a set; the message explains the reference forms",
    ),
    ("adapters/httpx_reminder_api.py", "get"): (EXEMPT, "an id lookup: no name set exists"),
    ("services/wiki_page_link_service.py", "_find_link_of_work_package"): (
        EXEMPT,
        "an id lookup on one work package: no name set exists",
    ),
    ("services/_stored_text_edit.py", "replace_passage"): (
        EXEMPT,
        "a passage of the stored text, not a reference; the message tells how to copy it",
    ),
    ("version_gate.py", "call_version_gated"): (EXEMPT, "a missing feature of the instance, not a reference"),
}


def _text_parts(node: ast.expr) -> tuple[list[str], bool]:
    """The literal pieces of a message expression and whether it has a placeholder."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value], False
    if isinstance(node, ast.JoinedStr):
        pieces = [part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str)]
        return pieces, any(isinstance(part, ast.FormattedValue) for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, left_placeholder = _text_parts(node.left)
        right, right_placeholder = _text_parts(node.right)
        return left + right, left_placeholder or right_placeholder
    return [], False


def _error_sites(tree: ast.AST) -> set[str]:
    sites: set[str] = set()
    scopes: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            scopes.append(node.name)
            self.generic_visit(node)
            scopes.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name in _ERRORS and node.args:
                pieces, placeholder = _text_parts(node.args[0])
                if placeholder and _PATTERN.search("".join(pieces)):
                    sites.add(scopes[-1] if scopes else "<module>")
            self.generic_visit(node)

    Visitor().visit(tree)
    return sites


def _scan() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(APP.rglob("*.py")):
        relative = path.relative_to(APP).as_posix()
        found |= {(relative, function) for function in _error_sites(ast.parse(path.read_text()))}
    return found


def _test_names() -> set[str]:
    names: set[str] = set()
    for path in UNIT_TESTS.glob("test_*.py"):
        names |= {
            node.name
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
    return names


def test_every_reference_error_of_the_app_is_in_the_table_and_every_row_exists() -> None:
    found = _scan()

    assert found - set(SITES) == set(), "a new reference error: say whether it offers the set or why it cannot"
    assert set(SITES) - found == set(), "a row names an error that no longer exists"


def test_every_offering_row_names_tests_that_exist_and_every_exemption_a_reason() -> None:
    existing = _test_names()

    for site, (kind, proof) in SITES.items():
        if kind == OFFERS:
            assert proof, site
            assert set(proof) <= existing, (site, sorted(set(proof) - existing))
        else:
            assert kind == EXEMPT and isinstance(proof, str) and proof.strip(), site


def test_the_scan_sees_a_message_built_by_concatenation_and_an_error_returned_not_raised() -> None:
    tree = ast.parse(
        "def a(x):\n"
        "    raise InvalidInputError(f\"thing '{x}' was not found.\" + offered_clause(x))\n"
        "def b(x):\n"
        "    return NotFoundError(f\"thing '{x}' is ambiguous\")\n"
        "def c(x):\n"
        "    raise InvalidInputError('thing was not found')\n"
    )

    assert _error_sites(tree) == {"a", "b"}


def test_names_are_sorted_without_regard_to_case_and_listed_once() -> None:
    assert offered_names(["beta", "Alpha", "beta", " alpha ", "Gamma"]) == "Alpha, alpha, beta, Gamma"
    assert offered_clause(["b", "A"], plural="things") == " Allowed things: A, b."


def test_the_order_the_server_offers_is_kept_when_asked() -> None:
    assert offered_names(["Urgent", "Low", "High"], sort=False) == "Urgent, Low, High"


def test_a_long_list_is_capped_and_says_how_many_are_left() -> None:
    names = [f"v{index:02d}" for index in range(OFFERED_LIMIT + 5)]

    offered = offered_names(names)

    assert offered is not None
    assert offered.endswith(f"v{OFFERED_LIMIT - 1:02d}, … (+5 more)")
    assert f"v{OFFERED_LIMIT:02d}" not in offered


@pytest.mark.parametrize("empty", [[], [None, "", "  "]])
def test_nothing_known_offers_no_clause(empty: list[object]) -> None:
    assert offered_names(empty) is None
    assert offered_clause(empty, plural="things") == ""
    assert candidates_clause([]) == ""


def test_a_name_is_put_on_one_line_and_cut_at_the_limit() -> None:
    assert trim_text("a\n  b\tc") == "a b c"
    assert trim_text("x" * 300, limit=10) == "x" * 9 + "…"
    assert trim_text("   ") is None


def test_candidates_carry_their_id_and_a_blank_name_is_left_out() -> None:
    assert candidates_clause([(12, "Release"), (15, None), (16, "  ")]) == " Matches: 12 (Release), 15, 16."
