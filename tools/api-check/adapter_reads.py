"""Which keys of an OpenProject response body the client reads, and from where in the body.

A small abstract interpreter over the source tree. A value is a set of origins, an origin is a root (a function
parameter bound to a body, the result of a transport call or a JSON decode, a body-carrying record field) and the path
from that root (`("_links", "project")`). `.get("k")`, `["k"]` and `"k" in x` on a value with an origin are reads.
What the model cannot follow is reported where it happens: a call into code it does not know with a body as argument,
a body in a literal container or on `self`, a dynamic key, `.items()` is `unresolved`; a read on a value whose origin
was lost is `unclassified`; a function that reads a parameter no caller or row binds to a body is `unbound`.

The functions of a source tree are summarised once, symbolically (parameters are `p:<name>` roots, a lost value is
`u:<name>` or `?`). A call instantiates the summary of its callee with the origins of its arguments, so a helper
(`link_title(x)`) is checked per caller and never merged across callers. A function in `terminals` (a normalizer whose
parameters a row binds to a body) keeps its own reads and passes none upward.

Limits, stated on purpose (each is a finding or a documented gap, never a silent default):
- Types come from annotations. A parameter or return declared as a class of the package is an object, not a body; a
  declared scalar keeps the provenance of what was handed to it, because an `Any` value may have been. A body stored in a
  declared scalar field of a record ends there: a record is a boundary, only its body-carrying fields are sources.
- A call of a function that is not in the package returns no origin, except the JSON decode entry points (`json.loads`,
  `.json()`); a body that enters through any other external call is invisible.
- A body held on `self` or in a container is reported where it is stored; reads of it elsewhere are not followed.
- A function that returns a tuple literal hands the union of its members to an unpacking caller (position is not
  tracked), so a member that is not a body can show a spurious read; WP2b waives those with a reason. A local list, dict
  or set that `.extend`, `.append`, `.add`, `.insert` or `.update` fill holds what was added; any other object that is
  handed a body is reported.
- Control flow is not followed (an assignment joins into the variable's origins), so a read is attributed to every
  origin the receiver may have; loops settle by a fixpoint, and a function whose assignments do not settle is opaque.
- Paths are cut at depth 8, above the deepest path the client reads today (7: a work-package form schema down to the
  `projects` link of an allowed activity), not at the planned 4, which would cut real reads. A loop that walks down a
  body (`node = node.get("members")`) never settles and is reported as opaque.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import wire_sources
from wire_sources import holds_body

Origin = tuple[str, tuple[str, ...]]
Value = frozenset[Origin]
NONE: Value = frozenset()
UNKNOWN_ROOT = "?"
UNKNOWN: Value = frozenset({(UNKNOWN_ROOT, ())})

_BUILTIN_COPIES = frozenset({"dict", "list", "tuple", "set", "sorted", "reversed", "iter", "filter"})
_BUILTIN_ELEMENT = frozenset({"next", "max", "min"})  # the result is one element of what they are given
_BUILTIN_PLAIN = frozenset(
    {"isinstance", "len", "str", "int", "float", "bool", "bytes", "repr", "any", "all", "sum", "abs"}
    | {"round", "range", "print", "type", "id", "hash", "callable", "issubclass", "ord", "chr", "format", "divmod"}
)
# Standard-library functions that take a string or an object and never a mapping: a body handed to one is a leaf,
# nothing is read from it. Matched by the fully qualified name the call was imported from, so a package function, a
# third-party function or a parameter of the same name is not taken for one.
_STRING_FUNCTIONS = frozenset(
    {f"urllib.parse.{name}" for name in ("urlsplit", "urlparse", "quote", "unquote", "quote_plus", "unquote_plus")}
    | {f"urllib.parse.{name}" for name in ("parse_qsl", "parse_qs", "urljoin", "urlunsplit")}
    | {"dataclasses.is_dataclass", "datetime.datetime.fromisoformat", "datetime.date.fromisoformat"}
)
_REGEX_METHODS = frozenset({"fullmatch", "match", "search", "sub", "subn", "findall", "finditer"})
_STRING_METHODS = frozenset(
    {"strip", "lstrip", "rstrip", "startswith", "endswith", "split", "rsplit", "lower", "upper", "replace", "join"}
    | {"isdigit", "isalpha", "isalnum", "encode", "decode", "removeprefix", "removesuffix", "partition"}
    | {"rpartition", "splitlines", "title", "casefold", "count", "find", "rfind", "index", "zfill", "isnumeric"}
    | {"capitalize", "center", "ljust", "rjust", "expandtabs", "translate", "swapcase", "istitle"}
    | {"isupper", "islower", "isspace", "isprintable", "isascii", "isdecimal", "isidentifier", "maketrans", "isoformat"}
)
# Functions whose result is the result of the callable they are given as the first argument (`call_version_gated`
# awaits it and translates a 404; it returns what the callable returned).
HIGHER_ORDER_RESULT = frozenset({"call_version_gated", "call_query_version_gated"})
_DYNAMIC_ITERATION = frozenset({"items", "keys", "values"})
_MAX_PASSES = 12
_MAX_PATH = 8  # a body nested deeper than any representer is cut and reported
# Member names that are a dict method or a callable's: on a receiver of unknown type they say nothing about a record.
_AMBIGUOUS_MEMBER_NAMES = frozenset({"get", "__call__", "update_comment"})
_MUTATING = frozenset({"update", "setdefault", "pop", "popitem", "append", "extend", "insert", "remove", "clear"})


class Read(NamedTuple):
    context: str
    line: int
    root: str
    path: tuple[str, ...]
    key: str
    how: str  # "get", "sub" or "in"


class Finding(NamedTuple):
    kind: str  # "unresolved", "unclassified", "unbound" or "unsupported"
    context: str
    line: int
    reason: str
    parameters: tuple[str, ...] = ()  # the parameters whose binding decides whether this finding applies


class Analysis(NamedTuple):
    reads: dict[str, list[Read]]
    findings: list[Finding]


def _lost(root: str) -> bool:
    return root == UNKNOWN_ROOT or root.startswith("u:")


def _unknown_from(value: Value) -> Value:
    """The origin of a result the model could not follow: it stays tied to the parameters it came from, so a helper
    that loses a value only counts against the callers that bind a body to that parameter."""
    result: set[Origin] = set()
    for root, _ in value:
        if root[:2] in {"p:", "k:"}:
            result.add((f"u:{root[2:]}", ()))
        elif root.startswith("u:"):
            result.add((root, ()))
        else:
            result.add((UNKNOWN_ROOT, ()))
    return frozenset(result)


def _parameters(value: Value) -> tuple[str, ...]:
    return tuple(sorted({root[2:] for root, _ in value if root[:2] in {"p:", "u:", "k:"}}))


def _concrete(value: Value) -> bool:
    return any(root[:2] not in {"p:", "u:", "k:"} for root, _ in value)


def _is_mapping_path(path: tuple[str, ...]) -> bool:
    """Is a body at this path certainly a dict, so that `"k" in x` tests a key and not a substring?"""
    return not path or path[-1] in {"_links", "_embedded", "*"} or (len(path) == 2 and path[0] == "_links")


def _is_leaf_path(path: tuple[str, ...]) -> bool:
    """`href` and `title` of a link are strings by the shape of a link object: a membership test on them is a substring test."""
    return len(path) >= 3 and path[0] == "_links" and path[-1] in {"href", "title"}


def _union(values: Iterable[Value]) -> Value:
    result: Value = NONE
    for value in values:
        result |= value
    return result


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _all_args(function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.arg]:
    args = function.args
    return [*args.posonlyargs, *args.args, *args.kwonlyargs]


_WRAPPERS = frozenset({"Awaitable", "Coroutine", "Optional", "Annotated", "Final", "ClassVar"})
_SEQUENCES = frozenset(
    {"list", "List", "Sequence", "Iterable", "Iterator", "tuple", "Tuple", "set", "frozenset", "AsyncIterator"}
)


def annotation_tuple(annotation: ast.expr | None) -> list[str]:
    """The class of each element of a `tuple[A, B]` annotation (wrappers like `Awaitable` and `Optional` looked through)."""
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return annotation_tuple(ast.parse(annotation.value, mode="eval").body)
        except SyntaxError:
            return []
    if not isinstance(annotation, ast.Subscript):
        return []
    head = annotation.value.id if isinstance(annotation.value, ast.Name) else getattr(annotation.value, "attr", "")
    inner = annotation.slice
    if head in _WRAPPERS:
        return annotation_tuple(inner.elts[0] if isinstance(inner, ast.Tuple) else inner)
    if head in {"tuple", "Tuple"} and isinstance(inner, ast.Tuple):
        return [annotation_type(element) for element in inner.elts]
    return []


def annotation_type(annotation: ast.expr | None) -> str:
    """`X` for a class, `list:X` for a sequence of X, an empty string when the annotation names no class."""
    if annotation is None:
        return ""
    if isinstance(annotation, ast.Name):
        return (
            annotation.id
            if annotation.id not in {"None", "Any", "str", "int", "float", "bool", "bytes", "dict"}
            else ""
        )
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return annotation_type(ast.parse(annotation.value, mode="eval").body)
        except SyntaxError:
            return ""
    if isinstance(annotation, ast.BinOp):
        left, right = annotation_type(annotation.left), annotation_type(annotation.right)
        return left if left == right or not right else right if not left else ""
    if isinstance(annotation, ast.Subscript):
        head = annotation_type(annotation.value)
        inner = annotation.slice
        if head in _WRAPPERS:
            return annotation_type(inner.elts[0] if isinstance(inner, ast.Tuple) else inner)
        if head in _SEQUENCES:
            element = annotation_type(inner.elts[0] if isinstance(inner, ast.Tuple) else inner)
            return f"list:{element}" if element else ""
        if head == "Callable" and isinstance(inner, ast.Tuple) and len(inner.elts) == 2:
            return f"call:{annotation_type(inner.elts[1])}"
    return ""


class _Module:
    def __init__(self, rel: str, tree: ast.Module) -> None:
        self.rel = rel
        self.tree = tree
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        self.methods: dict[str, dict[str, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
        self.imports: dict[str, tuple[str, str | None]] = {}  # local name -> (module rel, name or None for a module)
        self.external: set[str] = set()  # names imported from outside the package
        self.external_origin: dict[str, str] = {}  # local name -> "module.name" it was imported as
        self.aliases: dict[str, str] = {}  # `A = B` at module level
        self.import_aliases: dict[str, str] = {}  # `from x import A as B`: B -> A
        self.patterns: set[str] = set()  # module-level `NAME = re.compile(...)`
        self.attribute_types: dict[str, dict[str, str]] = {}  # class -> attribute -> type
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
            elif isinstance(node, ast.ClassDef):
                self.classes[node.name] = node
                self.methods[node.name] = {
                    n.name: n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                self.attribute_types[node.name] = self._attribute_types(node)
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                self._module_assignment(node.targets[0].id, node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                self._module_assignment(node.target.id, node.value)

    def _module_assignment(self, name: str, value: ast.expr) -> None:
        if isinstance(value, ast.Name):
            self.aliases[name] = value.id
        elif isinstance(value, ast.Call) and ast.unparse(value.func) in {"re.compile", "compile"}:
            self.patterns.add(name)

    @staticmethod
    def _attribute_types(cls: ast.ClassDef) -> dict[str, str]:
        types: dict[str, str] = {}
        for node in cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                types[node.target.id] = annotation_type(node.annotation)
        init = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
        if init is not None:
            parameter_types = {a.arg: annotation_type(a.annotation) for a in _all_args(init) if a.annotation}
            for node in ast.walk(init):
                target = value = annotation = None
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    target, value = node.targets[0], node.value
                elif isinstance(node, ast.AnnAssign):
                    target, value, annotation = node.target, node.value, node.annotation
                if not (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    continue
                if annotation is not None and annotation_type(annotation):
                    types[target.attr] = annotation_type(annotation)
                elif isinstance(value, ast.Name) and parameter_types.get(value.id):
                    types[target.attr] = parameter_types[value.id]
        return types


class Index:
    """The functions of a source tree and how names resolve between its modules."""

    def __init__(self, package: Path) -> None:
        self.package = package
        self.modules: dict[str, _Module] = {}
        for path in sorted(package.rglob("*.py")):
            rel = path.relative_to(package).as_posix()
            self.modules[rel] = _Module(rel, ast.parse(path.read_text()))
        self.aliases: dict[str, str] = {}
        for module in self.modules.values():
            self._resolve_imports(module)
        class_names = {name for module in self.modules.values() for name in module.classes}
        self.type_names = wire_sources.type_names(package)
        for name, bound in self.type_names.type_vars.items():
            if isinstance(bound, ast.Name) and bound.id in class_names:
                self.aliases[name] = bound.id
        for module in self.modules.values():
            candidates = {**module.aliases, **module.import_aliases}
            for local, original in candidates.items():
                if original in class_names and self.aliases.get(local, original) != original:
                    raise ValueError(f"the class alias {local!r} names both {self.aliases[local]!r} and {original!r}")
                if original in class_names:
                    self.aliases[local] = original
        self.bases: dict[str, list[str]] = {}
        for module in self.modules.values():
            for name, cls in module.classes.items():
                self.bases[name] = [annotation_type(base) for base in cls.bases if annotation_type(base)]
        self._infer_attribute_types()
        self.raw_attributes = self._raw_attributes()

    def wire_member(self, klass: str, attribute: str, wire_members: set[tuple[str, str]]) -> str:
        """The class, this one or a base, that declares `attribute` as a body-carrying member; empty when none does."""
        klass = self.resolve_class(klass)
        if (klass, attribute) in wire_members:
            return klass
        for base in self.bases.get(klass, []):
            declared = self.wire_member(base, attribute, wire_members)
            if declared:
                return declared
        return ""

    def _raw_attributes(self) -> dict[str, set[str]]:
        """Attributes of a plain class that are declared as able to hold a body (a record's fields are in the census)."""
        found: dict[str, set[str]] = {}
        for module in self.modules.values():
            for name, cls in module.classes.items():
                if any(
                    token in ast.unparse(node)
                    for node in (*cls.bases, *cls.decorator_list)
                    for token in ("Protocol", "dataclass", "TypedDict", "NamedTuple")
                ):
                    continue
                attributes: set[str] = set()
                for node in cls.body:
                    if (
                        isinstance(node, ast.AnnAssign)
                        and isinstance(node.target, ast.Name)
                        and holds_body(node.annotation, self.type_names)
                    ):
                        attributes.add(node.target.id)
                init = module.methods[name].get("__init__")
                if init is not None:
                    parameters = {a.arg: a.annotation for a in _all_args(init)}
                    for node in ast.walk(init):
                        target = value = annotation = None
                        if isinstance(node, ast.AnnAssign):
                            target, value, annotation = node.target, node.value, node.annotation
                        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                            target, value = node.targets[0], node.value
                        if not (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            continue
                        if annotation is None and isinstance(value, ast.Name) and value.id in parameters:
                            annotation = parameters[value.id]
                            if annotation is None:
                                continue
                        if annotation is not None and holds_body(annotation, self.type_names):
                            attributes.add(target.attr)
                if attributes:
                    found[name] = attributes
        return found

    def is_raw_attribute(self, klass: str, attribute: str) -> bool:
        klass = self.resolve_class(klass)
        if attribute in self.raw_attributes.get(klass, ()):
            return True
        return any(self.is_raw_attribute(base, attribute) for base in self.bases.get(klass, []))

    def unsupported(self) -> list[Finding]:
        """Code the model does not analyse, so a read in it would be skipped: a def or class under a module-level
        `if`, `try`, `with` or loop, a class inside a class, `global` and `nonlocal` stores."""
        found: list[Finding] = []
        for rel, module in self.modules.items():
            for node in module.tree.body:
                if isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While, ast.AsyncWith, ast.AsyncFor)):
                    for inner in ast.walk(node):
                        if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            reason = (
                                f"{type(inner).__name__} {inner.name!r} under a module-level statement is not analysed"
                            )
                            found.append(Finding("unsupported", f"{rel}:<module>", inner.lineno, reason))
            for cls in module.classes.values():
                for inner in cls.body:
                    if isinstance(inner, ast.ClassDef):
                        reason = f"class {inner.name!r} nested in a class is not analysed"
                        found.append(Finding("unsupported", f"{rel}:<module>", inner.lineno, reason))
            for node in ast.walk(module.tree):
                if isinstance(node, (ast.Global, ast.Nonlocal)):
                    found.append(
                        Finding(
                            "unsupported", f"{rel}:<module>", node.lineno, "a global or nonlocal store is not followed"
                        )
                    )
        return found

    def resolve_function(self, rel: str, name: str, depth: int = 0) -> tuple[str, str] | None:
        """The module and name of the function a name stands for: defined here, an alias, or re-exported by a package."""
        module = self.modules.get(rel)
        if module is None or depth > 6:
            return None
        if name in module.functions:
            return rel, name
        if name in module.aliases:
            return self.resolve_function(rel, module.aliases[name], depth + 1)
        imported = module.imports.get(name)
        if imported is not None and imported[1] is not None:
            return self.resolve_function(imported[0], imported[1], depth + 1)
        return None

    def _infer_attribute_types(self) -> None:
        """`self.x = factory(...)` has the declared return type of the factory, `self.x = Class(...)` that class."""
        for module in self.modules.values():
            for name in module.classes:
                init = module.methods[name].get("__init__")
                if init is None:
                    continue
                parameter_types = {a.arg: annotation_type(a.annotation) for a in _all_args(init) if a.annotation}
                for node in ast.walk(init):
                    if (
                        isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name)
                        and isinstance(node.targets[0], ast.Attribute)
                        and isinstance(node.targets[0].value, ast.Name)
                        and node.targets[0].value.id == "self"
                        and parameter_types.get(node.value.value.id)
                        and not module.attribute_types[name].get(node.targets[0].attr)
                    ):
                        inherited = self.class_attribute_type(parameter_types[node.value.value.id], node.value.attr)
                        if inherited:
                            module.attribute_types[name][node.targets[0].attr] = inherited
                    if not (
                        isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.value, ast.Call)
                    ):
                        continue
                    target = node.targets[0]
                    if not (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        continue
                    if module.attribute_types[name].get(target.attr) or not isinstance(node.value.func, ast.Name):
                        continue
                    called = node.value.func.id
                    resolved = self.resolve_function(module.rel, called)
                    if resolved is not None:
                        function = self.modules[resolved[0]].functions[resolved[1]]
                        module.attribute_types[name][target.attr] = annotation_type(function.returns)
                    elif self.find_class(called) is not None:
                        module.attribute_types[name][target.attr] = self.resolve_class(called)

    def resolve_class(self, name: str) -> str:
        seen = set()
        while name in self.aliases and name not in seen:
            seen.add(name)
            name = self.aliases[name]
        return name

    def find_class(self, name: str) -> tuple[_Module, ast.ClassDef] | None:
        name = self.resolve_class(name)
        for module in self.modules.values():
            if name in module.classes:
                return module, module.classes[name]
        return None

    def method(self, klass: str, name: str) -> tuple[str, ast.FunctionDef | ast.AsyncFunctionDef] | None:
        """The function id and node of `klass.name`, looked up through the base classes."""
        klass = self.resolve_class(klass)
        found = self.find_class(klass)
        if found is None:
            return None
        module, _ = found
        node = module.methods.get(klass, {}).get(name)
        if node is not None:
            return f"{module.rel}:{klass}.{name}", node
        for base in self.bases.get(klass, []):
            inherited = self.method(base, name)
            if inherited is not None:
                return inherited
        return None

    def is_protocol(self, klass: str) -> bool:
        found = self.find_class(klass)
        return found is not None and any("Protocol" in ast.unparse(base) for base in found[1].bases)

    def known_type(self, kind: str) -> bool:
        if kind.startswith("list:"):
            return self.known_type(kind[5:])
        return kind.startswith("call:") or self.find_class(kind) is not None

    def declared(self, annotation: ast.expr | None) -> str:
        """The class a declaration names, or an empty string for a scalar, a type variable or anything unknown."""
        kind = annotation_type(annotation)
        return kind if kind and self.known_type(kind) else ""

    def class_attribute_type(self, klass: str, attribute: str) -> str:
        found = self._class_attribute_type(klass, attribute)
        return found if found and self.known_type(found) else ""

    def _class_attribute_type(self, klass: str, attribute: str) -> str:
        klass = self.resolve_class(klass)
        found = self.find_class(klass)
        if found is None:
            return ""
        module, _ = found
        known = module.attribute_types.get(klass, {}).get(attribute)
        if known:
            return known
        for base in self.bases.get(klass, []):
            inherited = self._class_attribute_type(base, attribute)
            if inherited:
                return inherited
        return ""

    def _resolve_imports(self, module: _Module) -> None:
        base = Path(module.rel).parent
        for node in ast.walk(module.tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                target = base
                for _ in range(node.level - 1):
                    target = target.parent
                target = target / (node.module or "").replace(".", "/") if node.module else target
                for alias in node.names:
                    local = alias.asname or alias.name
                    if alias.asname and alias.asname != alias.name:
                        module.import_aliases[alias.asname] = alias.name
                    as_module = self._module_for(target / alias.name)
                    if as_module:
                        module.imports[local] = (as_module, None)
                        continue
                    owner = self._module_for(target)
                    if owner:
                        module.imports[local] = (owner, alias.name)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                module.external.update(alias.asname or alias.name for alias in node.names)
                for alias in node.names:
                    module.external_origin[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            elif isinstance(node, ast.Import):
                module.external.update((alias.asname or alias.name).split(".")[0] for alias in node.names)

    def _module_for(self, path: Path) -> str | None:
        for candidate in (f"{path.as_posix()}.py", f"{path.as_posix()}/__init__.py"):
            if candidate in self.modules:
                return candidate
        return None

    def function(self, rel: str, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        module = self.modules.get(rel)
        if module is None:
            return None
        if "." in qualname:
            owner, name = qualname.split(".", 1)
            return module.methods.get(owner, {}).get(name)
        return module.functions.get(qualname)

    def all_functions(self) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
        for rel, module in self.modules.items():
            for name, node in module.functions.items():
                yield f"{rel}:{name}", node
            for owner, methods in module.methods.items():
                for name, node in methods.items():
                    yield f"{rel}:{owner}.{name}", node


class _Summary(NamedTuple):
    params: tuple[str, ...]
    reads: list[Read]
    returns: Value
    findings: list[Finding]
    opaque: bool


class Interpreter:
    def __init__(self, index: Index, *, terminals: Mapping[str, Sequence[str]] | None = None) -> None:
        self.index = index
        self.terminals = {fid: tuple(params) for fid, params in (terminals or {}).items()}
        self.wire_members = wire_sources.wire_members(index.package)
        self.wire_field_names = {
            name for _, name in self.wire_members if "." not in name and name not in _AMBIGUOUS_MEMBER_NAMES
        }
        self.wire_method_names = {
            name for _, name in self.wire_members if "_" in name.strip("_") and name not in _AMBIGUOUS_MEMBER_NAMES
        }
        self.wire_parameters = {
            tuple(name.split(".", 1))
            for owner, name in self.wire_members
            if "." in name  # (method, parameter)
        }
        self._summaries: dict[str, _Summary] = {}
        self._running: list[str] = []
        self._cyclic: set[str] = set()  # functions on a call cycle: no partial summary of them is ever used
        # (callee, parameter) -> what binds it: None for a concrete origin, (caller, parameter) for a symbolic one
        self.bindings: dict[tuple[str, str], set[tuple[str, str] | None]] = {}

    def wired(self, fid: str) -> tuple[str, ...]:
        """The parameters of a function that hold a body by declaration: a row binds them, or the function implements a
        Protocol method whose parameter the sources table declares as a response body."""
        names = list(self.terminals.get(fid, ()))
        _, qualname = fid.split(":", 1)
        if "." in qualname:
            owner, method = qualname.split(".", 1)
            if not self.index.is_protocol(owner):
                function = self.index.function(*fid.split(":", 1))
                assert function is not None
                names += [a.arg for a in _all_args(function) if (method, a.arg) in self.wire_parameters]
        return tuple(dict.fromkeys(names))

    def run(self) -> Analysis:
        reads: dict[str, list[Read]] = {}
        findings: list[Finding] = []
        functions = [fid for fid, _ in self.index.all_functions()]
        for fid in functions:
            summary = self.summary(fid)
            wired = self.wired(fid)
            own = [r for r in summary.reads if r.root[:2] not in {"p:", "k:"} or r.root[2:] in wired]
            if own:
                reads[fid] = own
            findings.extend(
                f._replace(parameters=())
                for f in summary.findings
                if not f.parameters or set(f.parameters) & set(wired)
            )
        bound = {(fid, parameter) for fid in functions for parameter in self.wired(fid)}
        changed = True
        while changed:
            changed = False
            for key, sources in self.bindings.items():
                if key not in bound and any(source is None or source in bound for source in sources):
                    bound.add(key)
                    changed = True
        for fid in functions:
            summary = self.summary(fid)
            if summary.opaque:  # no partial summary of a call cycle is used: every read in it is unresolved
                for read in summary.reads:
                    reason = f"read of {read.key!r} in a function on a call cycle or that never settles"
                    findings.append(Finding("unresolved", fid, read.line, reason))
            for read in summary.reads:
                if read.root[:2] in {"p:", "k:"} and (fid, read.root[2:]) not in bound:
                    reason = f"read of {read.key!r} on parameter {read.root[2:]!r}, which no caller binds to a body"
                    findings.append(Finding("unbound", fid, read.line, reason))
            for finding in summary.findings:
                if finding.kind != "unclassified":  # a read on a value lost from a parameter is a read of it
                    continue
                for parameter in finding.parameters:
                    if (fid, parameter) not in bound:
                        reason = f"{finding.reason}; parameter {parameter!r} is bound by no caller to a body"
                        findings.append(Finding("unbound", finding.context, finding.line, reason))
        findings.extend(self.index.unsupported())
        return Analysis(reads, list(dict.fromkeys(findings)))

    def summary(self, fid: str) -> _Summary:
        if fid in self._summaries:
            return self._summaries[fid]
        rel, qualname = fid.split(":", 1)
        function = self.index.function(rel, qualname)
        if function is None:
            raise KeyError(fid)
        if fid in self._running:
            self._cyclic.update(self._running[self._running.index(fid) :])
            return _Summary((), [], NONE, [], True)  # a caller that passes a body in reports the recursion
        self._running.append(fid)
        try:
            summary = _Frame(self, fid, rel, qualname, function).analyse()
        finally:
            self._running.pop()
        if fid in self._cyclic:
            summary = summary._replace(opaque=True)
        self._summaries[fid] = summary
        return summary


class _Frame:
    def __init__(
        self,
        interpreter: Interpreter,
        fid: str,
        rel: str,
        qualname: str,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self.interpreter = interpreter
        self.index = interpreter.index
        self.fid = fid
        self.rel = rel
        self.module = interpreter.index.modules[rel]
        self.function = function
        self.owner = qualname.split(".", 1)[0] if "." in qualname else None
        self.env: dict[str, Value] = {}
        self.types: dict[str, str] = {}
        self.alternatives: dict[str, set[str]] = {}
        self.containers: set[str] = (
            set()
        )  # locals assigned a list, dict or set: `.extend` and `.append` collect into them
        self.callables: dict[str, Value] = {}  # a nested def or a lambda bound to a name: what calling it returns
        self.reads: list[Read] = []
        self.findings: list[Finding] = []
        self.returns: Value = NONE
        self.skip_first = bool(self.owner) and not any(
            "staticmethod" in ast.unparse(d) for d in function.decorator_list
        )
        self.params = tuple(a.arg for a in _all_args(function)[1 if self.skip_first else 0 :])
        self.call_index: dict[int, int] = {}

    # --- entry ---------------------------------------------------------------------------------------------------

    def analyse(self) -> _Summary:
        arguments = _all_args(self.function)
        if self.skip_first and arguments:
            self.note_type(arguments[0].arg, self.owner or "")
            arguments = arguments[1:]
        for arg in arguments:
            declared = self.index.declared(arg.annotation)
            self.note_type(arg.arg, declared)
            # A parameter declared only as a class of the package is an object, not a body; a scalar, a union with a
            # raw mapping and `Any` keep their provenance because a body may have been handed to them.
            is_object = (
                bool(declared)
                and not declared.startswith(("list:", "call:"))
                and not holds_body(arg.annotation, self.index.type_names)
            )
            self.env[arg.arg] = NONE if is_object else frozenset({(f"p:{arg.arg}", ())})
        settled = False
        declared_types = {name: set(kinds) for name, kinds in self.alternatives.items()}
        for _ in range(_MAX_PASSES):
            # The alternatives of a pass are rebuilt from the declarations, so a type that is unknown only because an
            # earlier assignment had not been reached yet does not stay an alternative.
            self.alternatives = {name: set(kinds) for name, kinds in declared_types.items()}
            before = (dict(self.env), dict(self.types), dict(self.callables), self.returns)
            sizes = (len(set(self.reads)), len(set(self.findings)))
            self.block(self.function.body)
            if before == (self.env, self.types, self.callables, self.returns) and sizes == (
                len(set(self.reads)),
                len(set(self.findings)),
            ):
                settled = True
                break
        if not settled:
            self.findings.append(Finding("unresolved", self.fid, self.function.lineno, "assignments did not settle"))
        reads = list(dict.fromkeys(self.reads))
        returned = self.index.declared(self.function.returns)
        if (
            returned
            and not returned.startswith(("list:", "call:"))
            and not holds_body(self.function.returns, self.index.type_names)
        ):
            self.returns = NONE
        return _Summary(self.params, reads, self.returns, list(dict.fromkeys(self.findings)), not settled)

    # --- findings ------------------------------------------------------------------------------------------------

    def unresolved(self, node: ast.AST, reason: str, receiver: Value = NONE) -> Value:
        """Report what the model cannot follow and give the result an unknown origin, so later reads are reported too."""
        line = getattr(node, "lineno", 0)
        if _concrete(receiver) or not receiver:
            self.findings.append(Finding("unresolved", self.fid, line, reason))
        else:
            self.findings.append(Finding("unresolved", self.fid, line, reason, _parameters(receiver)))
        return _unknown_from(receiver)

    def read(self, node: ast.AST, receiver: Value, key: str, how: str) -> Value:
        result: set[Origin] = set()
        for root, path in receiver:
            if len(path) >= _MAX_PATH:
                self.findings.append(
                    Finding(
                        "unresolved", self.fid, getattr(node, "lineno", 0), f"read of {key!r} below the path depth cap"
                    )
                )
                result.add((UNKNOWN_ROOT, ()))
                continue
            if _lost(root):
                parameters = (root[2:],) if root.startswith("u:") else ()
                self.findings.append(
                    Finding(
                        "unclassified",
                        self.fid,
                        getattr(node, "lineno", 0),
                        f"read of {key!r} on a value of unknown origin",
                        parameters,
                    )
                )
                result.add((root, ()))
                continue
            self.reads.append(Read(self.fid, getattr(node, "lineno", 0), root, path, key, how))
            result.add((root, (*path, key)))
        return frozenset(result)

    # --- statements ----------------------------------------------------------------------------------------------

    def block(self, body: list[ast.stmt]) -> None:
        for statement in body:
            self.stmt(statement)

    def stmt(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Assign):
            value = self.ev(node.value)
            for target in node.targets:
                self.assign(target, value, node.value)
        elif isinstance(node, ast.AnnAssign):
            declared = self.index.declared(node.annotation) if isinstance(node.target, ast.Name) else ""
            if node.value is not None:
                self.assign(node.target, self.ev(node.value), node.value, note=not declared)
            if isinstance(node.target, ast.Name) and declared:
                self.note_type(node.target.id, declared)
        elif isinstance(node, ast.AugAssign):
            value = self.ev(node.value)
            if isinstance(node.target, ast.Name):
                self.env[node.target.id] = self.env.get(node.target.id, NONE) | value
            else:
                self.assign(node.target, value | self.ev(node.target), node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            iterable = self.ev(node.iter)
            element = self.element_of(iterable, node.iter)
            kind = self.type_of(node.iter)
            self.bind(node.target, element, kind[5:] if kind.startswith("list:") else "")
            for _ in range(2):
                self.block(node.body)
            self.block(node.orelse)
        elif isinstance(node, ast.While):
            self.ev(node.test)
            for _ in range(2):
                self.block(node.body)
            self.block(node.orelse)
        elif isinstance(node, ast.If):
            self.ev(node.test)
            self.block(node.body)
            self.block(node.orelse)
        elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            self.block(node.body)
            for handler in node.handlers:
                self.ev(handler.type)
                self.block(handler.body)
            self.block(node.orelse)
            self.block(node.finalbody)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                value = self.ev(item.context_expr)
                if item.optional_vars is not None:
                    self.bind(item.optional_vars, value)
            self.block(node.body)
        elif isinstance(node, ast.Return):
            if isinstance(node.value, ast.Tuple):
                # `return elements, total`: the idiom of a function that hands several values to an unpacking caller.
                # The tuple is transparent, its members keep their origin, and the unpack below takes them unchanged.
                self.returns |= _union(self.ev(member) for member in node.value.elts)
            elif node.value is not None:
                self.returns |= self.ev(node.value)
        elif isinstance(node, ast.Expr):
            self.ev(node.value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.nested(node)
        elif isinstance(node, (ast.Raise, ast.Assert)):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    self.ev(child)
        elif isinstance(node, ast.Match):
            self.match(node)
        else:  # a statement form the model has no rule for: its expressions and blocks are still walked
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    self.ev(child)
                elif isinstance(child, ast.stmt):
                    self.stmt(child)

    def match(self, node: ast.Match) -> None:
        subject = self.ev(node.subject)
        for case in node.cases:
            for pattern in ast.walk(case.pattern):
                names = [pattern.name] if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name else []
                if isinstance(pattern, ast.MatchMapping) and pattern.rest:
                    names.append(pattern.rest)
                for name in names:
                    self.env[name] = self.env.get(name, NONE) | _unknown_from(subject)
            if subject:
                self.unresolved(case.pattern, "structural pattern matching on a body", subject)
            if case.guard is not None:
                self.ev(case.guard)
            self.block(case.body)

    def defaults(self, arguments: ast.arguments, decorators: Sequence[ast.expr] = ()) -> None:
        """Defaults and decorators run in the enclosing frame, when the function is defined."""
        for default in (*arguments.defaults, *arguments.kw_defaults):
            self.ev(default)
        for decorator in decorators:
            self.ev(decorator)

    def nested(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """A nested def runs in the enclosing context; its parameters are of unknown origin, its result is kept."""
        self.defaults(node.args, node.decorator_list)
        outer_returns = self.returns
        self.returns = NONE
        saved = {arg.arg: self.env.get(arg.arg) for arg in _all_args(node)}
        for arg in _all_args(node):
            self.env[arg.arg] = UNKNOWN
        self.block(node.body)
        self.callables[node.name] = self.returns
        for name, value in saved.items():
            if value is None:
                self.env.pop(name, None)
            else:
                self.env[name] = value
        value = self.callables[node.name]
        self.returns = outer_returns
        self.env[node.name] = value

    def assign(self, target: ast.expr, value: Value, source: ast.expr, *, note: bool = True) -> None:
        if isinstance(target, ast.Name):
            self.env[target.id] = self.env.get(target.id, NONE) | value
            if isinstance(source, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)) or (
                isinstance(source, ast.Call) and ast.unparse(source.func) in {"list", "dict", "set", "defaultdict"}
            ):
                self.containers.add(target.id)
            if note and not (
                isinstance(source, ast.Constant) and source.value is None
            ):  # `x = None` says nothing about the type
                self.note_type(target.id, self.type_of(source))
            if isinstance(source, ast.Lambda):
                self.callables[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            kinds = self.tuple_types(source)
            from_call = isinstance(source, ast.Call) or (
                isinstance(source, ast.Await) and isinstance(source.value, ast.Call)
            )
            for position, element in enumerate(target.elts):
                self.bind(
                    element,
                    value if from_call else self.element_of(value, source),
                    kinds[position] if position < len(kinds) else "",
                )
        elif isinstance(target, ast.Attribute):
            self.ev(target.value)
            if value:
                self.unresolved(target, "a body held as an attribute", value)
        elif isinstance(target, ast.Subscript):
            self.ev(target.value)
            self.ev(target.slice)
            if value:
                self.unresolved(target, "a body stored into a container", value)

    def tuple_types(self, node: ast.expr) -> list[str]:
        """The element classes a call that returns a `tuple[A, B]` promises, when the code says so."""
        if isinstance(node, ast.Await):
            return self.tuple_types(node.value)
        if not isinstance(node, ast.Call):
            return []
        function = None
        if isinstance(node.func, ast.Name):
            resolved = self.index.resolve_function(self.rel, node.func.id)
            function = self.index.function(resolved[0], resolved[1]) if resolved else None
        elif isinstance(node.func, ast.Attribute):
            receiver = self.type_of(node.func.value)
            found = self.index.method(receiver, node.func.attr) if receiver else None
            function = found[1] if found else None
        kinds = annotation_tuple(function.returns) if function is not None else []
        return [kind if kind and self.index.known_type(kind) else "" for kind in kinds]

    def bind(self, target: ast.expr, value: Value, kind: str | None = "") -> None:
        """Bind a value to a target; `kind` is the class it is known to have (an empty string is a known-unknown, None
        leaves the type alone)."""
        if isinstance(target, ast.Name):
            self.env[target.id] = self.env.get(target.id, NONE) | value
            if kind is not None:
                self.note_type(target.id, kind)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self.bind(element, self.element_of(value, target), "")
        elif isinstance(target, (ast.Subscript, ast.Attribute)):
            self.assign(target, value, target)
        elif value:
            self.unresolved(target, "a body bound to a complex target", value)

    def element_of(self, value: Value, node: ast.AST) -> Value:
        return frozenset((root, path) if _lost(root) else (root, (*path, "*")) for root, path in value)

    # --- types ---------------------------------------------------------------------------------------------------

    def note_type(self, name: str, kind: str) -> None:
        """Every assignment to a name is one more alternative; two different classes, or a class and an unknown, are an
        unknown type, which the net reports where it matters."""
        alternatives = self.alternatives.setdefault(name, set())
        alternatives.add(kind)
        self.types[name] = next(iter(alternatives)) if len(alternatives) == 1 else ""

    @staticmethod
    def _join(left: str, right: str) -> str:
        """Two alternatives of one class are that class; any disagreement is an unknown type, which the net reports."""
        return left if left == right else ""

    def type_of(self, node: ast.expr | None) -> str:
        """The class an expression evaluates to, when the code says so (an annotation, a constructor, a return type)."""
        if node is None:
            return ""
        if isinstance(node, ast.Await):
            return self.type_of(node.value)
        if isinstance(node, ast.IfExp):
            return self._join(self.type_of(node.body), self.type_of(node.orelse))
        if isinstance(node, ast.BoolOp):
            joined = self.type_of(node.values[0])
            for value in node.values[1:]:
                joined = self._join(joined, self.type_of(value))
            return joined
        if isinstance(node, ast.NamedExpr):
            return self.type_of(node.value)
        if isinstance(node, ast.Subscript):
            kind = self.type_of(node.value)
            if kind.startswith("list:"):
                return kind if isinstance(node.slice, ast.Slice) else kind[5:]
            return ""
        if isinstance(node, ast.Name):
            if node.id not in self.types and node.id not in self.env and self.index.find_class(node.id) is not None:
                return self.index.resolve_class(node.id)
            return self.types.get(node.id, "")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "self" and self.owner:
                return self.index.class_attribute_type(self.owner, node.attr)
            receiver = self.type_of(node.value)
            return self.index.class_attribute_type(receiver, node.attr) if receiver and "list:" not in receiver else ""
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in self.module.classes or self.index.find_class(func.id) is not None:
                    return self.index.resolve_class(func.id)
                kind = self.types.get(func.id, "")
                if kind.startswith("call:"):
                    return kind[5:]
                target = self.module.imports.get(func.id, ("", None))[0]
                function = self.module.functions.get(func.id) or (
                    self.index.modules[target].functions.get(self.module.imports[func.id][1] or "") if target else None
                )
                return self.index.declared(function.returns) if function is not None else ""
            if isinstance(func, ast.Attribute):
                receiver = self.type_of(func.value)
                if receiver:
                    found = self.index.method(receiver, func.attr)
                    if found is not None:
                        return self.index.declared(found[1].returns)
                    if receiver.startswith("call:") or self.index.class_attribute_type(receiver, func.attr):
                        return ""
        return ""

    # --- expressions ---------------------------------------------------------------------------------------------

    def ev(self, node: ast.AST | None) -> Value:
        if node is None:
            return NONE
        method = getattr(self, f"ev_{type(node).__name__}", None)
        if method is not None:
            return method(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.ev(child)
        return NONE

    def ev_Constant(self, node: ast.Constant) -> Value:
        return NONE

    def ev_Name(self, node: ast.Name) -> Value:
        if node.id in self.env or node.id in self.callables:
            return self.env.get(node.id, NONE)
        resolved = self.index.resolve_function(self.rel, node.id)
        return self.callable_value(f"{resolved[0]}:{resolved[1]}") if resolved else NONE

    def callable_value(self, fid: str) -> Value:
        """A function handed over by name stands for what it returns, like a lambda does: a result that depends on its
        parameters is of unknown origin, a result built from a transport call keeps that origin."""
        summary = self.interpreter.summary(fid)
        if summary.opaque:
            return UNKNOWN
        result: set[Origin] = set()
        for root, path in summary.returns:
            result.add(
                (UNKNOWN_ROOT, ())
                if root[:2] in {"p:", "u:", "k:"} or root == UNKNOWN_ROOT
                else (f"r:{fid}:{root}", path)
            )
        return frozenset(result)

    def ev_Await(self, node: ast.Await) -> Value:
        return self.ev(node.value)

    def ev_Yield(self, node: ast.Yield) -> Value:
        """The call of a generator function stands for the sequence of what it yields: the element path loses its `*`,
        the caller's loop adds it back."""
        yielded = self.ev(node.value)
        stream: set[Origin] = set()
        for root, path in yielded:
            if _lost(root):
                stream.add((root, path))
            elif path and path[-1] == "*":
                stream.add((root, path[:-1]))
            else:
                stream.update(
                    self.unresolved(
                        node, "a generator yields a value that is not an element of a body", frozenset({(root, path)})
                    )
                )
        self.returns |= frozenset(stream)
        return NONE

    def ev_YieldFrom(self, node: ast.YieldFrom) -> Value:
        self.returns |= self.ev(node.value)
        return NONE

    def ev_BoolOp(self, node: ast.BoolOp) -> Value:
        return _union(self.ev(value) for value in node.values)

    def ev_IfExp(self, node: ast.IfExp) -> Value:
        self.ev(node.test)
        return self.ev(node.body) | self.ev(node.orelse)

    def ev_NamedExpr(self, node: ast.NamedExpr) -> Value:
        value = self.ev(node.value)
        self.bind(node.target, value, self.type_of(node.value))
        return value

    def ev_BinOp(self, node: ast.BinOp) -> Value:
        """`a | b`, `a + b`: the result may be either operand (a merge of two bodies keeps both origins)."""
        return self.ev(node.left) | self.ev(node.right)

    def ev_Compare(self, node: ast.Compare) -> Value:
        self.ev(node.left)
        left: ast.expr = node.left
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            right = self.ev(comparator)
            if isinstance(operator, (ast.In, ast.NotIn)):
                if _is_str(left):
                    certain = frozenset(o for o in right if _is_mapping_path(o[1]) or _lost(o[0]))
                    ambiguous = frozenset(o for o in right if o not in certain and not _is_leaf_path(o[1]))
                    if certain:
                        self.read(node, certain, str(left.value), "in")  # type: ignore[attr-defined]
                    if ambiguous:
                        self.read(node, ambiguous, str(left.value), "in?")  # type: ignore[attr-defined]
                elif right and not isinstance(left, ast.Constant):
                    self.unresolved(node, "a membership test with a dynamic key on a body", right)
            left = comparator
        return NONE

    def ev_Subscript(self, node: ast.Subscript) -> Value:
        receiver = self.ev(node.value)
        key = node.slice
        self.ev(key)
        if not receiver:
            return NONE
        if _is_str(key):
            return self.read(node, receiver, str(key.value), "sub")  # type: ignore[attr-defined]
        if isinstance(key, ast.Slice):
            return receiver
        if isinstance(key, ast.Constant) and isinstance(key.value, int):
            return self.element_of(receiver, node)
        return self.unresolved(node, "a subscript with a dynamic key on a body", receiver)

    def ev_Attribute(self, node: ast.Attribute) -> Value:
        receiver = self.ev(node.value)
        klass = self.type_of(node.value)
        declaring = self.index.wire_member(klass, node.attr, self.interpreter.wire_members) if klass else ""
        if declaring:
            return self.source(node, f"a:{declaring}.{node.attr}")
        if receiver:
            return self.unresolved(node, f"attribute {node.attr!r} of a body", receiver)
        if klass and self.index.is_raw_attribute(klass, node.attr):
            self.unresolved(node, f"attribute {node.attr!r} of {klass} is declared as able to hold a body")
            return UNKNOWN
        if not klass and node.attr in self.interpreter.wire_field_names:
            self.unresolved(
                node, f"attribute {node.attr!r} of a value of unknown type, which a record declares as a body"
            )
            return UNKNOWN
        if klass and not klass.startswith(("list:", "call:")):
            found = self.index.method(klass, node.attr)
            if found is not None:  # a property reads as what it returns, a method handed over as a value likewise
                return self.callable_value(found[0])
        return NONE

    def source(self, node: ast.AST, label: str) -> Value:
        number = self.call_index.setdefault(id(node), len(self.call_index))
        return frozenset({(f"{label}#{number}", ())})

    def ev_Call(self, node: ast.Call) -> Value:
        positional: list[Value] = []
        spread: Value = NONE
        for argument in node.args:
            if isinstance(argument, ast.Starred):
                spread |= self.ev(argument.value)
            elif not spread:
                positional.append(self.ev(argument))
            else:
                spread |= self.ev(argument)
        keywords: dict[str | None, Value] = {}
        for keyword in node.keywords:
            value = self.ev(keyword.value)
            if keyword.arg is None:
                spread |= value
            else:
                keywords[keyword.arg] = value
        if spread:
            self.unresolved(node, "a body spread into a call with * or **", spread)
        func = node.func
        if isinstance(func, ast.Name):
            return self.call_name(node, func.id, positional, keywords)
        if isinstance(func, ast.Attribute):
            return self.call_attribute(node, func, positional, keywords)
        callee = self.ev(func)
        arguments = _union([callee, *positional, *keywords.values()])
        return self.unresolved(node, "a call of a computed callee with a body", arguments) if arguments else NONE

    def call_name(self, node: ast.Call, name: str, positional: list[Value], keywords: dict[str | None, Value]) -> Value:
        arguments = _union([*positional, *keywords.values()])
        original = self.module.imports.get(name, ("", name))[1] or name
        if original in HIGHER_ORDER_RESULT and positional:
            return positional[0]
        if name in self.callables:
            return self.callables[name]
        if name in self.env and self.env[name]:
            return self.call_value(node, name, arguments)
        if name == "partial" and node.args:
            return self.partial(node, positional, keywords)
        resolved = self.index.resolve_function(self.rel, name)
        if resolved is not None:
            return self.instantiate(node, f"{resolved[0]}:{resolved[1]}", positional, keywords)
        if name == "getattr" and len(node.args) >= 2:
            return self.dynamic_attribute(node)
        constructed = self.index.resolve_class(name)
        if self.index.find_class(constructed) is not None:
            return self.construct(node, constructed, positional, keywords)
        if name in _BUILTIN_COPIES:
            return arguments
        if name in _BUILTIN_ELEMENT:
            return self.element_of(arguments, node)
        if name in _BUILTIN_PLAIN:
            return NONE
        if name in self.env and self.env[name]:
            return self.call_value(node, name, arguments)
        if self.module.external_origin.get(name) in _STRING_FUNCTIONS:
            return NONE
        if arguments:
            return self.unresolved(node, f"a call of {name}() with a body", arguments)
        return NONE

    def collect(self, node: ast.Call, name: str, method: str, added_values: list[Value], receiver: Value) -> Value:
        """`items.extend(page)` and `items.append(element)` on a local container: the container holds what is added, so
        a later read of it is a read of the body. An element whose position in the body is not an element is reported."""
        added = _union(added_values)
        if any(root[:2] in {"p:", "k:", "u:"} for root, _ in receiver):
            self.unresolved(node, f"a parameter container is changed in place by .{method}()", receiver)
        if method in {"extend", "update"}:
            self.env[name] = self.env.get(name, NONE) | added
            return NONE
        contribution: set[Origin] = set()
        for root, path in added:
            if _lost(root):
                contribution.add((root, path))
            elif path and path[-1] == "*":
                contribution.add((root, path[:-1]))
            else:
                self.unresolved(
                    node,
                    f"a body that is not an element appended to a container by .{method}()",
                    frozenset({(root, path)}),
                )
        self.env[name] = self.env.get(name, NONE) | frozenset(contribution)
        return NONE

    def call_value(self, node: ast.Call, name: str, arguments: Value) -> Value:
        """Calling a parameter or a local that holds a callable gives what the callable returns, which is the value it
        stands for; a body handed to a callable the model cannot see into is reported."""
        result: set[Origin] = set()
        for root, path in self.env[name]:
            result.add((f"k:{root[2:]}", ()) if root.startswith("p:") else (root, path))
        if arguments:
            self.unresolved(node, f"a body passed to the callable {name}()", arguments)
        return frozenset(result)

    def dynamic_attribute(self, node: ast.Call) -> Value:
        """`getattr(x, "name")` is the attribute; a computed name on a typed record may reach any of its body members."""
        subject, name = node.args[0], node.args[1]
        default = self.ev(node.args[2]) if len(node.args) >= 3 else NONE
        if _is_str(name):
            attribute = ast.copy_location(ast.Attribute(value=subject, attr=str(name.value)), node)  # type: ignore[attr-defined]
            return self.ev_Attribute(attribute) | default
        klass = self.index.resolve_class(self.type_of(subject)) if self.type_of(subject) else ""
        receiver = self.ev(subject)
        if receiver or any(owner == klass for owner, _ in self.interpreter.wire_members):
            return self.unresolved(node, "getattr with a computed name on a body or a body-carrying record", receiver)
        return NONE

    def construct(
        self, node: ast.Call, klass: str, positional: list[Value], keywords: dict[str | None, Value]
    ) -> Value:
        found = self.index.find_class(klass)
        assert found is not None
        init = self.index.method(klass, "__init__")
        if init is not None:
            self.instantiate(node, init[0], positional, keywords)
            return NONE
        _, cls = found
        fields = [
            (n.target.id, n.annotation)
            for n in cls.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        ]
        given: dict[str, Value] = dict(zip((name for name, _ in fields), positional, strict=False))
        given.update({k: v for k, v in keywords.items() if k is not None})
        declared = dict(fields)
        for field, value in given.items():
            if (
                value
                and holds_body(declared.get(field), self.index.type_names)
                and (klass, field) not in self.interpreter.wire_members
            ):
                self.unresolved(
                    node, f"a body passed to the field {field!r} of {klass}, which is not a body source", value
                )
        return NONE

    def partial(self, node: ast.Call, positional: list[Value], keywords: dict[str | None, Value]) -> Value:
        first = node.args[0]
        fake = ast.Call(func=first, args=node.args[1:], keywords=node.keywords)
        ast.copy_location(fake, node)
        if isinstance(first, ast.Name):
            return self.call_name(fake, first.id, positional[1:], keywords)
        if isinstance(first, ast.Attribute):
            return self.call_attribute(fake, first, positional[1:], keywords)
        rest = _union([*positional[1:], *keywords.values()])
        return self.unresolved(node, "partial of a computed callee with a body", rest) if rest else NONE

    def call_attribute(
        self, node: ast.Call, func: ast.Attribute, positional: list[Value], keywords: dict[str | None, Value]
    ) -> Value:
        method = func.attr
        receiver = self.ev(func.value)
        arguments = _union([*positional, *keywords.values()])
        if (
            method in {"extend", "update", "append", "add", "insert"}
            and arguments
            and isinstance(func.value, ast.Name)
            and func.value.id in self.env
            and self.type_of(func.value) == ""
            and (func.value.id in self.containers or receiver)
        ):
            return self.collect(node, func.value.id, method, [*positional, *keywords.values()], receiver)
        if method == "json" and not node.args:
            return self.source(node, "x:json()")
        owner_type = self.type_of(func.value)
        if owner_type and self.index.is_raw_attribute(owner_type, method):
            self.unresolved(node, f"call of {method!r} of {owner_type}, which is declared as able to hold a body")
            return UNKNOWN
        if (
            method in {"loads", "load"}
            and isinstance(func.value, ast.Name)
            and func.value.id == "json"
            and "json" in self.module.external
        ):
            return self.source(node, "x:json.loads")
        klass = self.index.resolve_class(self.type_of(func.value)) if self.type_of(func.value) else ""
        declaring = self.index.wire_member(klass, method, self.interpreter.wire_members) if klass else ""
        if declaring:
            return self.source(node, f"c:{declaring}.{method}")
        if not klass and not receiver and method in self.interpreter.wire_method_names:
            self.unresolved(
                node, f"method {method}() of a value of unknown type, which a port declares as returning a body"
            )
            return UNKNOWN
        called = self.type_of(func)
        if called.startswith("call:") and not self.index.wire_member(klass, method, self.interpreter.wire_members):
            return self.callable_result(node, called, receiver, arguments)
        if receiver:
            return self.read_method(node, method, receiver, positional)
        if isinstance(func.value, ast.Name) and func.value.id in self.module.imports:
            module, original = self.module.imports[func.value.id]
            resolved = self.index.resolve_function(module, method) if original is None else None
            if resolved is not None:
                return self.instantiate(node, f"{resolved[0]}:{resolved[1]}", positional, keywords)
        if ast.unparse(func) in _STRING_FUNCTIONS:
            return NONE
        if (
            method in _REGEX_METHODS
            and isinstance(func.value, ast.Name)
            and (func.value.id in self.module.patterns or func.value.id == "re")
        ):
            return NONE
        if klass:
            found = self.index.method(klass, method)
            if found is not None and not self.index.is_protocol(klass):
                through_class = (
                    isinstance(func.value, ast.Name)
                    and func.value.id not in self.env
                    and func.value.id not in self.types
                    and self.index.find_class(func.value.id) is not None
                )
                return self.instantiate(node, found[0], positional, keywords, class_call=through_class)
            if found is not None:  # a Protocol method: its implementation is another context
                names = [a.arg for a in _all_args(found[1])[1:]]
                given = dict(zip(names, positional, strict=False))
                given.update({k: v for k, v in keywords.items() if k is not None})
                request_side = _union(
                    v for p, v in given.items() if (klass, f"{method}.{p}") not in self.interpreter.wire_members
                )
                if request_side:
                    lost = self.unresolved(
                        node, f"a body passed to the request-side parameter of {klass}.{method}()", request_side
                    )
                    # The port declares what it returns: a record is an object whatever was passed in.
                    return lost if holds_body(found[1].returns, self.index.type_names) else NONE
                return NONE
        if arguments:
            return self.unresolved(node, f"a call of .{method}() with a body", arguments)
        return NONE

    def callable_result(self, node: ast.Call, kind: str, receiver: Value, arguments: Value) -> Value:
        """Calling an attribute or parameter annotated as a `Callable` returns what the annotation says."""
        result = kind[5:]
        if (self.index.resolve_class(result), "__call__") in self.interpreter.wire_members:
            return self.source(node, f"c:{self.index.resolve_class(result)}.__call__")
        return (
            NONE
            if not arguments
            else self.unresolved(node, "a body passed to a callable of unknown behaviour", arguments)
        )

    def read_method(self, node: ast.Call, method: str, receiver: Value, positional: list[Value]) -> Value:
        if method == "get" and node.args and _is_str(node.args[0]):
            fallback = positional[1] if len(positional) > 1 else NONE
            return self.read(node, receiver, str(node.args[0].value), "get") | fallback  # type: ignore[attr-defined]
        if method == "get":
            return self.unresolved(node, ".get with a dynamic key on a body", receiver)
        if method in _DYNAMIC_ITERATION:
            return self.unresolved(node, f".{method}() iteration over a body", receiver)
        if method == "copy":
            return receiver
        if method in _MUTATING:
            return self.unresolved(node, f".{method}() on a body", receiver)
        if method in _STRING_METHODS:
            return NONE
        return self.unresolved(node, f"method {method}() on a body", receiver)

    def instantiate(
        self,
        node: ast.Call,
        fid: str,
        positional: list[Value],
        keywords: dict[str | None, Value],
        *,
        class_call: bool = False,
    ) -> Value:
        rel, qualname = fid.split(":", 1)
        function = self.index.function(rel, qualname)
        if function is None:
            return NONE
        arguments = _all_args(function)
        static = any("staticmethod" in ast.unparse(d) for d in function.decorator_list)
        classmethod_ = any("classmethod" in ast.unparse(d) for d in function.decorator_list)
        explicit_self = class_call and not classmethod_
        names = [a.arg for a in arguments[1 if "." in qualname and not static and not explicit_self else 0 :]]
        mapping: dict[str, Value] = dict(zip(names, positional, strict=False))
        mapping.update({k: v for k, v in keywords.items() if k is not None})
        if function.args.vararg is not None and len(positional) > len(names) and _union(positional[len(names) :]):
            self.unresolved(node, f"a body passed through *args to {fid}", _union(positional[len(names) :]))
        declared = {a.arg for a in _all_args(function)}
        stray = _union(v for k, v in keywords.items() if k is not None and k not in declared)
        if function.args.kwarg is not None and stray:
            self.unresolved(node, f"a body passed through **kwargs to {fid}", stray)
        for parameter, value in mapping.items():
            for root, _ in value:
                source = None if _concrete(frozenset({(root, ())})) else (self.fid, root[2:])
                self.interpreter.bindings.setdefault((fid, parameter), set()).add(source)
        callee = self.interpreter.summary(fid)
        if callee.opaque:
            if _union(mapping.values()):
                self.unresolved(node, f"recursion through {fid}", _union(mapping.values()))
            lost = _unknown_from(_union(mapping.values()))
            return lost | (UNKNOWN if holds_body(function.returns, self.index.type_names) else NONE)
        for finding in callee.findings if fid not in self.interpreter.terminals else ():
            if not finding.parameters:
                continue
            origins = _union(mapping.get(name, NONE) for name in finding.parameters)
            if _concrete(origins):
                self.findings.append(finding._replace(parameters=()))
            elif origins:
                self.findings.append(finding._replace(parameters=_parameters(origins)))
        for r in callee.reads if fid not in self.interpreter.terminals else ():
            if r.root[:2] not in {"p:", "k:"}:
                continue
            for root, path in mapping.get(r.root[2:], NONE):
                if _lost(root):
                    parameters = (root[2:],) if root.startswith("u:") else ()
                    reason = f"read of {r.key!r} on a value of unknown origin"
                    self.findings.append(Finding("unclassified", r.context, r.line, reason, parameters))
                    continue
                if len(path) + len(r.path) >= _MAX_PATH:
                    self.findings.append(
                        Finding("unresolved", r.context, r.line, f"read of {r.key!r} below the path depth cap")
                    )
                    continue
                self.reads.append(Read(self.fid, node.lineno, root, (*path, *r.path), r.key, r.how))
        result: set[Origin] = set()
        for root, path in callee.returns:
            if root[:2] in {"p:", "u:", "k:"}:
                for argument_root, argument_path in mapping.get(root[2:], NONE):
                    if _lost(argument_root) or root.startswith("u:"):
                        result.update(_unknown_from(frozenset({(argument_root, ())})))
                    else:
                        result.add((argument_root, (*argument_path, *path)))
            elif root == UNKNOWN_ROOT:
                result.add((UNKNOWN_ROOT, ()))
            else:
                result.add((f"r:{fid}:{root}", path))
        return frozenset(result)

    def ev_Lambda(self, node: ast.Lambda) -> Value:
        self.defaults(node.args)
        saved = {arg.arg: self.env.get(arg.arg) for arg in _all_args(node)}
        for arg in _all_args(node):
            self.env[arg.arg] = UNKNOWN
        value = self.ev(node.body)
        for name, previous in saved.items():
            if previous is None:
                self.env.pop(name, None)
            else:
                self.env[name] = previous
        return value

    def comprehension(self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp) -> Value:
        saved = dict(self.env)
        saved_types = dict(self.types)
        for generator in node.generators:
            iterable = self.ev(generator.iter)
            self.bind(generator.target, self.element_of(iterable, generator.iter), None)
            kind = self.type_of(generator.iter)
            if isinstance(generator.target, ast.Name) and kind.startswith("list:"):
                self.types[generator.target.id] = kind[5:]
            for condition in generator.ifs:
                self.ev(condition)
        elements = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        union = _union(self.ev(element) for element in elements)
        self.env = saved
        self.types = saved_types
        if union:
            self.unresolved(node, "body values collected by a comprehension", union)
        return _unknown_from(union)

    ev_ListComp = ev_SetComp = ev_GeneratorExp = ev_DictComp = comprehension

    def container(self, node: ast.expr) -> Value:
        union = _union(self.ev(child) for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr))
        return self.unresolved(node, "a body stored in a literal container", union) if union else NONE

    ev_List = ev_Tuple = ev_Set = container

    def ev_Dict(self, node: ast.Dict) -> Value:
        """A `{**x, ...}` merge keeps the origin of what it spreads; any other body in a literal is reported."""
        spread: Value = NONE
        rest: Value = NONE
        for key, value in zip(node.keys, node.values, strict=True):
            evaluated = self.ev(value)
            if key is None:
                spread |= evaluated
            else:
                self.ev(key)
                rest |= evaluated
        if rest:
            self.unresolved(node, "a body stored in a literal container", rest)
        return spread | _unknown_from(rest)

    def ev_Starred(self, node: ast.Starred) -> Value:
        return self.ev(node.value)

    def plain(self, node: ast.expr) -> Value:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.ev(child)
        return NONE

    ev_JoinedStr = ev_UnaryOp = ev_FormattedValue = plain


# --- reads against the snapshot -------------------------------------------------------------------------------------


STRUCTURAL_KEYS = ("_links", "_embedded")


class Conditional(NamedTuple):
    absent: tuple[str, ...]  # the pinned versions in which the key may be missing
    reason: str


class Row(NamedTuple):
    """What a function's body root is: the representers that compose it, and those of its embedded resources."""

    compose: tuple[str, ...]
    embedded: dict[str, tuple[str, ...]] = {}
    waivers: dict[str, str] = {}  # "location|name" -> reason, for a read the snapshot cannot confirm
    conditional: dict[str, Conditional] = {}  # "location|name" -> the versions without it, for a conditional key


class Target(NamedTuple):
    representers: tuple[str, ...]
    location: str
    name: str
    scope: tuple[str, ...] = ()  # the embedded resources between the body root and the representer that renders it

    @property
    def key(self) -> str:
        """The key of a waiver or conditional entry: `location|name`, prefixed by the embedded path when there is one."""
        return (f"{'.'.join(self.scope)}:" if self.scope else "") + f"{self.location}|{self.name}"


class Check(NamedTuple):
    read: Read
    # "ok", "partial" (some versions), "missing", "open" (members unreadable), "opaque", "waived", "gated" (rendered only
    # for an Enterprise token, so never on Community), "ambiguous" (a membership test that may be a substring test)
    status: str
    versions: str  # the versions that lack the name, when it is partial


def target(read: Read, row: Row) -> Target | None:
    """The (representers, location, name) a read addresses, or None when it reaches below what the snapshot holds."""
    representers = row.compose
    scope: tuple[str, ...] = ()
    path = list(read.path)
    while True:
        if not path:
            if read.key in STRUCTURAL_KEYS:
                return Target(representers, "structure", read.key, scope)
            return Target(representers, "property", read.key, scope)
        head = path[0]
        if head == "*":
            path = path[1:]
        elif head == "_links":
            inner = [step for step in path[1:] if step != "*"]
            if not inner:
                return Target(representers, "link", read.key, scope)
            if len(inner) == 1:
                return Target(representers, f"link-member:{inner[0]}", read.key, scope)
            return None
        elif head == "_embedded":
            if len(path) == 1:
                return Target(representers, "embedded", read.key, scope)
            nested = row.embedded.get(path[1])
            if nested is None:
                return None
            representers, scope, path = nested, (*scope, path[1]), path[2:]
        else:
            return Target(representers, f"value-member:{head}", read.key, scope) if len(path) == 1 else None


def _versions(
    snapshot: dict, representers: tuple[str, ...], location: str, name: str, *, community: bool = False
) -> set[str]:
    """The pinned versions in which the name is rendered; with `community`, only by a representer entry that does not
    need an Enterprise token."""
    from check_adapter_reads import expand_ranges

    pins = list(snapshot["pinned"])
    found: set[str] = set()
    for representer in representers:
        entry = snapshot["paths"].get(representer, {"fields": {}})
        field = entry["fields"].get(f"{location}|{name}")
        if field is not None and not (community and field.get("enterprise")):
            found |= set(expand_ranges(field["versions"], pins))
    return found


def _explicit_member_versions(snapshot: dict, representers: tuple[str, ...], link: str) -> set[str]:
    """The pinned versions in which the source lists members of this link by hand, so the macro defaults do not apply."""
    from check_adapter_reads import expand_ranges

    pins = list(snapshot["pinned"])
    prefix = f"link-member:{link}|"
    found: set[str] = set()
    for representer in representers:
        for key, field in snapshot["paths"].get(representer, {"fields": {}})["fields"].items():
            if key.startswith(prefix) and not key.endswith("|*"):
                found |= set(expand_ranges(field["versions"], pins))
    return found


def check(read: Read, row: Row, snapshot: dict) -> Check:
    """Is the key read present in the snapshot of the row's representers, in every version where the row exists?"""
    from check_adapter_reads import expand_ranges

    place = target(read, row)
    if place is None:
        return Check(read, "opaque", "")
    if place.location == "structure":
        return Check(read, "ok", "")
    key = place.key
    if key in row.waivers:
        return Check(read, "waived", "")
    pins = list(snapshot["pinned"])
    existing: set[str] = set()
    for representer in place.representers:
        entry = snapshot["paths"].get(representer)
        if entry is not None:
            existing |= set(expand_ranges(entry["versions"], pins))
    present = _versions(snapshot, place.representers, place.location, place.name, community=True)
    if place.location.startswith("link-member:"):
        link = place.location.removeprefix("link-member:")
        open_versions = _versions(snapshot, place.representers, place.location, "*")
        explicit = _explicit_member_versions(snapshot, place.representers, link)
        default = (
            _versions(snapshot, place.representers, "link", link, community=True) - open_versions - explicit
            if place.name in snapshot.get("link_object_members", ())
            else set()
        )
        present |= default
        if open_versions and not present >= existing:
            return Check(read, "open", "")
    missing = existing - present
    if not present:
        if _versions(snapshot, place.representers, place.location, place.name):
            return Check(read, "gated", "")  # rendered, but only by representer entries that need an Enterprise token
        return Check(read, "ambiguous" if read.how == "in?" else "missing", "")
    if missing:
        allowed = set(row.conditional[key].absent) if key in row.conditional else set()
        return Check(
            read,
            "ok" if missing <= allowed else "partial",
            ",".join(sorted(missing, key=lambda v: tuple(map(int, v.split("."))))),
        )
    return Check(read, "ok", "")


def stale_entries(reads: Sequence[Read], row: Row, snapshot: dict) -> list[str]:
    """The waivers and conditional entries of a row that no read needs: a waived read the snapshot confirms anyway, a
    conditional key that is present everywhere or lists versions that are not missing."""
    bare = Row(row.compose, row.embedded)
    needed_waivers: set[str] = set()
    live_conditional: dict[str, set[str]] = {}
    for read in reads:
        place = target(read, row)
        if place is None or place.location == "structure":
            continue
        key = place.key
        outcome = check(read, bare, snapshot)
        if outcome.status != "ok":
            needed_waivers.add(key)
        if outcome.status == "partial":
            live_conditional.setdefault(key, set()).update(outcome.versions.split(","))
    stale = [f"waiver {key}" for key in row.waivers if key not in needed_waivers]
    for key, entry in row.conditional.items():
        if key not in live_conditional or set(entry.absent) != live_conditional[key]:
            stale.append(f"conditional {key}")
    return stale


class Exemption(NamedTuple):
    """One finding the model cannot resolve and a reviewer accepted: matched by kind, function, a pattern of the reason
    and the text of the source line, so a second finding in the same function, or on another line, is not covered."""

    kind: str
    context: str
    reason_pattern: str
    line_text: str  # a non-empty part of the source line the finding points at
    why: str
    occurrence: int | None = None  # which of several lines with that text (1-based, in file order) the exemption means


def apply_exemptions(
    findings: Sequence[Finding], exemptions: Sequence[Exemption], package: Path
) -> tuple[list[Finding], list[Exemption]]:
    """(the findings no exemption covers, the exemptions that cover nothing).

    An exemption names one source line of one function: the lines of the function that contain its `line_text`, in file
    order, are the candidates, and the occurrence picks one. That is decided from the source alone, so an exemption does
    not slide to another line when a finding disappears."""
    import re

    trees: dict[str, tuple[ast.Module, list[str]]] = {}

    def source(rel: str) -> tuple[ast.Module, list[str]]:
        if rel not in trees:
            text = (package / rel).read_text()
            trees[rel] = (ast.parse(text), text.splitlines())
        return trees[rel]

    def line_of(exemption: Exemption) -> int | None:
        rel, qualname = exemption.context.split(":", 1)
        tree, lines = source(rel)
        owner, _, name = qualname.rpartition(".")
        scope: Sequence[ast.stmt] = tree.body
        if owner:
            scope = next((n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner), [])
        function = next(
            (n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None
        )
        if function is None:
            return None
        candidates = [
            number
            for number in range(function.lineno, (function.end_lineno or function.lineno) + 1)
            if exemption.line_text in lines[number - 1]
        ]
        if exemption.occurrence is None:
            if len(candidates) > 1:
                raise ValueError(
                    f"the exemption for {exemption.context!r} matches {len(candidates)} lines: name the occurrence"
                )
            return candidates[0] if candidates else None
        return candidates[exemption.occurrence - 1] if 0 < exemption.occurrence <= len(candidates) else None

    for exemption in exemptions:
        if not exemption.line_text.strip():
            raise ValueError(f"the exemption for {exemption.context} names no source line")
        if re.search(exemption.reason_pattern, ""):
            raise ValueError(f"the exemption pattern {exemption.reason_pattern!r} matches every finding")
    chosen = [line_of(exemption) for exemption in exemptions]
    used: set[int] = set()
    open_findings: list[Finding] = []
    for finding in findings:
        for position, exemption in enumerate(exemptions):
            if (
                exemption.kind == finding.kind
                and exemption.context == finding.context
                and chosen[position] == finding.line
                and re.search(exemption.reason_pattern, finding.reason)
            ):
                used.add(position)
                break
        else:
            open_findings.append(finding)
    return open_findings, [e for position, e in enumerate(exemptions) if position not in used]


def analyse(
    package: Path,
    *,
    terminals: Mapping[str, Sequence[str]] | None = None,
) -> Analysis:
    """Reads and findings of every function under `package`.

    `terminals` maps a function a row binds to a body onto the names of its parameters that hold the body."""
    return Interpreter(Index(package), terminals=terminals).run()


def main(argv: Sequence[str] | None = None) -> int:
    """Print what the model finds in a source tree: contexts, reads and the findings by kind."""
    import argparse
    import collections
    import sys

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--src", type=Path, default=Path(__file__).resolve().parents[2] / "src" / "openproject_ce_mcp")
    parser.add_argument("--findings", action="store_true", help="list every finding, not only the counts")
    args = parser.parse_args(argv)
    result = analyse(args.src)
    kinds = collections.Counter(f.kind for f in result.findings)
    print(
        f"{len(result.reads)} contexts with reads, {sum(len(v) for v in result.reads.values())} reads; findings: "
        + ", ".join(f"{kind} {count}" for kind, count in sorted(kinds.items()))
    )
    if args.findings:
        for finding in result.findings:
            print(f"{finding.kind}\t{finding.context}:{finding.line}\t{finding.reason}", file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
