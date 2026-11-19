"""Every `payload=` of a write result shows no value of a hidden field.

The payload of a write result is built from the server's form answer (masked by `shown_payload` in
`_finalize_write`, in the user result and in the project copy), from a record the service read (a delete preview:
`record_payload`), or from what the caller passed in. This scan reads the services' source and requires that every
`payload=` keyword argument is one of:

- a call of `shown_payload` or `record_payload`, or a local name whose every assignment in the same function is such a call;
- `outcome.payload` of `_finalize_write`, or the argument of `_finalize_write` itself (masked inside it);
- the argument of `self._write_result` in a module whose `_write_result` calls `shown_payload`;
- a site listed in `UNMASKED` with its reason, keyed by (module, function, payload expression; a local name is replaced
  by the expressions assigned to it in that function), which a stale row fails and which a changed expression fails.

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

UNMASKED: dict[tuple[str, str, str], str] = {
    ("_work_package_target.py", "resolved_target", "record.payload"): CALLER_INPUT,
    ("_work_package_target.py", "write_target", "record.payload"): CALLER_INPUT,
    ("attachment_service.py", "_upload", "{}"): CALLER_INPUT,
    ("document_service.py", "update", "{}"): CALLER_INPUT,
    ("relation_service.py", "create", "await self._work_package_lookup_api.get(source_ref)"): CALLER_INPUT,
    (
        "time_entry_service.py",
        "create",
        "await self._work_package_lookup_api.get(work_package_reference)",
    ): CALLER_INPUT,
    ("user_non_working_time_service.py", "_commit", "p"): CALLER_INPUT,
    ("user_preferences_service.py", "update", "{}"): CALLER_INPUT,
    ("user_working_hours_service.py", "_commit", "p"): CALLER_INPUT,
    (
        "work_package_service.py",
        "add_comment",
        "{'comment': {'raw': comment}, 'internal': internal, 'notify': notify}",
    ): CALLER_INPUT,
    (
        "work_package_service.py",
        "update",
        "await self._build_write_payload(project=str(project_id), type=type, subject=subject, description=description, version=version, target_versions=target_versions, observed_in_versions=observed_in_versions, sprint=sprint, project_phase=project_phase, status=status, assignee=assignee, responsible=responsible, priority=priority, category=category, custom_fields=custom_fields, parent_work_package_id=parent_work_package_id, start_date=start_date, due_date=due_date, estimated_time=estimated_time, remaining_time=remaining_time, duration=duration, percentage_done=percentage_done, work_package_id=ref, lock_version=lock_version, resolution_context=wp_context)",
    ): INTERNAL_HELPER,
    ("work_package_service.py", "update_comment", "{'comment': comment}"): CALLER_INPUT,
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


def _assignments(name: str, function: ast.AST) -> list[ast.expr]:
    values: list[ast.expr] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            values.append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            values.append(node.value)
    return values


def _assigned_values(name: str, function: ast.AST) -> list[str]:
    return sorted({ast.unparse(value) for value in _assignments(name, function)})


def _unmasked_sites() -> set[tuple[str, str, str]]:
    sites: set[tuple[str, str, str]] = set()
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
                if _masked_call(value) or ast.unparse(value) == "outcome.payload":
                    continue
                if callee == "_finalize_write" or (callee == "self._write_result" and write_result_masks):
                    continue
                if isinstance(value, ast.Name) and function is not None:
                    assigned = _assignments(value.id, function)
                    if assigned and all(_masked_call(n) for n in assigned):
                        continue
                shown = ast.unparse(value)
                if isinstance(value, ast.Name) and function is not None:
                    shown = " | ".join(_assigned_values(value.id, function)) or shown
                sites.add((path.name, function.name if function else "<module>", shown))
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


def test_no_write_result_carries_a_record_without_the_stamp() -> None:
    """`result=` of a write result takes a stamped record. The stamp lists the hidden fields of the record and the
    presentation leaves them out; a record handed over as read (`current.summary`, `record.to_detail()`) shows
    every value. The scan reads constructor keywords only, like the guard above, and judges a value that is a record
    accessor (`x.summary`, `x.detail`, `x.to_detail()`), or a local name one assignment of which is one; the argument
    of `self._write_result` is exempt in a module whose `_write_result` calls `self._stamp` itself. A record built by
    a model constructor, or a stamp lost on the way through a helper, is outside it."""

    def accessor(value: ast.expr) -> bool:
        if ast.unparse(value) == "outcome.detail":
            # The detail `_finalize_write` hands back is the record the service stamped before it passed it in
            # (`preview_detail`, the committed value); the runtime scan checks that the shown record drops every
            # hidden key (`result keeps the hidden key`).
            return False
        callee = value.func if isinstance(value, ast.Call) else value
        return isinstance(callee, ast.Attribute) and callee.attr in {"summary", "detail", "to_detail"}

    unstamped: list[tuple[str, int, str]] = []
    for path in sorted(SERVICES.glob("*.py")):
        tree = ast.parse(path.read_text())
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        write_result_stamps = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_write_result"
            and any(isinstance(call, ast.Call) and ast.unparse(call.func) == "self._stamp" for call in ast.walk(node))
            for node in ast.walk(tree)
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if write_result_stamps and ast.unparse(node.func) == "self._write_result":
                continue
            for keyword in node.keywords:
                if keyword.arg != "result":
                    continue
                value, function = keyword.value, _enclosing(node, parents)
                judged = [value]
                if isinstance(value, ast.Name) and function is not None:
                    judged = _assignments(value.id, function)
                if any(accessor(item) for item in judged):
                    unstamped.append((path.name, keyword.value.lineno, ast.unparse(value)))
    assert unstamped == []
