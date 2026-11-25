#!/usr/bin/env python3
"""The work package filters a stored query can carry, read from the pinned OpenProject sources.

A saved OpenProject query stores its filters by the API name of the filter (`assignee`, `dueDate`,
`customField5`). The server builds that name from the key of the filter class with
`PropertyNameConverter.from_ar_name`; the filter classes are registered per query class in
`Queries::Register.register(Query) do ... end` blocks of the core and of the modules. A stored selection is judged
by this name (`app/policies/stored_query_policy.py`), so the set of names per pinned version has to be known: this
tool lists, per version, every filter class a `Query` registers, resolves its key (the explicit `def self.key`, or
the default derived from the class name), converts it the way the server does, and compares the result with a
committed snapshot (`query_filter_keys.json`).

    python tools/api-check/query_filter_keys.py --check   # exit 1 when the snapshot is stale
    python tools/api-check/query_filter_keys.py --write   # rewrite the snapshot after fetch-sources.sh

Stated boundary: the names come from the Ruby sources by pattern, not by running them. A registration is looked
for in the files under a `queries/` directory and in the module engines (`modules/*/lib/**/engine.rb`), and a
block of another query class nested in it is not part of it. A registration block holds class names only (a computed name is `unresolved`); a class is found by its Zeitwerk path (the constant `A::B::C`
lives in `.../app/<dir>/a/b/c.rb`) and must be unique; the filter whose name carries a custom field id
(`CustomFieldFilter`) is the pattern `customField<N>`, never a fixed name; `type` and the operator override flag
are read from the class, its included mixins and its superclasses, and are `null` where a base class decides at
run time. The server omits a filter from its schema when its module is off or its `available?` is false, so the
snapshot is a superset of what one instance lists. The proof against a running instance is a comparison, not an
equality (every name an instance lists is in the snapshot or matches the pattern).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import error_keys  # noqa: E402
import op_sources  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parent / "query_filter_keys.json"

CUSTOM_FIELD_PATTERN = "customField<N>"
# The registered filter that exists once per custom field: its name is built from the id at run time.
DYNAMIC_FILTER_CLASSES = {"Queries::WorkPackages::Filter::CustomFieldFilter": CUSTOM_FIELD_PATTERN}

_REGISTER = re.compile(r"Register\.register\(\s*(?:::)?Query\s*\)\s*do\s*$")
_NESTED_REGISTER = re.compile(r"Register\.register\([^)]*\)\s*do\s*$")
_CONSTANT = re.compile(r"(?<![\w:])((?:::)?[A-Z]\w*(?:::[A-Z]\w*)*Filter)\b")
_FILTER_LINE = re.compile(r"^\s*filter\b")
_EXCLUDE_LINE = re.compile(r"^\s*exclude\s+(\S+)")
_LOOP_VARIABLE = re.compile(r"\.each do \|(\w+)\|")
_VARIABLE_FILTER_LINE = re.compile(r"^\s*filter\s+([a-z_]\w*)\s*$")
_MODULE = re.compile(r"^module\s+([A-Z][\w:]*)\s*$")
_SELF_KEY_BLOCK = re.compile(r"def self\.key\s*\n\s*:(\w+)\s*\n\s*end")
_SELF_KEY_INLINE = re.compile(r"def self\.key\s*=\s*:(\w+)")
_TYPE_BLOCK = re.compile(r"def type\s*\n\s*:(\w+)\s*\n\s*end")
_TYPE_INLINE = re.compile(r"def type\s*=\s*:(\w+)")
_OPERATOR_OVERRIDE = re.compile(r"def (?:self\.)?(?:available_operators|operator_strategy)\b")
_SUPERCLASS = re.compile(r"^\s*class\s+[\w:]+\s*<\s*\n?\s*((?:::)?[A-Z][\w:]*)", re.M)
_INCLUDE = re.compile(r"^\s*include\s+((?:::)?[A-Z][\w:]*)", re.M)
_RUNTIME_CONVERSION = re.compile(r"ARToAPIConversions\.add\(\s*(?P<body>[^)]*)\)")
_RUNTIME_PAIR = re.compile(r"(?:\"([\w/]+)\"|(\w+)):\s*\"(\w+)\"")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# The classes whose own `type` and operators come from a base class that decides at run time.
_STOP_ANCESTORS = {"Queries::Filters::Base", "Queries::WorkPackages::Filter::WorkPackageFilter"}
_ROOTS = ("app", "modules/*/app", "modules/*/lib")


class UnresolvedConstantError(RuntimeError):
    """A registered filter class that names no single file, or no file at all."""


class UnreadableRegistrationError(RuntimeError):
    """A `filter` line of a `Query` registration block that does not name exactly one filter class."""


def underscore(name: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def zeitwerk_suffix(constant: str) -> str:
    return "/".join(underscore(part) for part in constant.removeprefix("::").split("::")) + ".rb"


class Checkout:
    """One pinned checkout: its Ruby files by path, and the conversions the server applies to a key."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = sorted(p for pattern in _ROOTS for p in root.glob(f"{pattern}/**/*.rb"))
        self.conversions, self.runtime_conversions = self._conversions()
        self.acronyms = error_keys.read_acronyms(root)

    def _conversions(self) -> tuple[dict[str, str], dict[str, str]]:
        conversions = dict(error_keys.read_conversions(self.root))
        runtime: dict[str, str] = {}
        for path in sorted(self.root.glob("modules/*/lib/**/engine.rb")):
            for call in _RUNTIME_CONVERSION.finditer(path.read_text()):
                for quoted, bare, value in _RUNTIME_PAIR.findall(call.group("body")):
                    runtime[quoted or bare] = value
        return {**conversions, **runtime}, runtime

    def api_name(self, ar_key: str) -> str:
        return error_keys.from_ar_name(ar_key, conversions=self.conversions, acronyms=self.acronyms)

    def resolve(self, constant: str, *, namespaces: tuple[str, ...] = ()) -> Path:
        """The one file a constant lives in, by its Zeitwerk path. A name written relative to a module is tried
        under each enclosing namespace, innermost first, like Ruby's lexical lookup; a leading `::` is absolute."""
        candidates = [constant.removeprefix("::")]
        if not constant.startswith("::"):
            candidates = [f"{namespace}::{constant}" for namespace in namespaces if namespace] + candidates
        for spelling in candidates:
            suffix = zeitwerk_suffix(spelling)
            matches = [
                p for p in self.files if p.as_posix().endswith(f"/{suffix}") and _is_autoload_root(self.root, p, suffix)
            ]
            if len(matches) > 1:
                raise UnresolvedConstantError(
                    f"{constant}: {sorted(p.relative_to(self.root).as_posix() for p in matches)}"
                )
            if matches:
                return matches[0]
        raise UnresolvedConstantError(f"{constant}: no file")

    def registration_files(self) -> list[Path]:
        """The files a `Query` registration can sit in: the query objects of the core and of the modules, and the
        engines of the modules."""
        candidates = [p for p in self.files if "/queries/" in p.as_posix()] + sorted(
            self.root.glob("modules/*/lib/**/engine.rb")
        )
        return sorted({p for p in candidates if "Register.register(" in p.read_text()})


