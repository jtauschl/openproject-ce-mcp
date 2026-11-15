"""Where a Ruby API representer renders each name: a property, a link, an embedded resource, or a member of one.

Pure text analysis, no package imports. One declaration per macro line (`property`, `link`, `self_link`, ...) in
source order, expanded into `Entry(location, wire_name)` pairs.

The statement of a macro is the macro line and every following line that is blank or indented deeper than the macro,
plus the `end` at the macro's own indent when the statement opens a `do` block; it stops at the next macro. Embedding,
conditions and link members are read from that whole statement. The `as:` override is searched only on the macro line
and up to 15 following lines: a wider search would change which wire name `check_field_completeness` derives.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import NamedTuple

PROPERTY = "property"
LINK = "link"
EMBEDDED = "embedded"
LINK_MEMBER = "link-member:"
VALUE_MEMBER = "value-member:"
# The member name that says a link's members could not be read from the source (a helper or factory builds the object).
UNREADABLE_MEMBERS = "*"

# The members of a link object the representer DSL renders itself (`LinkObject`, the SQL representers' `link`) when a
# link declares no hash of its own and is not marked unreadable.
LINK_OBJECT_MEMBERS = ("href", "title")
# The members of a formattable property value.
FORMATTABLE_MEMBERS = ("format", "raw", "html")

# Data properties.
_PROPERTY_MACROS = ("formattable_property", "date_time_property", "date_property", "duration_property", "property")
# Schema representers declare one property per schema entry (`schema :subject, type: ...`).
_SCHEMA_MACROS = (
    "schema_with_allowed_string_collection",
    "schema_with_allowed_collection",
    "schema_with_allowed_link",
    "schema_property",
    "schema",
)
# A link, and an embedded resource unless it says `embedded: false`; the name is camelized.
_RESOURCE_MACROS = (
    "associated_visible_resources",
    "associated_visible_resource",
    "associated_resources",
    "associated_resource",
    "associated_project",
    "polymorphic_resource",
    "resource_link",
    "resources",
    "resource",
)
# A plain link: the rel is rendered as given (`link :authSource`), not camelized.
_BARE_LINK_MACROS = ("links", "link", "link_without_resource", "associated_user_link")
_COLLECTION_MACROS = ("collection",)

# The macros `check_field_completeness` reads; it filters the output of this module to them.
LEGACY_DATA_MACROS = (
    "formattable_property",
    "date_time_property",
    "date_property",
    "associated_visible_resource",
    "associated_resources",
    "associated_resource",
    "associated_project",
    "resources",
    "resource",
    "property",
)
LEGACY_LINK_MACROS = ("links", "link")

_OTHER_MACROS = ("self_link", "embedded", "custom_field_injector")
_ALL_MACROS = (
    _PROPERTY_MACROS + _SCHEMA_MACROS + _RESOURCE_MACROS + _BARE_LINK_MACROS + _COLLECTION_MACROS + _OTHER_MACROS
)
_MACRO_RE = re.compile(
    r"^[ \t]*(?P<macro>" + "|".join(sorted(_ALL_MACROS, key=len, reverse=True)) + r")\b(?P<rest>.*)$"
)
_DEF_TYPE_RE = re.compile(r"^[ \t]*def[ \t]+_type\b")
_POSITIONAL_SYMBOL_RE = re.compile(r"^\s*:(\w+)")
_AS_RE = re.compile(r"\bas:\s*[:\"']?(\w+)")
_REL_RE = re.compile(r"\brel:\s*[:\"']?(\w+)")
_EMBEDDED_TRUE_RE = re.compile(r"\bembedded:\s*true\b")
_EMBEDDED_FALSE_RE = re.compile(r"\bembedded:\s*false\b")
_TITLE_FALSE_RE = re.compile(r"\btitle:\s*false\b")
_EMPTY_TITLE_GETTER_RE = re.compile(r"\btitle_getter:\s*->\s*(?:\([^)]*\))?\s*\{\s*\}")
_LINK_LAMBDA_RE = re.compile(r"\blink:\s*->")
_CONDITION_KEYS = ("if", "show_if", "skip_render", "render_if", "cache_if")
_CONDITION_LINE_RE = re.compile(r"(?<![\w:])(?P<key>" + "|".join(_CONDITION_KEYS) + r"):\s*(?P<expr>.*)")
_KWARG_LINE_RE = re.compile(r"^\s*\w+:(\s|$)")
_STRUCTURAL_RE = re.compile(r"^[ \t]*(def\b|end\b)")
_MAX_CONTINUATION_LINES = 15
_MAX_STATEMENT_LINES = 400

# A condition that names one of these renders the property only with an Enterprise token. `can_readonly?` is the
# helper behind `Status.can_readonly?` (`app/models/status.rb`: `EnterpriseToken.allows_to?(:readonly_work_packages)`).
ENTERPRISE_MARKERS = ("EnterpriseToken", "can_readonly?")


class Declaration(NamedTuple):
    macro: str
    symbol: str
    wire_name: str  # the name the completeness check always derived (`as:`, else camelized symbol)
    rendered: str  # the name the representer renders (a bare link keeps its rel as given)
    embedded: bool
    link_members: tuple[str, ...]
    conditions: tuple[str, ...]
    enterprise: bool
    plain_property: bool = False  # a resource with `embedded: false` also renders a top-level property
    members_unreadable: bool = False  # the link object is built by a helper, a factory or a lambda without a hash


class Entry(NamedTuple):
    location: str
    wire_name: str
    enterprise: bool = False


def camelize(name: str, acronyms: dict[str, str] | None = None) -> str:
    """Ruby snake_case -> lowerCamelCase, the way Representable derives a wire name.

    A leading underscore (`_meta`, from TimestampedRepresenter) is kept: a generic converter would turn `_meta` into
    `Meta` and fabricate a wire name. `acronyms` maps a lower-case word to its inflected spelling (`api` -> `API`): the
    server camelizes with its acronym list, so `maximum_api_v3_page_size` renders `maximumAPIV3PageSize`.
    """
    if name.startswith("_"):
        return name
    parts = name.split("_")
    inflected = acronyms or {}
    return parts[0] + "".join(inflected.get(p.lower(), p[:1].upper() + p[1:]) for p in parts[1:] if p)


def read_acronyms(inflections: str) -> dict[str, str]:
    """The `inflect.acronym 'API'` words of a Rails inflections file, lower-case word -> spelling."""
    return {word.lower(): word for word in re.findall(r"acronym\s+['\"]([\w]+)['\"]", inflections)}


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


_NOT_A_CALL = "=.),]}?<>+|&*/[!%^"


def _is_call(rest: str) -> bool:
    """`rest` (the text after a macro word) reads like a call, not `link = x`, `self_link)` or `link.href`."""
    stripped = rest.strip()
    return (not rest or rest[0] in " \t(:") and not stripped.startswith(tuple(_NOT_A_CALL))


_DEF_RE = re.compile(r"^(?P<indent>[ \t]*)(?:private[ \t]+)?def[ \t]+(?P<name>[\w.?!]+)")
_ENDLESS_DEF_RE = re.compile(r"^[ \t]*(?:private[ \t]+)?def[ \t]+[\w.?!]+(?:\([^)]*\))?[ \t]+=[ \t]+\S")
_TRAILING_COMMENT_RE = re.compile(r"[ \t]+#.*$")


def _inside_methods(lines: list[str]) -> list[bool]:
    """For each line: is it in the body of a `def` other than `def self.extension` (which wraps a patch's macros)?"""
    inside = [False] * len(lines)
    stack: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _DEF_RE.match(line)
        code = _TRAILING_COMMENT_RE.sub("", line).rstrip()
        if m and not code.endswith("end") and not _ENDLESS_DEF_RE.match(code):
            stack.append((len(m.group("indent")), m.group("name")))
        elif stack and code.strip() == "end" and _indent(line) == stack[-1][0]:
            stack.pop()
        inside[i] = any(name.split(".")[-1] != "extension" for _, name in stack)
    return inside


def _header(body: list[str]) -> str:
    """The statement up to and including the line that opens its `do` block (the whole statement without one)."""
    taken = []
    for line in body:
        taken.append(line)
        if re.search(r"\bdo(\s*\|[^|]*\|)?\s*$", line):
            break
    return "\n".join(taken)


def _positional_symbol(rest: str) -> str | None:
    """The macro's own positional `:symbol`, only when it is the very first token after the macro name.

    Anchored on purpose: a free search would take the `as: :word` of a bare `associated_project as: :definingProject`
    for a positional symbol.
    """
    m = _POSITIONAL_SYMBOL_RE.match(rest)
    return m.group(1) if m else None


def _continuation(lines: list[str], indent: int) -> list[str]:
    """The lines after a macro line that the `as:` override may sit on.

    Stops at a blank line, at a line that is not indented deeper than the macro, at the next macro, and at `def`/`end`.
    """
    taken: list[str] = []
    for line in lines[:_MAX_CONTINUATION_LINES]:
        if not line.strip():
            break
        if _indent(line) <= indent:
            break
        macro = _MACRO_RE.match(line)
        # `link: ->(*) {` is a keyword argument of the statement, not the next macro.
        if (macro and not macro.group("rest").startswith(":")) or _STRUCTURAL_RE.match(line):
            break
        taken.append(line)
    return taken


def _resolve_as(first_line_rest: str, following: list[str]) -> str | None:
    """The `as:` wire-name override, on the macro line or on a deeper-indented continuation line."""
    m = _AS_RE.search(first_line_rest)
    if m:
        return m.group(1)
    for line in following:
        m = _AS_RE.search(line)
        if m:
            return m.group(1)
    return None


def statement(lines: list[str], start: int) -> list[str]:
    """The macro line, every following blank or deeper-indented line, and the closing `end` of a `do` block."""
    indent = _indent(lines[start])
    taken = [lines[start]]
    for line in lines[start + 1 :]:
        if len(taken) >= _MAX_STATEMENT_LINES:
            raise ValueError(f"statement longer than {_MAX_STATEMENT_LINES} lines: {lines[start].strip()}")
        macro = _MACRO_RE.match(line)
        if macro and _is_call(macro.group("rest")) and not macro.group("rest").startswith(":"):
            break  # the next declaration, even when it is indented deeper
        if not line.strip() or _indent(line) > indent:
            taken.append(line)
            continue
        if _indent(line) == indent and (line.strip() == "end" or line.strip()[:1] in "})]"):
            taken.append(line)
        break
    while taken and not taken[-1].strip():
        taken.pop()
    return taken


def _top_level(body: str) -> str:
    """`body` with everything nested inside (), [] or {} blanked, so only the hash's own keys remain."""
    depth = 0
    out = []
    for char in body:
        if char in "([{":
            depth += 1
            out.append(" ")
        elif char in ")]}":
            depth = max(depth - 1, 0)
            out.append(" ")
        else:
            out.append(char if depth == 0 else " ")
    return "".join(out)


_STRING_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'")


def _hash_keys_with_href(text: str) -> tuple[str, ...]:
    """The top-level keys of every `{ ... }` literal in `text` that has an `href:` key (a link object)."""
    keys: list[str] = []
    stack: list[int] = []
    for position, char in enumerate(text):
        if char == "{":
            stack.append(position)
        elif char == "}" and stack:
            start = stack.pop()
            own = _top_level(text[start + 1 : position])
            if re.search(r"(?<![\w:])href:", own):
                keys += re.findall(r"(?<![\w:])(\w+):(?!:)", own)
    return tuple(dict.fromkeys(keys))


def _lambda_text(text: str, start: int) -> str | None:
    """The `{ ... }` body of the lambda whose `->` ends at `start`; None for a `do` block or an unbalanced literal."""
    position = start
    while position < len(text) and text[position].isspace():
        position += 1
    if position < len(text) and text[position] == "(":
        depth = 0
        for index in range(position, len(text)):
            depth += {"(": 1, ")": -1}.get(text[index], 0)
            if depth == 0:
                position = index + 1
                break
    while position < len(text) and text[position].isspace():
        position += 1
    if position >= len(text) or text[position] != "{":
        return None
    depth = 0
    for end in range(position, len(text)):
        depth += {"{": 1, "}": -1}.get(text[end], 0)
        if depth == 0:
            return text[position : end + 1]
    return None


# Another way of building the link object than a hash literal: its members are not the keys of the literal.
_OTHER_CONSTRUCTION_RE = re.compile(
    r"\bLinkObject\b|\bHash\b|\blink_object\b|\*\*\w|"
    r"\.(?:to_hash|to_h|merge!?|reverse_merge|deep_merge|update|store|tap)\b|"
    r"\w\]\s*(?:\|\|)?=(?!=)"
)


def _blank(text: str) -> str:
    """`text` without string contents and comments, so braces and keys in them are not read."""
    text = _STRING_RE.sub('""', text)
    return "\n".join(_TRAILING_COMMENT_RE.sub("", line) for line in text.splitlines())


def _link_members(body: str | None) -> tuple[tuple[str, ...], bool]:
    """(members, unreadable) of a link object built by `body`: readable only when it is hash literals alone."""
    if body is None:
        return (), True
    clean = _blank(body)
    members = _hash_keys_with_href(clean)
    return members, not members or bool(_OTHER_CONSTRUCTION_RE.search(clean))


# Link object members a macro can be given as options (`link :favor, method: :post do ... end`).
_OPTION_MEMBERS = ("templated", "method", "payload", "type")
_SQL_RESERVED = ("column", "path", "title", "href", "join", "render_if", "sql")


def _option_members(header: str) -> tuple[str, ...]:
    """The link object members given as keyword options on the macro line, before its block."""
    keys = re.findall(r"(?<![\w:])(\w+):(?!:)", _top_level(header))
    return tuple(key for key in keys if key in _OPTION_MEMBERS)


def _sql_link_members(statement_text: str) -> tuple[tuple[str, ...], bool]:
    """(members, unreadable) of a link of the SQL representer DSL: `href`, a `title` unless `title: -> {}`, and every
    option that is not one of the DSL's own as an additional member; a raw `sql:` link is unreadable."""
    clean = _blank(statement_text)
    options = re.findall(r"(?<![\w:])(\w+):(?!:)", _top_level(clean))
    if "sql" in options:
        return (), True
    title = () if re.search(r"\btitle:\s*->\s*(?:\([^)]*\))?\s*\{\s*\}", clean) else ("title",)
    return ("href", *title, *(o for o in options if o not in _SQL_RESERVED)), False


def _conditions(lines: list[str]) -> tuple[str, ...]:
    """Every `if:`/`show_if:`/`skip_render:`/`render_if:`/`cache_if:` expression of a statement, multi-line included."""
    found: list[str] = []
    i = 0
    while i < len(lines):
        m = _CONDITION_LINE_RE.search(lines[i])
        if not m:
            i += 1
            continue
        expression = [m.group("expr").strip()]
        base = _indent(lines[i])
        j = i + 1
        while (
            j < len(lines) and lines[j].strip() and not (_indent(lines[j]) <= base and _KWARG_LINE_RE.match(lines[j]))
        ):
            expression.append(lines[j].strip())
            j += 1
        found.append(f"{m.group('key')}: " + " ".join(expression).rstrip(","))
        i = j
    return tuple(found)


def extract_declarations(text: str, acronyms: dict[str, str] | None = None) -> list[Declaration]:
    """Every field declaration of one representer source file, in source order."""
    lines = text.splitlines()
    in_method = _inside_methods(lines)
    sql = bool(re.search(r"^\s*include\s+(?:::)?API::Decorators::Sql::", text, re.MULTILINE))
    out: list[Declaration] = []
    for i, line in enumerate(lines):
        if _DEF_TYPE_RE.match(line):
            out.append(Declaration("def", "_type", "_type", "_type", False, (), (), False))
            continue
        m = _MACRO_RE.match(line)
        if not m:
            continue
        macro, rest = m.group("macro"), m.group("rest")

        symbol = _positional_symbol(rest)
        if symbol is None:
            # Without a positional symbol a macro is only declared in these call shapes, never in a method body, and
            # never as `link = x`, `self_link)` or the hash key `self_link: path`.
            if in_method[i] or not _is_call(rest) or rest.startswith(":"):
                continue
            if macro == "associated_project":
                # A bare `associated_project`, or one with only `as:`, names the resource's own project.
                symbol = "project"
            elif macro == "self_link":
                symbol = "self"
            elif macro == "custom_field_injector":
                symbol = "customField*"
            elif macro in _BARE_LINK_MACROS and (rel := _REL_RE.search("\n".join(statement(lines, i)))):
                symbol = rel.group(1)
            else:
                # No other macro is declared without a positional symbol in the pinned sources.
                continue

        body = statement(lines, i)
        whole = "\n".join(body)
        arguments = _resolve_as(rest, _continuation(lines[i + 1 :], _indent(line)))
        wire = arguments or camelize(symbol)
        rendered = arguments or camelize(symbol, acronyms)
        if macro == "custom_field_injector":
            wire = rendered = symbol
        header = _blank(_header(body))
        if macro in _BARE_LINK_MACROS:
            rel = _REL_RE.search(header)
            rendered = rel.group(1) if rel else symbol
        elif macro == "self_link":
            rendered = "self"

        conditions = _conditions(body)
        enterprise = any(marker in condition for condition in conditions for marker in ENTERPRISE_MARKERS)
        members: tuple[str, ...] = ()
        unreadable = False
        if macro == "self_link":
            members = (
                ("href",)
                if _TITLE_FALSE_RE.search(whole) or _EMPTY_TITLE_GETTER_RE.search(whole)
                else ("href", "title")
            )
        elif macro in _BARE_LINK_MACROS:
            if macro == "associated_user_link":
                members = LINK_OBJECT_MEMBERS  # the SQL DSL builds href and title from the association name
            elif sql and not re.search(r"\bdo\b", header):
                members, unreadable = _sql_link_members(whole)
            else:
                members, unreadable = _link_members(whole)
                members = tuple(dict.fromkeys([*members, *_option_members(header)]))
        elif macro in _RESOURCE_MACROS:
            lambda_ = _LINK_LAMBDA_RE.search(whole)
            if lambda_:
                members, unreadable = _link_members(
                    _lambda_text(_blank(whole), _LINK_LAMBDA_RE.search(_blank(whole)).end())
                )
            else:
                unreadable = macro == "resource_link" or bool(re.search(r"\blink:\s*\S", whole))
        embedded = bool(_EMBEDDED_TRUE_RE.search(whole))
        plain_property = False
        if macro in _RESOURCE_MACROS:
            plain_property = macro != "resource_link" and bool(_EMBEDDED_FALSE_RE.search(whole))
            embedded = macro != "resource_link" and not plain_property
        out.append(
            Declaration(
                macro, symbol, wire, rendered, embedded, members, conditions, enterprise, plain_property, unreadable
            )
        )
    return out


def unparsed(text: str) -> list[str]:
    """Macro-like lines outside a method body that declare nothing: a computed name (`property setting`)."""
    lines = text.splitlines()
    in_method = _inside_methods(lines)
    found: list[str] = []
    for i, line in enumerate(lines):
        m = _MACRO_RE.match(line)
        if (
            m is None
            or in_method[i]
            or m.group("macro") in ("associated_project", "self_link", "custom_field_injector")
        ):
            continue
        rest = m.group("rest").strip()
        if not rest or _positional_symbol(m.group("rest")) is not None:
            continue
        if rest.startswith((':"', ":'")) or rest[0].isalpha() or rest[0] in "_(":
            found.append(f"{m.group('macro')} {rest}"[:80])
    return list(dict.fromkeys(found))


def entries(declarations: list[Declaration]) -> list[Entry]:
    """The (location, wire name) pairs the declarations render, each once, in source order."""
    out: list[Entry] = []
    seen: set[tuple[str, str]] = set()

    def add(location: str, wire: str, enterprise: bool = False) -> None:
        if (location, wire) not in seen:
            seen.add((location, wire))
            out.append(Entry(location, wire, enterprise))

    for d in declarations:
        name = d.rendered
        if d.macro == "def" or d.macro in _PROPERTY_MACROS or d.macro in _SCHEMA_MACROS:
            # A property rendered under `_embedded` is not rendered as a top-level property.
            add(EMBEDDED if d.embedded else PROPERTY, name, d.enterprise)
            if d.macro == "formattable_property":
                for member in FORMATTABLE_MEMBERS:
                    add(VALUE_MEMBER + name, member)
        elif d.macro in _COLLECTION_MACROS or d.macro == "embedded":
            add(EMBEDDED if d.embedded or d.macro == "embedded" else PROPERTY, name, d.enterprise)
        elif d.macro == "custom_field_injector":
            add(PROPERTY, name)
            add(LINK, name)
        elif d.macro in _RESOURCE_MACROS:
            add(LINK, name, d.enterprise)
            if d.members_unreadable:
                add(LINK_MEMBER + name, UNREADABLE_MEMBERS)
            if d.embedded:
                add(EMBEDDED, name)
            if d.plain_property:
                add(PROPERTY, name)
            for member in d.link_members:
                add(LINK_MEMBER + name, member)
        else:
            add(LINK, name, d.enterprise)
            if d.members_unreadable:
                add(LINK_MEMBER + name, UNREADABLE_MEMBERS)
            for member in d.link_members:
                add(LINK_MEMBER + name, member)
    return out


class Extension(NamedTuple):
    """One `extend_api_response(...)` call of an engine: the representer it patches and where its fields are."""

    target: str  # the representer path, relative to the source root
    inline_body: str | None  # the block body, when the fields are given inline
    patch_class: str | None  # the `Patch::Constant` of `&Patch::Constant.extension`


_EXTEND_RE = re.compile(
    r"extend_api_response\(\s*(?P<args>:[^)&]*?)\s*(?:,\s*&(?P<patch>[\w:]+)\.extension\s*)?\)(?P<do>\s*do)?"
)


def representer_path(arguments: str) -> str:
    """`:v3, :work_packages, :schema, :work_package_schema` -> `lib/api/v3/work_packages/schema/..._representer.rb`."""
    segments = [part.strip().lstrip(":") for part in arguments.split(",") if part.strip()]
    return "lib/api/" + "/".join(segments[:-1] + [f"{segments[-1]}_representer.rb"])


def extract_extensions(text: str) -> list[Extension]:
    """Every `extend_api_response` call of one `engine.rb`, with its inline body or its patch constant."""
    lines = text.splitlines()
    found: list[Extension] = []
    for i, line in enumerate(lines):
        if "extend_api_response" not in line:
            continue
        joined = line
        j = i
        while joined.count("(") > joined.count(")") and j + 1 < len(lines):
            j += 1
            joined += " " + lines[j].strip()
        m = _EXTEND_RE.search(joined)
        if m is None:
            raise ValueError(f"cannot parse extend_api_response: {joined.strip()}")
        target = representer_path(m.group("args"))
        if m.group("patch"):
            found.append(Extension(target, None, m.group("patch")))
            continue
        indent = _indent(line)
        body: list[str] = []
        for later in lines[j + 1 :]:
            if later.strip() == "end" and _indent(later) == indent:
                break
            body.append(later)
        found.append(Extension(target, "\n".join(body), None))
    return found


def patch_file(engine_path: str, patch_class: str) -> str:
    """The patch file a `Patches::API::WorkPackageRepresenter` constant lives in, next to its engine."""
    last = patch_class.split("::")[-1]
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", last).lower()
    return str(PurePosixPath(engine_path).parent / "patches" / "api" / f"{snake}.rb")
