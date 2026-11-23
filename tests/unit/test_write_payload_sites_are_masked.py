"""Every `payload=` of a write result shows no value of a hidden field.

The payload of a write result is built from the server's form answer (masked by `shown_payload` in
`_finalize_write`, in the user result and in the project copy), from a record the service read (a delete preview:
`record_payload`), or from what the caller passed in. This scan reads the package's source and requires that every
`payload=` keyword argument of a call of a result class, of `dataclasses.replace` or of a function that forwards to
one is one of:

- a call of `shown_payload` or `record_payload`, or a local name whose every assignment in the same function is such
  a call;
- `outcome.payload` of `_finalize_write`, or the argument of `_finalize_write` itself (masked inside it);
- the argument of `self._write_result` in a module whose `_write_result` calls `shown_payload`;
- a site listed in `UNMASKED` with its reason, keyed by (module, function, payload expression; a local name is
  replaced by the expressions assigned to it in that function and by everything the function stores into it, hands
  it to, or stores into it through another name), which a stale row fails and which a changed expression, or one
  more value stored into the dict, fails.

The result classes are found, not listed: every class of `models.py` or of `app/services/` that declares a `payload`
field, and every class that derives from one. A function forwards to one when it has a `payload` parameter and passes
a `payload=` keyword to a result class or to another forwarder (a fixpoint over the whole package), so a new helper
between a service and a result class turns its own callers into sites; a forwarder takes `payload` keyword-only, so
no call passes it positionally. Two more rules close what the keyword scan alone cannot see:

- rule A: a result class is called with keywords only, and a `**` expansion into one that carries no `payload=` of its
  own (the payload could arrive inside the mapping) is listed in `EXPANSIONS` with its reason;
- rule B: a store to an attribute named `payload` (also through `setattr`), an item assignment, `del`, an augmented
  assignment, or a mutating call (`update`, `pop`, `setdefault`, `clear`, `popitem`, `append`, `extend`, `insert`,
  `remove`) on `<x>.payload` or on a name bound to a masker result or to a `.payload` (an alias or a part of one, at
  any depth of subscripts, also inside a function that holds the binding) is listed in `MUTATIONS` with its reason (a
  payload changed after the mask).

The planted-source cases at the end keep each rule from passing on an empty match set, and the floors count the result
classes and the construction sites the scan sees.

Stated limit: a payload that reaches a result class through a variable the scan cannot follow (a value built in
another module and passed as `payload=` is judged by its expression only), a base class named other than by a plain
name (`models.X`, `Base[T]`), a tuple-unpacking binding of a masked payload, and the `result=` scan below (a record
built by a model constructor, a stamp lost in a helper; it reads `app/services/` only) are outside it; the golden
tests (`test_write_payload_hidden_fields.py`) and the delete matrix (`test_delete_preview_hidden_fields.py`) cover
those by running the tools.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

import openproject_ce_mcp

PACKAGE = Path(openproject_ce_mcp.__file__).parent
SERVICES = PACKAGE / "app" / "services"
MASKERS = {"shown_payload", "record_payload"}
RESULT_CLASS_MODULES = ("models.py", "app/services/")

CALLER_INPUT = "the payload holds only the caller's own input, no value read from a form answer or a record"
REQUEST_BODY = (
    "the payload is the request body of the write (hrefs of resolved ids, the caller's own values): "
    "the caller sees only the masked form answer"
)
WRITABLE_ONLY = (
    "the payload holds the values of fields the call writes, each checked writable first, so a hidden field never reaches it "
    "(an edit of a stored text is shown only for a writable field)"
)
STAMPED = "the payload holds the caller's own input; `stamp_result` leaves out the copies of hidden fields afterwards"

UNMASKED: dict[tuple[str, str, str], str] = {
    (
        "app/services/document_service.py",
        "update",
        "_stored_text_edit.edit_stored_field('document', 'description', (current.payload.get('description') or {}).get('raw'), description, description_append, description_replace, settings=self._settings)"
        " | payload['description'] = description | payload['title'] = title"
        " | self._api.commit_update(document_id, payload) | {}",
    ): WRITABLE_ONLY,
    (
        "app/services/project_service.py",
        "_build_write_payload",
        "apply_custom_fields(payload, links, schema, custom_fields, subject='project', settings=self._settings, resource_links=self._resource_links, check=self._references_allowed)"
        " | links['parent'] = {'href': None}"
        " | links['parent'] = {'href': _api_href(f'projects/{parent_summary.id}', api_prefix=self._api_prefix)}"
        " | links['status'] = {'href': self._resolve_status_href(schema, status)}"
        " | payload['_links'] = links | payload['active'] = active"
        " | payload['description'] = {'format': 'markdown', 'raw': description}"
        " | payload['identifier'] = identifier | payload['name'] = name | payload['public'] = public"
        " | payload['statusExplanation'] = {'format': 'markdown', 'raw': status_explanation}"
        " | self._api.get_copy_schema(copy_of, draft_payload=payload)"
        " | self._api.get_schema(project_id=project_id, draft_payload=payload, custom_field_options=bool(custom_fields) and copy_of is None)"
        " | {}",
    ): REQUEST_BODY,
    (
        "app/services/user_preferences_service.py",
        "update",
        "payload['autoHidePopups'] = auto_hide_popups | payload['commentSortDescending'] = comment_sort_descending"
        " | payload['timeZone'] = time_zone | payload['warnOnLeavingUnsaved'] = warn_on_leaving_unsaved"
        " | self._api.commit_update(payload) | {}",
    ): CALLER_INPUT,
    (
        "app/services/work_package_service.py",
        "add_comment",
        "{'comment': {'raw': comment}, 'internal': internal, 'notify': notify}",
    ): CALLER_INPUT,
    ("app/services/work_package_service.py", "update_comment", "{'comment': comment}"): CALLER_INPUT,
    (
        "app/services/attachment_service.py",
        "_upload",
        "committed_payload['description'] = description"
        " | committed_payload['fileName'] = confirmed_file_info.file_name"
        " | committed_payload['fileSize'] = len(confirmed_file_info.file_bytes) | {}",
    ): STAMPED,
}


# (module, function, the mapping expanded with `**`) -> why the payload cannot arrive inside it.
EXPANSIONS: dict[tuple[str, str, str], str] = {}

# (module, function, the store or mutating call) -> why a payload changed after construction is safe.
MUTATIONS: dict[tuple[str, str, str], str] = {
    ("app/services/_payload_masking.py", "stamp_result", "result.payload"): (
        "the stamp itself: it replaces the payload of a result by the one without the copies of hidden values"
    ),
}

MIN_RESULT_CLASSES = 31
MIN_CONSTRUCTIONS = 49


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


_MUTATING = {"update", "pop", "setdefault", "clear", "popitem", "append", "extend", "insert", "remove"}
_UNWRAPPED = {"get", "setdefault"}


def _is_payload_attribute(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "payload"


def _is_payload_getattr(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and ast.unparse(node.args[1]) == "'payload'"
    )


def _root(node: ast.AST) -> ast.AST:
    """The value a subscript or a `.get(...)` reads from: `shown['_links']` and `shown.get('_links')` are parts of
    `shown`, so a change of the part is a change of the payload."""
    while True:
        if isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _UNWRAPPED:
            node = node.func.value
        else:
            return node


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _puts_into(name: str, function: ast.AST, targets: set[str], seen: frozenset[str] = frozenset()) -> set[str]:
    """What the function does with the dict held by `name` besides building it: an item store, a mutating call, an
    augmented assignment and any other call that receives it (except a call of a result class, a forwarder or
    `replace`, which is the site). A name stored into the dict (`payload['_links'] = links`) is followed the same way."""
    found: set[str] = set()
    stored: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Subscript) and _is_name(_root(target), name):
                    found.add(f"{ast.unparse(target)} = {ast.unparse(node.value)}")
                    if isinstance(node.value, ast.Name):
                        stored.add(node.value.id)
                elif isinstance(node, ast.AugAssign) and _is_name(target, name):
                    found.add(f"{name} {ast.unparse(node.op)}= {ast.unparse(node.value)}")
        elif isinstance(node, ast.Call) and _callee(node) not in targets:
            receives = any(_is_name(argument, name) for argument in (*node.args, *(k.value for k in node.keywords)))
            changes = (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in _MUTATING
                and _is_name(_root(node.func.value), name)
            )
            if receives or changes:
                found.add(ast.unparse(node))
    for other in stored - seen - {name}:
        found |= _puts_into(other, function, targets, seen | {name})
    return found


def _site_expression(name: str, function: ast.AST, targets: set[str]) -> str:
    """A name-valued payload is keyed by everything the function puts into it, so a record value stored into the dict
    later changes the key and fails the listed row."""
    assigned = {ast.unparse(value) for value in _assignments(name, function)}
    return " | ".join(sorted(assigned | _puts_into(name, function, targets)))


@functools.cache
def _package_trees() -> dict[str, ast.Module]:
    return {path.relative_to(PACKAGE).as_posix(): ast.parse(path.read_text()) for path in sorted(PACKAGE.rglob("*.py"))}


def _callee(node: ast.Call) -> str:
    function = node.func
    return (
        function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""
    )


def _result_classes(trees: dict[str, ast.Module]) -> set[str]:
    """The classes that declare a `payload` field in `models.py` or `app/services/`, and every class that derives from
    one: the write results and the internal outcome carriers. A record of a port (`WorkPackageRecord.payload`, the
    server's own answer) is not one."""
    declared: set[str] = set()
    derived: list[ast.ClassDef] = []
    for module, tree in trees.items():
        if not module.startswith(RESULT_CLASS_MODULES):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            derived.append(node)
            if any(
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id == "payload"
                for statement in node.body
            ):
                declared.add(node.name)
    changed = True
    while changed:
        changed = False
        for node in derived:
            if node.name not in declared and any(ast.unparse(base) in declared for base in node.bases):
                declared.add(node.name)
                changed = True
    return declared


def _has_payload_parameter(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    arguments = function.args
    return any(argument.arg == "payload" for argument in (*arguments.args, *arguments.kwonlyargs))


def _forwarders(trees: dict[str, ast.Module], classes: set[str]) -> set[str]:
    """Functions with a `payload` parameter that pass a `payload=` keyword to a result class or to another forwarder
    (a fixpoint, by function name over the whole package)."""
    functions = [
        node
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_payload_parameter(node)
    ]
    forwarders: set[str] = set()
    changed = True
    while changed:
        changed = False
        for function in functions:
            if function.name in forwarders:
                continue
            targets = classes | forwarders
            if any(
                isinstance(call, ast.Call)
                and _callee(call) in targets
                and any(keyword.arg == "payload" for keyword in call.keywords)
                for call in ast.walk(function)
            ):
                forwarders.add(function.name)
                changed = True
    return forwarders


def _takes_payload_by_keyword_only(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    arguments = function.args
    return not any(argument.arg == "payload" for argument in (*arguments.posonlyargs, *arguments.args))


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _unmasked_sites(trees: dict[str, ast.Module], classes: set[str], forwarders: set[str]) -> set[tuple[str, str, str]]:
    sites: set[tuple[str, str, str]] = set()
    # `dataclasses.replace(outcome, payload=...)` swaps the payload of a result that exists already.
    targets = classes | forwarders | {"replace"}
    for module, tree in trees.items():
        parents = _parents(tree)
        write_result_masks = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_write_result"
            and _calls_a_masker(node)
            for node in ast.walk(tree)
        )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _callee(node) not in targets:
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
                    shown = _site_expression(value.id, function, targets) or shown
                sites.add((module, function.name if function else "<module>", shown))
    return sites


def _expansions(trees: dict[str, ast.Module], classes: set[str]) -> set[tuple[str, str, str]]:
    """Every `**` expansion into a result class that carries no `payload=` keyword of its own."""
    found: set[tuple[str, str, str]] = set()
    for module, tree in trees.items():
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _callee(node) not in classes:
                continue
            if any(keyword.arg == "payload" for keyword in node.keywords):
                continue
            function = _enclosing(node, parents)
            where = function.name if function else "<module>"
            found |= {(module, where, ast.unparse(keyword.value)) for keyword in node.keywords if keyword.arg is None}
    return found


def _rule_a_findings(trees: dict[str, ast.Module], classes: set[str]) -> tuple[set[tuple[str, str, str]], int]:
    """(findings, construction sites): a positional argument into a result class, or a `**` expansion into one that
    carries no `payload=` keyword of its own and is not listed."""
    findings = {
        (module, where, f"expansion: {text}") for module, where, text in _expansions(trees, classes) - set(EXPANSIONS)
    }
    constructions = 0
    for module, tree in trees.items():
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _callee(node) not in classes:
                continue
            constructions += 1
            if node.args:
                function = _enclosing(node, parents)
                findings.add((module, function.name if function else "<module>", f"positional: {_callee(node)}"))
    return findings, constructions


def _masked_names(function: ast.AST) -> set[str]:
    """Names bound to a masked payload, to the `payload` of a result, or to a part or alias of either, in the function
    and every function it holds (a fixpoint: `alias = shown; links = alias['_links']`)."""
    bindings: list[tuple[list[ast.expr], ast.expr]] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            bindings.append((node.targets, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bindings.append(([node.target], node.value))
    names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for targets, value in bindings:
            root = _root(value)
            tracked = (
                _masked_call(value)
                or _is_payload_attribute(root)
                or _is_payload_getattr(root)
                or (isinstance(root, ast.Name) and root.id in names)
            )
            for target in targets:
                if tracked and isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True
    return names


def _masked_in(function: ast.AST, cache: dict[ast.AST, set[str]]) -> set[str]:
    if function not in cache:
        cache[function] = _masked_names(function)
    return cache[function]


def _mutated(base: ast.AST, masked_names: set[str]) -> bool:
    base = _root(base)
    return (
        _is_payload_attribute(base)
        or _is_payload_getattr(base)
        or (isinstance(base, ast.Name) and base.id in masked_names)
    )


def _is_payload_setattr(node: ast.Call) -> bool:
    return _callee(node) in {"setattr", "__setattr__"} and any(
        isinstance(argument, ast.Constant) and argument.value == "payload" for argument in node.args
    )


def _rule_b_findings(trees: dict[str, ast.Module]) -> set[tuple[str, str, str]]:
    """A store to an attribute named `payload` (also through `setattr`), an item assignment, `del` or augmented
    assignment, or a mutating call on `<x>.payload` or on a name bound to a masked payload or to a `payload` (an
    alias or a part of one), at any depth of subscripts."""
    findings: set[tuple[str, str, str]] = set()
    for module, tree in trees.items():
        parents = _parents(tree)
        names_of: dict[ast.AST, set[str]] = {}

        for node in ast.walk(tree):
            chain: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
            function = _enclosing(node, parents)
            while function is not None:
                chain.append(function)
                function = _enclosing(function, parents)
            masked_names = set().union(*(_masked_in(function, names_of) for function in chain))
            where = chain[0].name if chain else "<module>"
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif isinstance(node, ast.Delete):
                targets = list(node.targets)
            for target in targets:
                if _is_payload_attribute(target) or (
                    (isinstance(target, ast.Subscript) or isinstance(node, ast.AugAssign))
                    and _mutated(target, masked_names)
                ):
                    findings.add((module, where, ast.unparse(target)))
            if isinstance(node, ast.Call) and (
                _is_payload_setattr(node)
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in _MUTATING
                    and _mutated(node.func.value, masked_names)
                )
            ):
                findings.add((module, where, ast.unparse(node)))
    return findings


def _scan() -> tuple[dict[str, ast.Module], set[str], set[str]]:
    trees = _package_trees()
    classes = _result_classes(trees)
    return trees, classes, _forwarders(trees, classes)


def test_every_payload_of_a_write_result_is_masked_or_listed_with_its_reason() -> None:
    trees, classes, forwarders = _scan()
    assert _unmasked_sites(trees, classes, forwarders) == set(UNMASKED)


def test_every_listed_site_has_one_of_the_stated_reasons() -> None:
    assert set(UNMASKED.values()) <= {CALLER_INPUT, REQUEST_BODY, STAMPED, WRITABLE_ONLY}


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
    for module, tree in _package_trees().items():
        if not module.startswith("app/services/"):
            continue
        parents = _parents(tree)
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
                    unstamped.append((module, keyword.value.lineno, ast.unparse(value)))
    assert unstamped == []


def test_a_result_class_is_called_with_keywords_and_a_payload_inside_a_mapping_is_listed() -> None:
    trees, classes, _ = _scan()
    findings, _ = _rule_a_findings(trees, classes)

    assert findings == set(), "a result class got a positional argument or an unlisted `**` expansion"
    assert _expansions(trees, classes) >= set(EXPANSIONS), "a listed expansion no longer exists"


def test_a_payload_changed_after_construction_is_listed_with_its_reason() -> None:
    assert _rule_b_findings(_package_trees()) == set(MUTATIONS)
    assert all(MUTATIONS.values())


def test_a_forwarder_takes_its_payload_by_keyword_only_so_no_call_passes_it_positionally() -> None:
    trees, classes, forwarders = _scan()
    positional = sorted(
        f"{module}:{node.name}"
        for module, tree in trees.items()
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in forwarders
        and _has_payload_parameter(node)
        and not _takes_payload_by_keyword_only(node)
    )

    assert positional == []


def test_a_planted_forwarder_with_a_positional_payload_fails_the_keyword_only_rule() -> None:
    tree = ast.parse("def positional(payload, x):\n    pass\ndef keyword(*, payload):\n    pass\n")
    positional, keyword = (node for node in tree.body if isinstance(node, ast.FunctionDef))

    assert not _takes_payload_by_keyword_only(positional)
    assert _takes_payload_by_keyword_only(keyword)


def test_the_scan_sees_the_result_classes_and_their_construction_sites() -> None:
    trees, classes, forwarders = _scan()
    _, constructions = _rule_a_findings(trees, classes)

    assert len(classes) >= MIN_RESULT_CLASSES
    assert constructions >= MIN_CONSTRUCTIONS
    assert {"_finalize_write", "_write_result"} <= forwarders


_PLANTED_MODEL = "from dataclasses import dataclass\n@dataclass\nclass Shown:\n    payload: dict\n    identity: dict\n"


def _planted(source: str) -> tuple[dict[str, ast.Module], set[str]]:
    trees = {"models.py": ast.parse(_PLANTED_MODEL + source)}
    return trees, _result_classes(trees)


def test_a_planted_positional_payload_is_a_rule_a_finding() -> None:
    trees, classes = _planted("def build(form):\n    return Shown(shown_payload(form), {})\n")

    findings, constructions = _rule_a_findings(trees, classes)

    assert constructions == 1
    assert findings == {("models.py", "build", "positional: Shown")}


def test_a_planted_expansion_without_a_payload_keyword_is_a_rule_a_finding() -> None:
    trees, classes = _planted("def build(outcome):\n    return Shown(**outcome.identity)\n")

    findings, _ = _rule_a_findings(trees, classes)

    assert findings == {("models.py", "build", "expansion: outcome.identity")}


def test_a_planted_expansion_next_to_a_payload_keyword_is_no_finding() -> None:
    trees, classes = _planted(
        "def build(outcome, form):\n    return Shown(payload=shown_payload(form), **outcome.identity)\n"
    )

    assert _rule_a_findings(trees, classes)[0] == set()


def test_a_planted_helper_between_a_service_and_a_result_class_turns_its_callers_into_sites() -> None:
    trees, classes = _planted(
        "def helper(payload):\n    return Shown(payload=payload, identity={})\n"
        "def service(form):\n    return helper(payload=form)\n"
    )

    forwarders = _forwarders(trees, classes)

    assert forwarders == {"helper"}
    assert _unmasked_sites(trees, classes, forwarders) == {
        ("models.py", "helper", "payload"),
        ("models.py", "service", "form"),
    }


@pytest.mark.parametrize(
    ("statement", "finding"),
    [
        ("result.payload = {}", "result.payload"),
        ("result.payload['status'] = 'x'", "result.payload['status']"),
        ("result.payload.update({'status': 'x'})", "result.payload.update({'status': 'x'})"),
        ("result.payload.pop('status')", "result.payload.pop('status')"),
        ("del result.payload['status']", "result.payload['status']"),
        ("shown['status'] = 'x'", "shown['status']"),
        ("shown.update({'status': 'x'})", "shown.update({'status': 'x'})"),
        ("shown['_links']['status'] = 'x'", "shown['_links']['status']"),
        ("shown['_links'].pop('status')", "shown['_links'].pop('status')"),
        ("shown |= {'status': 'x'}", "shown"),
        ("alias = result.payload\n    alias['status'] = 'x'", "alias['status']"),
        ("alias = shown\n    alias['status'] = 'x'", "alias['status']"),
        ("links = shown['_links']\n    links['self'] = 'x'", "links['self']"),
        ("links = shown.get('_links')\n    links.update({'self': 'x'})", "links.update({'self': 'x'})"),
        ("shown['items'].append('x')", "shown['items'].append('x')"),
        ("setattr(result, 'payload', {})", "setattr(result, 'payload', {})"),
        ("getattr(result, 'payload').update({'status': 'x'})", "getattr(result, 'payload').update({'status': 'x'})"),
        ("def later():\n        shown['status'] = 'x'", "shown['status']"),
    ],
)
def test_a_planted_change_of_a_payload_after_construction_is_a_rule_b_finding(statement: str, finding: str) -> None:
    trees = {"planted.py": ast.parse(f"def build(form, result):\n    shown = shown_payload(form)\n    {statement}\n")}

    assert {text for _, _, text in _rule_b_findings(trees)} == {finding}


def test_a_class_that_derives_from_a_result_class_is_one_too() -> None:
    trees = {"models.py": ast.parse(_PLANTED_MODEL + "class Derived(Shown):\n    extra: int = 0\n")}

    assert _result_classes(trees) == {"Shown", "Derived"}


def test_a_planted_replace_of_a_payload_is_a_site() -> None:
    trees, classes = _planted(
        "from dataclasses import replace\ndef build(outcome, extra):\n    return replace(outcome, payload=extra)\n"
    )

    assert _unmasked_sites(trees, classes, set()) == {("models.py", "build", "extra")}