def _is_autoload_root(root: Path, path: Path, suffix: str) -> bool:
    """The suffix starts right after an autoload directory (`app/<dir>` or a module's `lib`), so `foo/a.rb` does
    not match `bar/foo/a.rb`."""
    remainder = path.relative_to(root).as_posix().removesuffix(suffix).rstrip("/").split("/")
    return (
        (len(remainder) >= 2 and remainder[-2] == "app")
        or (remainder[:1] == ["modules"] and remainder[-1:] == ["lib"] and len(remainder) == 3)
        or remainder == ["lib"]
    )


def registrations(path: Path) -> tuple[dict[str, bool], str]:
    """(filter constants of the `Query` registration blocks of a file -> excluded, the file's namespace). A
    registration of another query class nested in the block (the engine of the storages module does that) is
    not part of it."""
    lines = path.read_text().splitlines()
    namespace = next((m.group(1) for line in lines if (m := _MODULE.match(line))), "")
    found: dict[str, bool] = {}
    index = 0
    while index < len(lines):
        if _REGISTER.search(lines[index]):
            body, index = _block(lines, index)
            loop_lists = _loop_lists(body)
            loop_variables = set(loop_lists)
            excluded_named = {m.group(1).removeprefix("::") for line in body if (m := _EXCLUDE_LINE.match(line))}
            excluded_named |= {c.removeprefix("::") for v in excluded_named & loop_variables for c in loop_lists[v]}
            for text in body:
                if text.lstrip().startswith("#"):
                    continue
                if _FILTER_LINE.match(text) and not _names_one_filter(text, loop_variables):
                    raise UnreadableRegistrationError(f"{path.name}: {text.strip()}")
                for constant in _CONSTANT.findall(text):
                    name = constant.removeprefix("::")
                    found[constant] = found.get(constant, False) or name in excluded_named
        index += 1
    return found, namespace


