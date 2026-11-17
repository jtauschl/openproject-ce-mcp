"""Every `payload=` of a write result shows no value of a hidden field.

The payload of a write result is built from the server's form answer (masked by `shown_payload` in
`_finalize_write`, in the user result and in the project copy), from a record the service read (a delete preview:
`record_payload`), or from what the caller passed in. This scan reads the services' source and requires that every
`payload=` keyword argument is one of:

- a call of `shown_payload` or `record_payload`, or a local name whose every assignment in the same function is such a call;
- `outcome.payload` of `_finalize_write`, or the argument of `_finalize_write` itself (masked inside it);
- the argument of `self._write_result` in a module whose `_write_result` calls `shown_payload`;
- a site listed in `UNMASKED` with its reason, keyed by (module, function), which a stale row fails.

Stated limit: the scan reads keyword arguments named `payload` of calls only. A payload passed positionally, a result
class built without that keyword and a payload changed after construction are outside it; the golden tests
(`test_write_payload_hidden_fields.py`) and the delete matrix (`test_delete_preview_hidden_fields.py`) cover those by
running the tools.
"""

from __future__ import annotations

import ast
from pathlib import Path

import openproject_ce_mcp

SERVICES = Path(openproject_ce_mcp.__file__).parent / "app" / "services"
MASKERS = {"shown_payload", "record_payload"}

CALLER_INPUT = "the payload holds only the caller's own input, no value read from a form answer or a record"
PARAMETER = "the payload arrives as a parameter; the functions that build it are masked or listed"
INTERNAL_HELPER = "an internal helper that receives the payload the update already holds"

UNMASKED: dict[tuple[str, str], str] = {
    ("attachment_service.py", "create"): CALLER_INPUT,
    ("document_service.py", "update"): CALLER_INPUT,
    ("group_service.py", "_write_result"): PARAMETER,
    ("group_service.py", "create"): CALLER_INPUT,
    ("group_service.py", "delete"): CALLER_INPUT,
    ("group_service.py", "update"): CALLER_INPUT,
    ("meeting_agenda_item_service.py", "create"): CALLER_INPUT,
    ("meeting_agenda_item_service.py", "update"): CALLER_INPUT,
    ("meeting_outcome_service.py", "create"): CALLER_INPUT,
    ("meeting_outcome_service.py", "update"): CALLER_INPUT,
    ("meeting_section_service.py", "create"): CALLER_INPUT,
    ("meeting_section_service.py", "update"): CALLER_INPUT,
    ("news_service.py", "_committed"): PARAMETER,
    ("news_service.py", "_delete_outcome"): PARAMETER,
    ("news_service.py", "_preview"): PARAMETER,
    ("news_service.py", "create"): CALLER_INPUT,
    ("news_service.py", "update"): CALLER_INPUT,
    ("recurring_meeting_service.py", "cancel_occurrence"): CALLER_INPUT,
    ("recurring_meeting_service.py", "create"): CALLER_INPUT,
    ("recurring_meeting_service.py", "init_occurrence"): CALLER_INPUT,
    ("recurring_meeting_service.py", "update"): CALLER_INPUT,
    ("relation_service.py", "create"): CALLER_INPUT,
    ("relation_service.py", "update"): CALLER_INPUT,
    ("reminder_service.py", "create"): CALLER_INPUT,
    ("reminder_service.py", "delete"): CALLER_INPUT,
    ("reminder_service.py", "update"): CALLER_INPUT,
    ("storage_service.py", "_write_result"): PARAMETER,
    ("storage_service.py", "create"): CALLER_INPUT,
    ("storage_service.py", "delete"): CALLER_INPUT,
    ("storage_service.py", "update"): CALLER_INPUT,
    ("user_non_working_time_service.py", "create"): CALLER_INPUT,
    ("user_non_working_time_service.py", "delete"): CALLER_INPUT,
    ("user_non_working_time_service.py", "update"): CALLER_INPUT,
    ("user_preferences_service.py", "update"): CALLER_INPUT,
    ("user_working_hours_service.py", "create"): CALLER_INPUT,
    ("user_working_hours_service.py", "delete"): CALLER_INPUT,
    ("user_working_hours_service.py", "update"): CALLER_INPUT,
    ("wiki_page_link_service.py", "create"): CALLER_INPUT,
    ("wiki_page_link_service.py", "delete"): CALLER_INPUT,
    ("work_package_service.py", "add_comment"): CALLER_INPUT,
    ("work_package_service.py", "update"): INTERNAL_HELPER,
}


def _masked_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in MASKERS


def _calls_a_masker(function: ast.AST) -> bool:
    return any(_masked_call(node) for node in ast.walk(function))


def _enclosing(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _unmasked_sites() -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for path in sorted(SERVICES.glob("*.py")):
        tree = ast.parse(path.read_text())
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        write_result_masks = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_write_result"
            and _calls_a_masker(node)
            for node in ast.walk(tree)
        )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "payload":
                    continue
                value, callee, function = keyword.value, ast.unparse(node.func), _enclosing(node, parents)
                if _masked_call(value) or ast.unparse(value).endswith("outcome.payload"):
                    continue
                if callee == "_finalize_write" or (callee == "self._write_result" and write_result_masks):
                    continue
                if isinstance(value, ast.Name) and function is not None:
                    assigned = [
                        n
                        for n in ast.walk(function)
                        if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == value.id for t in n.targets)
                    ]
                    if assigned and all(_masked_call(n.value) for n in assigned):
                        continue
                sites.add((path.name, function.name if function else "<module>"))
    return sites


def test_every_payload_of_a_write_result_is_masked_or_listed_with_its_reason() -> None:
    assert _unmasked_sites() == set(UNMASKED)


def test_every_listed_site_has_one_of_the_stated_reasons() -> None:
    assert set(UNMASKED.values()) <= {CALLER_INPUT, PARAMETER, INTERNAL_HELPER}


def test_the_shared_write_state_machine_and_the_user_result_call_the_masker() -> None:
    for module, name in (("_write_outcome.py", "_finalize_write"), ("user_service.py", "_write_result")):
        tree = ast.parse((SERVICES / module).read_text())
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ]
        assert functions and all(_calls_a_masker(function) for function in functions), f"{module}:{name}"
