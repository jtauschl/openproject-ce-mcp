"""Where raw OpenProject response bodies enter the code, and which typed members carry them.

A read of a key is only checked against the representers when its receiver is known to hold a response body. That
knowledge starts here: the transport calls that parse a body, the port methods and record fields that hand a body on,
and the request-side members that look alike but carry what the client sends. `census()` lists every member of the
source tree whose annotation says "a dict of anything"; `classify()` puts each into a table, and a member that is in
none of them fails the completeness test, so a new port method or record field cannot be skipped by accident.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

TRANSPORT_METHODS = frozenset({"get_json", "post_json", "patch_json", "delete_json", "post_multipart"})
# `request_raw` returns the status and the headers, not a parsed body.
NOT_A_BODY_METHODS = frozenset({"request_raw"})

_BODY_NAMES = frozenset(
    {"Any", "object", "dict", "list", "Mapping", "Sequence", "Iterable", "tuple", "set", "frozenset"}
    | {"MutableMapping", "Iterator", "AsyncIterator", "Collection", "Dict", "List", "Tuple", "Set", "FrozenSet"}
)


# Names that are a scalar, a standard-library value type or a marker, never a response body. Any other name that is not
# a class of the source tree, an alias or a type variable is treated as able to hold a body, so an unknown type cannot
# hide a body field from the census.
_PLAIN_TYPES = frozenset(
    {"str", "int", "float", "bool", "bytes", "None", "NoReturn", "Path", "PurePath", "datetime", "date", "time"}
    | {"timedelta", "Decimal", "UUID", "Pattern", "Callable", "Exception", "SecretStr", "type", "Self", "LiteralString"}
    | {"Awaitable", "Coroutine", "Optional", "Union", "Final", "ClassVar", "Annotated", "Literal", "TypeAlias"}
)


class TypeNames(NamedTuple):
    """The type aliases, type variables and classes declared in the source tree."""

    aliases: dict[str, ast.expr]
    type_vars: dict[str, ast.expr | None]  # name -> bound, None when unbound
    classes: frozenset[str] = frozenset()


def type_names(package: Path) -> TypeNames:
    """Module-level aliases (`Json = dict[str, Any]`, `Raw = Any`, `from typing import Any as Raw`) and type variables.
    The names are global to the tree; an alias defined twice with different meanings is an error, not a guess."""
    aliases: dict[str, ast.expr] = {}
    type_vars: dict[str, ast.expr | None] = {}
    classes: set[str] = set()

    def define(name: str, value: ast.expr) -> None:
        if name in aliases and ast.unparse(aliases[name]) != ast.unparse(value):
            raise ValueError(f"the type alias {name!r} is defined with two different meanings in the source tree")
        aliases[name] = value

    for path in sorted(package.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                classes.add(node.name)
                if any("TypedDict" in ast.unparse(base) for base in node.bases):
                    define(node.name, ast.Name(id="dict"))  # a TypedDict is a body-shaped mapping
    for path in sorted(package.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.asname and alias.asname != alias.name and alias.name in _BODY_NAMES:
                        define(alias.asname, ast.Name(id=alias.name))
                continue
            if isinstance(node, ast.TypeAlias if hasattr(ast, "TypeAlias") else ()) and isinstance(node.name, ast.Name):  # type: ignore[attr-defined]
                define(node.name.id, node.value)  # type: ignore[attr-defined]
                continue
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                name, value = node.target.id, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            else:
                continue
            if (
                isinstance(value, ast.Call)
                and ast.unparse(value.func).split(".")[-1] == "NewType"
                and len(value.args) == 2
            ):
                define(name, value.args[1])
            elif isinstance(value, ast.Call) and ast.unparse(value.func).split(".")[-1] == "TypeVar":
                type_vars[name] = next((k.value for k in value.keywords if k.arg == "bound"), None)
            elif isinstance(value, ast.Name) and value.id in classes and value.id not in aliases:
                classes.add(name)  # `ProjectFormResult = FormResult`
            elif isinstance(value, (ast.Subscript, ast.BinOp)) or (
                isinstance(value, ast.Name)
                and (value.id in _BODY_NAMES or value.id in aliases or value.id in _PLAIN_TYPES)
            ):
                define(name, value)
    return TypeNames(aliases, type_vars, frozenset(classes))


def holds_body(annotation: ast.expr | None, names: TypeNames | None = None, _depth: int = 0) -> bool:
    """Can a value of this declared type be, or contain, a response body? No annotation, `Any`, an unbound type variable
    and a bare or `Any`-valued container can; a class, a scalar and a container of those cannot. Aliases and bound type
    variables of the source tree are resolved."""
    if annotation is None or _depth > 8:
        return True
    names = names or TypeNames({}, {})
    deeper = _depth + 1
    if isinstance(annotation, (ast.Name, ast.Attribute)):
        name = annotation.id if isinstance(annotation, ast.Name) else annotation.attr
        if name in names.aliases:
            return holds_body(names.aliases[name], names, deeper)
        if name in names.type_vars:
            bound = names.type_vars[name]
            return True if bound is None else holds_body(bound, names, deeper)
        if name in _BODY_NAMES:
            return True
        return name not in names.classes and name not in _PLAIN_TYPES
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return holds_body(ast.parse(annotation.value, mode="eval").body, names, deeper)
        except SyntaxError:
            return True
    if isinstance(annotation, ast.Constant):
        return False
    if isinstance(annotation, ast.BinOp):
        return holds_body(annotation.left, names, deeper) or holds_body(annotation.right, names, deeper)
    if isinstance(annotation, (ast.Tuple, ast.List)):
        return any(holds_body(element, names, deeper) for element in annotation.elts)
    if isinstance(annotation, ast.Subscript):
        head = annotation.value.id if isinstance(annotation.value, ast.Name) else getattr(annotation.value, "attr", "")
        inner = annotation.slice
        if head == "Literal":
            return False
        if head == "Annotated":
            return holds_body(inner.elts[0] if isinstance(inner, ast.Tuple) else inner, names, deeper)
        return holds_body(inner, names, deeper)
    return True


class Member(NamedTuple):
    kind: str  # "method" (return), "parameter" (name is `method.parameter`) or "field"
    module: str  # path below the package root
    owner: str
    name: str
    annotation: str


def census(package: Path) -> list[Member]:
    """Every member of the source tree whose declared type can hold a response body: Protocol method returns and
    parameters, and dataclass, Protocol and TypedDict fields (callbacks and containers of raw mappings included)."""
    members: list[Member] = []
    names = type_names(package)
    for path in sorted(package.rglob("*.py")):
        module = path.relative_to(package).as_posix()
        for cls in (n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.ClassDef)):
            protocol = any("Protocol" in ast.unparse(base) for base in cls.bases)
            dataclass = any("dataclass" in ast.unparse(deco) for deco in cls.decorator_list)
            typed_dict = any("TypedDict" in ast.unparse(base) for base in cls.bases)
            for node in cls.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and protocol:
                    if node.returns is not None and holds_body(node.returns, names):
                        members.append(Member("method", module, cls.name, node.name, ast.unparse(node.returns)))
                    for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                        if (
                            arg.arg not in {"self", "cls"}
                            and arg.annotation is not None
                            and holds_body(arg.annotation, names)
                        ):
                            members.append(
                                Member(
                                    "parameter", module, cls.name, f"{node.name}.{arg.arg}", ast.unparse(arg.annotation)
                                )
                            )
                elif (
                    isinstance(node, ast.AnnAssign)
                    and (dataclass or protocol or typed_dict)
                    and isinstance(node.target, ast.Name)
                    and holds_body(node.annotation, names)
                ):
                    members.append(Member("field", module, cls.name, node.target.id, ast.unparse(node.annotation)))
    return members


WIRE = "wire"
REQUEST = "request"  # what the client sends or computes, not a response body
EXEMPT = "exempt"

# Modules whose raw members are response bodies unless a rule below says otherwise.
_WIRE_MODULES = (
    "app/ports/",
    "app/form_result.py",
    "app/resolvers/scoped_reference_resolver.py",
    "app/services/_work_package_target.py",
)
_REQUEST_MODULES = (
    "models.py",
    "presentation.py",
    "tool_params.py",
    "app/services/_write_outcome.py",
    "app/services/project_service.py",
)

# (owner, name) of a member in a wire module that is not a response body.
_REQUEST_MEMBERS: dict[tuple[str, str], str] = {
    ("CustomFieldCarrier", "custom_fields"): "the custom field values a write carries, built by the client",
}
# `get_json` and its siblings carry the bodies; these names are the Protocol that declares them.
_TRANSPORT_OWNER = "Transport"
# (owner, "method.parameter") of a Protocol parameter that receives a response body; every other raw parameter is what
# the client sends (a write payload, a filter list) and names cannot tell them apart.
_WIRE_PARAMETERS = frozenset(
    {
        ("ActivityApi", "to_record.payload"),
        ("CostApi", "to_cost_entry_record.payload"),
        ("CostApi", "to_cost_type_record.payload"),
        ("CostApi", "to_costs_by_type_result.payload"),
        ("GithubGitlabLinkApi", "to_github_pull_request_record.payload"),
        ("GithubGitlabLinkApi", "to_gitlab_issue_record.payload"),
        ("GithubGitlabLinkApi", "to_gitlab_merge_request_record.payload"),
        ("ProjectApi", "list_available_parent_projects.schema"),
        ("RelationApi", "to_record.payload"),
        ("ReminderApi", "to_record.payload"),
        ("ResponseLearner", "learn.payload"),
        ("TimeEntryApi", "parse_form_result.form"),
        ("TimeEntryApi", "project_link_title_and_id.link"),
        ("TimeEntryApi", "to_activity_record.payload"),
        ("TimeEntryApi", "to_record.payload"),
        ("WorkPackageApi", "parse_form.form"),
        ("WorkPackageApi", "to_record.payload"),
    }
)
# (owner, "method.parameter") of a Protocol parameter that is what the client sends: a write payload, a draft, a filter
# list. Declared member by member, like the wire ones, so a new raw parameter fails the census until it is classified.
_REQUEST_PARAMETERS = frozenset(
    {
        ("ActionCapabilityApi", "list_capabilities.filters"),
        ("AttachmentApi", "create.metadata"),
        ("AttachmentApi", "create_for_container.metadata"),
        ("BoardApi", "commit_create.payload"),
        ("BoardApi", "commit_update.payload"),
        ("BoardApi", "create_form.payload"),
        ("BoardApi", "update_form.payload"),
        ("DocumentApi", "commit_update.payload"),
        ("GridApi", "commit_create.payload"),
        ("GridApi", "commit_update.payload"),
        ("GridApi", "create_form.payload"),
        ("GridApi", "update_form.payload"),
        ("GroupApi", "commit_create.payload"),
        ("GroupApi", "commit_update.payload"),
        ("MeetingAgendaItemApi", "create.payload"),
        ("MeetingAgendaItemApi", "update.payload"),
        ("MeetingApi", "commit_create.payload"),
        ("MeetingApi", "commit_update.payload"),
        ("MeetingApi", "create_form.payload"),
        ("MeetingApi", "update_form.payload"),
        ("MeetingOutcomeApi", "create.payload"),
        ("MeetingOutcomeApi", "update.payload"),
        ("MeetingSectionApi", "create.payload"),
        ("MeetingSectionApi", "update.payload"),
        ("MembershipApi", "commit_create.payload"),
        ("MembershipApi", "commit_update.payload"),
        ("MembershipApi", "create_form.payload"),
        ("MembershipApi", "update_form.payload"),
        ("NewsApi", "commit_create.payload"),
        ("NewsApi", "commit_update.payload"),
        ("ProjectApi", "commit_copy.payload"),
        ("ProjectApi", "commit_create.payload"),
        ("ProjectApi", "commit_update.payload"),
        ("ProjectApi", "copy_form.payload"),
        ("ProjectApi", "create_form.payload"),
        ("ProjectApi", "get_copy_schema.draft_payload"),
        ("ProjectApi", "get_schema.draft_payload"),
        ("ProjectApi", "list.custom_field_filters"),
        ("ProjectApi", "update_form.payload"),
        ("RecurringMeetingApi", "create.payload"),
        ("RecurringMeetingApi", "update.payload"),
        ("RelationApi", "create.payload"),
        ("RelationApi", "update.payload"),
        ("ReminderApi", "create.payload"),
        ("ReminderApi", "update.payload"),
        ("StorageApi", "commit_create.payload"),
        ("StorageApi", "commit_update.payload"),
        ("TimeEntryApi", "create.payload"),
        ("TimeEntryApi", "update.payload"),
        ("TimeEntryApi", "validate_create.payload"),
        ("TimeEntryApi", "validate_update.payload"),
        ("Transport", "patch_json.json_body"),
        ("Transport", "post_json.json_body"),
        ("Transport", "post_multipart.metadata"),
        ("Transport", "request_raw.json_body"),
        ("UserApi", "commit_create.payload"),
        ("UserApi", "commit_update.payload"),
        ("UserApi", "create_form.payload"),
        ("UserApi", "update_form.payload"),
        ("UserNonWorkingTimeApi", "update.payload"),
        ("UserPreferencesApi", "commit_update.payload"),
        ("UserWorkingHoursApi", "update.payload"),
        ("VersionApi", "commit_create.payload"),
        ("VersionApi", "commit_update.payload"),
        ("VersionApi", "create_form.payload"),
        ("VersionApi", "update_form.payload"),
        ("WorkPackageApi", "commit_create.payload"),
        ("WorkPackageApi", "commit_update.payload"),
        ("WorkPackageApi", "list.filters"),
        ("WorkPackageApi", "validate_create.payload"),
        ("WorkPackageApi", "validate_update.payload"),
    }
)


def classify(member: Member) -> tuple[str, str]:
    """(class, reason) of a census member; raises for a member that no rule covers."""
    if member.kind == "parameter":
        if (member.owner, member.name) in _WIRE_PARAMETERS:
            return WIRE, "a normalizer entry point: the caller hands it a response body"
        if (member.owner, member.name) in _REQUEST_PARAMETERS:
            return REQUEST, "a body or filter the client builds and sends"
        raise LookupError(f"no wire source rule for {member}")
    if member.module == "transport_chain.py":
        return EXEMPT, "an httpx transport that is wrapped, never a body"
    if member.module.startswith("doctor/"):
        return EXEMPT, "the doctor reads local client configuration files, never a response"
    if member.owner == _TRANSPORT_OWNER:
        if member.name in TRANSPORT_METHODS:
            return WIRE, "the transport returns the parsed response body"
        return EXEMPT, "the transport does not return a body here"
    if (member.owner, member.name) in _REQUEST_MEMBERS:
        return REQUEST, _REQUEST_MEMBERS[(member.owner, member.name)]
    if member.module in _REQUEST_MODULES or member.module.startswith(_REQUEST_MODULES):
        return REQUEST, "an outgoing payload, a write outcome, tool output or a model field the client fills"
    if member.module.startswith(_WIRE_MODULES) or member.module in _WIRE_MODULES:
        return WIRE, "hands a response body or one of its links on"
    raise LookupError(f"no wire source rule for {member}")


def wire_members(package: Path) -> set[tuple[str, str]]:
    """(owner, name) of every member that holds a response body."""
    return {(m.owner, m.name) for m in census(package) if classify(m)[0] == WIRE}