def _loop_lists(body: list[str]) -> dict[str, set[str]]:
    """The classes of each list a block loops over (`[ ... ].each do |variable|`), by loop variable."""
    lists: dict[str, set[str]] = {}
    group: set[str] = set()
    for line in body:
        if line.lstrip().startswith("#"):
            continue
        if "[" in line:
            group = set()
            line = line[line.index("[") :]
        group |= set(_CONSTANT.findall(line))
        loop = _LOOP_VARIABLE.search(line)
        if loop:
            lists[loop.group(1)] = group
            group = set()
    return lists


def _names_one_filter(line: str, loop_variables: set[str]) -> bool:
    """A `filter` line names one class, or the variable of a loop over a list of classes written in the same block
    (the storages engine registers its five work package filters that way)."""
    variable = _VARIABLE_FILTER_LINE.match(line)
    if variable:
        return variable.group(1) in loop_variables
    return len(_CONSTANT.findall(line)) == 1


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _block(lines: list[str], start: int) -> tuple[list[str], int]:
    """(the lines of the `do` block that opens on `lines[start]` without nested registrations, the index of its
    closing `end`)."""
    indent = _indent(lines[start])
    body: list[str] = []
    index = start + 1
    while index < len(lines) and not (_indent(lines[index]) == indent and lines[index].strip() == "end"):
        if _NESTED_REGISTER.search(lines[index]):
            _, index = _block(lines, index)
        else:
            body.append(lines[index])
        index += 1
    return body, index


def _read_literal(text: str, block: re.Pattern[str], inline: re.Pattern[str]) -> str | None:
    match = block.search(text) or inline.search(text)
    return match.group(1) if match else None


def class_facts(checkout: Checkout, path: Path) -> dict:
    """Key, type and operator override of the filter class in `path`, read through its mixins and superclasses."""
    seen: set[Path] = set()
    key: str | None = None
    kind: str | None = None
    overrides = False
    unresolved: list[str] = []
    queue = [path]
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        text = current.read_text()
        if key is None:
            key = _read_literal(text, _SELF_KEY_BLOCK, _SELF_KEY_INLINE)
        if kind is None:
            kind = _read_literal(text, _TYPE_BLOCK, _TYPE_INLINE)
        overrides = overrides or bool(_OPERATOR_OVERRIDE.search(text))
        for ancestor in [*_SUPERCLASS.findall(text), *_INCLUDE.findall(text)]:
            if ancestor.removeprefix("::") in _STOP_ANCESTORS:
                continue
            try:
                queue.append(checkout.resolve(ancestor, namespaces=_scopes(checkout, current)))
            except UnresolvedConstantError:
                unresolved.append(ancestor.removeprefix("::"))
    return {"key": key, "type": kind, "operator_override": overrides, "unresolved_ancestors": sorted(set(unresolved))}


def _scopes(checkout: Checkout, path: Path) -> tuple[str, ...]:
    """The enclosing namespaces of the class in `path`, innermost first (`A::B::C` is looked up in `A::B`, `A`)."""
    segments = _declared_class(checkout, path).split("::")[:-1]
    return tuple("::".join(segments[:n]) for n in range(len(segments), 0, -1))


def default_key(constant: str) -> str:
    return re.sub(r"_filter\Z", "", underscore(constant.removeprefix("::").split("::")[-1]))


def source_of(checkout: Checkout, path: Path) -> str:
    parts = path.relative_to(checkout.root).parts
    return parts[1] if parts[0] == "modules" else "core"


def read_filters(root: Path) -> dict:
    """Every filter a `Query` registers on a checkout, by API name (or pattern)."""
    checkout = Checkout(root)
    filters: dict[str, dict] = {}
    unresolved: list[str] = []
    for registration in checkout.registration_files():
        found, namespace = registrations(registration)
        for constant, excluded in sorted(found.items()):
            try:
                path = checkout.resolve(constant, namespaces=(namespace,))
            except UnresolvedConstantError as error:
                unresolved.append(f"{registration.relative_to(root).as_posix()}: {error}")
                continue
            declared = _declared_class(checkout, path)
            facts = class_facts(checkout, path)
            dynamic = DYNAMIC_FILTER_CLASSES.get(declared)
            if dynamic:
                api, ar_key = dynamic, None
            else:
                ar_key = facts["key"] or default_key(constant)
                api = checkout.api_name(ar_key)
            filters[api] = {
                "class": declared,
                "ar_key": ar_key,
                "source": source_of(checkout, path),
                "excluded": excluded,
                "type": facts["type"],
                "operator_override": facts["operator_override"],
                "unresolved_ancestors": facts["unresolved_ancestors"],
            }
    return {"filters": filters, "unresolved": sorted(unresolved), "runtime_conversions": checkout.runtime_conversions}


def _declared_class(checkout: Checkout, path: Path) -> str:
    """The full constant of the registered class: its Zeitwerk path read back (`app/models/queries/a/b.rb` is
    `Queries::A::B`, `modules/m/lib/a/b.rb` is `A::B`), so a name written relative to a module carries its
    namespace in the snapshot."""
    parts = path.relative_to(checkout.root).parts
    rest = parts[2:] if parts[0] == "modules" else parts
    segments = rest[2:] if rest[0] == "app" else rest[1:]
    return "::".join(_camelize(segment.removesuffix(".rb")) for segment in segments)


def _camelize(segment: str) -> str:
    return "".join(word.capitalize() for word in segment.split("_"))


def build(pins: dict[str, str], sources: Path = op_sources.SOURCES) -> dict:
    per_version = {version: read_filters(sources / version) for version in pins}
    names: dict[str, dict] = {}
    for version, data in per_version.items():
        for api, facts in data["filters"].items():
            entry = names.setdefault(api, {"facts": {}, "versions": []})
            entry["versions"].append(version)
            entry["facts"][version] = facts
    filters = {}
    for api, entry in sorted(names.items()):
        latest = entry["facts"][entry["versions"][-1]]
        filters[api] = {
            "class": latest["class"],
            "ar_key": latest["ar_key"],
            "source": latest["source"],
            "type": latest["type"],
            "operator_override": latest["operator_override"],
            "excluded": sorted((v for v, f in entry["facts"].items() if f["excluded"]), key=op_sources.version_key),
            "versions": sorted(entry["versions"], key=op_sources.version_key),
        }
    return {
        "pins": pins,
        "filters": filters,
        "unresolved": {v: d["unresolved"] for v, d in per_version.items() if d["unresolved"]},
        "unresolved_ancestors": {
            api: sorted({a for f in entry["facts"].values() for a in f["unresolved_ancestors"]})
            for api, entry in sorted(names.items())
            if any(f["unresolved_ancestors"] for f in entry["facts"].values())
        },
        "runtime_conversions": {v: d["runtime_conversions"] for v, d in per_version.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    pins = error_keys.read_tags(list(op_sources.pinned_versions()))
    snapshot = json.dumps(build(pins), indent=1) + "\n"
    if args.write:
        SNAPSHOT.write_text(snapshot)
        return 0
    if not SNAPSHOT.is_file() or SNAPSHOT.read_text() != snapshot:
        print("query_filter_keys.json is stale: run tools/api-check/query_filter_keys.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
