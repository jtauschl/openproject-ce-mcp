"""The read model: what it records for each construct, and what it refuses to guess.

Every fixture plants a tiny package and runs the interpreter over it. A `Transport` Protocol and an adapter class with a
`_transport: Transport` attribute are planted where a fixture needs a body to come from a transport call.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import adapter_reads
import pytest
import wire_sources

PLANTED_TRANSPORT = """
from typing import Any, Protocol

class Transport(Protocol):
    async def get_json(self, path: str) -> dict[str, Any]: ...
    async def request_raw(self, path: str) -> dict[str, Any]: ...
"""


def plant(tmp_path: Path, **modules: str) -> Path:
    package = tmp_path / "pkg"
    package.mkdir()
    for name, source in modules.items():
        target = package / f"{name.replace('__', '/')}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source))
    return package


def reads_of(
    tmp_path: Path, source: str, *, terminals: dict[str, tuple[str, ...]] | None = None, **modules: str
) -> dict[str, list]:
    package = plant(tmp_path, m=source, transport=PLANTED_TRANSPORT, **modules)
    return adapter_reads.analyse(package, terminals=terminals).reads


def findings_of(
    tmp_path: Path, source: str, *, terminals: dict[str, tuple[str, ...]] | None = None, **modules: str
) -> list:
    package = plant(tmp_path, m=source, transport=PLANTED_TRANSPORT, **modules)
    return adapter_reads.analyse(package, terminals=terminals).findings


def shape(reads: list) -> set[tuple[tuple[str, ...], str, str]]:
    return {(tuple(r.path), r.key, r.how) for r in reads}


def test_get_subscript_and_membership_of_a_bound_parameter_are_reads_with_their_path(tmp_path: Path) -> None:
    source = """
    def normalize(payload):
        links = payload.get("_links", {})
        project = links.get("project")
        href = project.get("href") if isinstance(project, dict) else None
        if "readIAN" in payload:
            pass
        return payload["id"], href
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:normalize": ("payload",)})["m.py:normalize"]

    assert shape(reads) == {
        ((), "_links", "get"),
        (("_links",), "project", "get"),
        (("_links", "project"), "href", "get"),
        ((), "readIAN", "in"),
        ((), "id", "sub"),
    }


def test_a_transport_result_is_a_body_with_its_own_root(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    class Adapter:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def list_all(self):
            payload = await self._transport.get_json("x")
            elements = payload.get("_embedded", {}).get("elements", [])
            total = int(payload.get("total", 0))
            return [element["id"] for element in elements], total
    """
    reads = reads_of(tmp_path, source)["m.py:Adapter.list_all"]

    assert shape(reads) == {
        ((), "_embedded", "get"),
        (("_embedded",), "elements", "get"),
        ((), "total", "get"),
        (("_embedded", "elements", "*"), "id", "sub"),
    }
    assert {r.root.split(":")[0] for r in reads} == {"c"}


def test_request_raw_is_no_body(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    class Adapter:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def go(self):
            response = await self._transport.request_raw("x")
            return response.get("location")
    """

    assert reads_of(tmp_path, source) == {}


def test_a_helper_is_checked_per_caller_and_never_merged(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    def link_title(link):
        return link.get("title") if isinstance(link, dict) else None

    class Adapter:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def wire_caller(self):
            payload = await self._transport.get_json("x")
            return link_title(payload.get("_links", {}).get("project"))

        def plain_caller(self):
            return link_title({"title": "x"})
    """
    reads = reads_of(tmp_path, source)

    assert shape(reads["m.py:Adapter.wire_caller"]) >= {(("_links", "project"), "title", "get")}
    assert "m.py:Adapter.plain_caller" not in reads
    assert "m.py:link_title" not in reads


def test_a_terminal_function_keeps_its_reads_and_passes_none_upward(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    def normalize(payload):
        return payload.get("name")

    class Adapter:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def get(self):
            payload = await self._transport.get_json("x")
            return normalize(payload)
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:normalize": ("payload",)})

    assert shape(reads["m.py:normalize"]) == {((), "name", "get")}
    assert "m.py:Adapter.get" not in reads


def test_a_non_terminal_helper_called_with_a_body_puts_its_reads_into_the_caller(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    def normalize(payload):
        return payload.get("name")

    class Adapter:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def get(self):
            payload = await self._transport.get_json("x")
            return normalize(payload)
    """
    reads = reads_of(tmp_path, source)

    assert shape(reads["m.py:Adapter.get"]) == {((), "name", "get")}
    assert "m.py:normalize" not in reads


def test_self_methods_bind_their_parameters(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    class Adapter:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        def _record(self, payload):
            links = payload.get("_links", {})
            return links.get("project")

        async def list_all(self):
            payload = await self._transport.get_json("x")
            return [self._record(item) for item in payload.get("_embedded", {}).get("elements", [])]
    """
    reads = reads_of(tmp_path, source)["m.py:Adapter.list_all"]

    assert (("_embedded", "elements", "*", "_links"), "project", "get") in shape(reads)


def test_dict_copies_and_spreads_keep_the_origin(tmp_path: Path) -> None:
    source = """
    def normalize(payload):
        links = dict(payload.get("_links", {}))
        merged = {**links}
        return merged.get("project")
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:normalize": ("payload",)})["m.py:normalize"]

    assert (("_links",), "project", "get") in shape(reads)


def test_a_lambda_that_captures_a_body_reads_in_the_enclosing_context(tmp_path: Path) -> None:
    source = """
    def build(payload):
        return make(summary=lambda: payload.get("name"))

    def make(summary):
        return summary
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:build": ("payload",)})["m.py:build"]

    assert ((), "name", "get") in shape(reads)


def test_the_version_gate_returns_what_its_callable_returns(tmp_path: Path) -> None:
    source = """
    from .transport import Transport
    from .gate import call_version_gated

    class Adapter:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def go(self):
            payload = await call_version_gated(lambda: self._transport.get_json("x"), feature="f", floor="1")
            return payload.get("name")
    """
    gate = """
    async def call_version_gated(call, *, feature, floor):
        return await call()
    """

    assert ((), "name", "get") in shape(reads_of(tmp_path, source, gate=gate)["m.py:Adapter.go"])


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("def f(payload):\n    return payload.items()\n", "iteration"),
        ("def f(payload, key):\n    return payload.get(key)\n", "dynamic key"),
        ("def f(payload, key):\n    return payload[key]\n", "dynamic key"),
        ("def f(payload):\n    payload.setdefault('a', 1)\n", "setdefault"),
        ("def f(payload):\n    return [payload.get('a')]\n", "literal container"),
        ("import json\n\ndef f(payload):\n    return json.dumps(payload)\n", "dumps"),
        ("def f(payload):\n    return unknown_function(payload)\n", "unknown_function"),
    ],
)
def test_what_the_model_cannot_follow_is_reported_for_a_terminal(tmp_path: Path, source: str, reason: str) -> None:
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert any(f.kind == "unresolved" and reason in f.reason for f in found), found


def test_a_body_held_as_an_attribute_is_reported(tmp_path: Path) -> None:
    source = """
    class Holder:
        def keep(self, payload):
            self.saved = payload
    """

    assert any(
        "attribute" in f.reason for f in findings_of(tmp_path, source, terminals={"m.py:Holder.keep": ("payload",)})
    )


def test_a_finding_on_a_parameter_counts_only_when_a_caller_binds_a_body_to_it(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    def helper(value):
        return value.items()

    class Adapter:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def wire(self):
            payload = await self._transport.get_json("x")
            return helper(payload)

        def plain(self):
            return helper({"a": 1})
    """
    found = findings_of(tmp_path, source)

    assert [(f.kind, f.context) for f in found] == [("unresolved", "m.py:helper")]
    (tmp_path / "b").mkdir()
    assert not findings_of(tmp_path / "b", source.replace("return helper(payload)", "return None"))


def test_a_nested_function_parameter_is_of_unknown_origin_and_its_reads_are_unclassified(tmp_path: Path) -> None:
    source = """
    def f(payload):
        def check(raw):
            return raw.get("_links")
        return check(payload)
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert any(f.kind == "unclassified" for f in found)


def test_recursion_through_a_body_is_unresolved(tmp_path: Path) -> None:
    source = """
    def walk(node):
        return walk(node.get("child"))

    def start(payload):
        return walk(payload)
    """
    found = findings_of(tmp_path, source, terminals={"m.py:start": ("payload",)})

    assert any("recursion" in f.reason for f in found), found


def test_a_function_that_reads_a_parameter_nobody_binds_is_unbound(tmp_path: Path) -> None:
    source = """
    def orphan(payload):
        return payload.get("name")
    """

    assert [f.kind for f in findings_of(tmp_path, source)] == ["unbound"]


def test_a_comprehension_element_path_has_a_star(tmp_path: Path) -> None:
    source = """
    def f(payload):
        return [item.get("id") for item in payload.get("items", []) if item.get("ok")]
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert {(("items", "*"), "id"), (("items", "*"), "ok")} <= {(tuple(r.path), r.key) for r in reads}


def test_a_record_field_that_holds_a_body_is_a_source(tmp_path: Path) -> None:
    ports = """
    from dataclasses import dataclass
    from typing import Any

    @dataclass
    class ThingRecord:
        payload: dict[str, Any]
    """
    source = """
    from .app.ports.thing import ThingRecord

    def use(record: ThingRecord):
        return record.payload.get("name")
    """
    reads = reads_of(tmp_path, source, app__ports__thing=ports)["m.py:use"]

    assert ((), "name", "get") in shape(reads)


def test_a_value_the_model_loses_in_a_helper_counts_only_against_callers_that_bind_a_body(tmp_path: Path) -> None:
    source = """
    def lose(value):
        return mystery(value)

    def use(payload):
        return lose(payload).get("k")

    def plain():
        return lose({"a": 1}).get("k")
    """
    found = findings_of(tmp_path, source, terminals={"m.py:use": ("payload",)})

    assert [(f.kind, f.context) for f in found if f.kind == "unclassified"] == [("unclassified", "m.py:lose")] or any(
        f.kind == "unclassified" and f.context == "m.py:use" for f in found
    )
    assert not any(f.context == "m.py:plain" for f in found)


def test_a_chain_of_rebindings_that_needs_several_passes_still_reaches_the_read(tmp_path: Path) -> None:
    source = """
    def f(payload):
        a = b = c = d = e = None
        for _ in range(6):
            e = d
            d = c
            c = b
            b = a
            a = payload
        return e.get("deep")
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert ((), "deep", "get") in shape(reads)


def test_a_match_capture_of_a_body_is_reported_not_skipped(tmp_path: Path) -> None:
    source = """
    def f(payload):
        match payload:
            case {"node": node}:
                return node.get("id")
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert {f.kind for f in found} >= {"unresolved", "unclassified"}


def test_a_generator_helper_yields_the_elements_of_the_body_it_walks(tmp_path: Path) -> None:
    source = """
    def each(payload):
        for element in payload.get("elements", []):
            yield element

    def use(payload):
        return [item.get("id") for item in each(payload)]

    def spread(payload):
        yield from payload.get("elements", [])

    def use_spread(payload):
        for item in spread(payload):
            item.get("name")
    """
    result = reads_of(tmp_path, source, terminals={"m.py:use": ("payload",), "m.py:use_spread": ("payload",)})

    assert (("elements", "*"), "id", "get") in shape(result["m.py:use"])
    assert (("elements", "*"), "name", "get") in shape(result["m.py:use_spread"])


def test_a_generator_that_yields_something_else_than_an_element_is_reported(tmp_path: Path) -> None:
    source = """
    def f(payload):
        yield payload.get("name")
    """

    assert any("generator" in f.reason for f in findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)}))


def test_classmethods_staticmethods_and_properties_are_followed(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    class Reader:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        @classmethod
        def named(cls, payload):
            return payload.get("name")

        @staticmethod
        def titled(payload):
            return payload.get("title")

        @staticmethod
        def labelled(payload):
            return payload.get("label")

        @property
        def page(self):
            return self._cached

        async def go(self):
            payload = await self._transport.get_json("x")
            return self.named(payload), Reader.titled(payload), self.labelled(payload), self.page
    """
    reads = reads_of(tmp_path, source)["m.py:Reader.go"]

    assert {(tuple(r.path), r.key) for r in reads} >= {((), "name"), ((), "title"), ((), "label")}


def test_getattr_with_a_constant_name_is_the_attribute_and_a_computed_name_on_a_body_record_is_reported(
    tmp_path: Path,
) -> None:
    ports = """
    from dataclasses import dataclass
    from typing import Any

    @dataclass
    class ThingRecord:
        payload: dict[str, Any]
    """
    source = """
    from .app.ports.thing import ThingRecord

    def constant(record: ThingRecord):
        return getattr(record, "payload").get("name")

    def computed(record: ThingRecord, field):
        return getattr(record, field)
    """
    package = plant(tmp_path, m=source, transport=PLANTED_TRANSPORT, app__ports__thing=ports)
    result = adapter_reads.analyse(package)

    assert ((), "name", "get") in shape(result.reads["m.py:constant"])
    assert any(f.context == "m.py:computed" and "getattr" in f.reason for f in result.findings)


def test_a_function_is_found_through_an_alias_and_through_a_reexport_and_a_class_through_an_import_alias(
    tmp_path: Path,
) -> None:
    source = """
    from .facade import norm
    from .transport import Transport as Wire

    class A:
        def __init__(self, transport: Wire) -> None:
            self._transport = transport

        async def go(self):
            payload = await self._transport.get_json("x")
            return norm(payload), alias(payload)

    def real(payload):
        return payload.get("through_alias")

    alias = real
    """
    facade = "from .impl import norm\n"
    impl = "def norm(payload):\n    return payload.get('through_reexport')\n"
    reads = reads_of(tmp_path, source, facade=facade, impl=impl)["m.py:A.go"]

    assert {r.key for r in reads} == {"through_alias", "through_reexport"}


def test_a_factory_return_type_and_a_constructor_type_the_attribute_they_are_assigned_to(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    def make(settings) -> Transport: ...

    class A:
        def __init__(self, settings) -> None:
            self._transport = make(settings)

        async def go(self):
            payload = await self._transport.get_json("x")
            return payload.get("name")
    """

    assert ((), "name", "get") in shape(reads_of(tmp_path, source)["m.py:A.go"])


def test_a_parameter_or_return_declared_as_a_class_or_scalar_is_no_body(tmp_path: Path) -> None:
    models = """
    from dataclasses import dataclass
    from typing import Any

    @dataclass
    class Summary:
        id: str
        raw: dict[str, Any]
    """
    source = """
    from .models import Summary

    def build(payload, summary: Summary, name: str) -> Summary:
        return Summary(id=payload.get("id"), raw=payload.get("raw"))

    def use(summary: Summary):
        return summary.id
    """
    package = plant(tmp_path, m=source, transport=PLANTED_TRANSPORT, models=models)
    result = adapter_reads.analyse(package, terminals={"m.py:build": ("payload",)})

    assert shape(result.reads["m.py:build"]) == {((), "id", "get"), ((), "raw", "get")}
    reasons = [f.reason for f in result.findings]
    assert any("'raw' of Summary" in reason for reason in reasons)
    assert not any("'id' of Summary" in reason for reason in reasons)
    assert "m.py:use" not in result.reads


def test_a_recursive_call_chain_is_opaque_for_every_function_on_the_cycle(tmp_path: Path) -> None:
    source = """
    def first(node):
        return second(node.get("a"))

    def second(node):
        return first(node.get("b"))

    def start(payload):
        return first(payload)
    """
    found = findings_of(tmp_path, source, terminals={"m.py:start": ("payload",)})

    assert any("recursion" in f.reason for f in found), found


def test_a_body_deeper_than_the_path_cap_is_cut_and_reported(tmp_path: Path) -> None:
    source = """
    def f(payload):
        return payload.get("a").get("b").get("c").get("d").get("e").get("f").get("g").get("h").get("i").get("j")
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert any("depth cap" in f.reason for f in found)


def test_a_helper_called_only_by_an_unbound_caller_is_still_unbound(tmp_path: Path) -> None:
    source = """
    def norm(payload):
        return payload.get("phantom")

    def caller(record):
        return norm(record)
    """

    assert {(f.kind, f.context) for f in findings_of(tmp_path, source)} >= {("unbound", "m.py:norm")}


def test_a_callable_parameter_that_a_caller_binds_to_a_transport_call_hands_its_result_to_the_reader(
    tmp_path: Path,
) -> None:
    source = """
    from .transport import Transport

    async def page(fetch):
        payload = await fetch(1)
        return payload.get("total")

    class A:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def go(self):
            return await page(lambda number: self._transport.get_json("x"))
    """
    reads = reads_of(tmp_path, source)

    assert ((), "total", "get") in shape(reads["m.py:A.go"])


def test_a_membership_test_on_a_property_may_be_a_substring_test_and_is_recorded_as_ambiguous(tmp_path: Path) -> None:
    source = """
    def f(payload):
        return "raw" in payload["description"], "update" in payload["_links"]
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert {(tuple(r.path), r.key, r.how) for r in reads if r.key in {"raw", "update"}} == {
        (("description",), "raw", "in?"),
        (("_links",), "update", "in"),
    }


def test_a_body_passed_to_a_protocol_method_is_fine_for_a_wire_parameter_and_reported_for_a_request_one(
    tmp_path: Path,
) -> None:
    ports = """
    from typing import Any, Protocol

    class WorkPackageApi(Protocol):
        def to_record(self, payload: dict[str, Any]) -> None: ...
        def commit_update(self, payload: dict[str, Any]) -> None: ...
    """
    source = """
    from .transport import Transport
    from .app.ports.thing import WorkPackageApi

    class A:
        def __init__(self, transport: Transport, api: WorkPackageApi) -> None:
            self._transport = transport
            self._api = api

        async def good(self):
            payload = await self._transport.get_json("x")
            return self._api.to_record(payload)

        async def bad(self):
            payload = await self._transport.get_json("x")
            return self._api.commit_update(payload)
    """
    found = findings_of(tmp_path, source, app__ports__thing=ports)

    assert [(f.kind, f.context) for f in found if f.kind == "unresolved"] == [("unresolved", "m.py:A.bad")]


def test_the_census_covers_parameters_callbacks_typed_dicts_and_containers_of_raw_mappings(tmp_path: Path) -> None:
    (tmp_path / "app" / "ports").mkdir(parents=True)
    (tmp_path / "app" / "ports" / "thing.py").write_text(
        textwrap.dedent(
            """
            from collections.abc import Callable, Awaitable
            from dataclasses import dataclass
            from typing import Any, Protocol, TypedDict

            class Shape(TypedDict):
                body: dict[str, Any]

            @dataclass
            class Holder:
                pages: tuple[dict[str, Any], ...]
                fetch: Callable[[int], Awaitable[dict[str, Any]]]
                hook: Callable[[dict[str, Any]], None]
                done: Callable[[str], int]
                count: int
                names: list[str]

            class Api(Protocol):
                def one(self, payload: dict[str, Any], limit: int) -> list[Mapping[str, Any]]: ...
            """
        )
    )
    found = {(m.kind, m.owner, m.name) for m in wire_sources.census(tmp_path)}

    assert found == {
        ("field", "Shape", "body"),
        ("field", "Holder", "pages"),
        ("field", "Holder", "fetch"),
        ("field", "Holder", "hook"),
        ("method", "Api", "one"),
        ("parameter", "Api", "one.payload"),
    }


def test_a_body_leaf_handed_to_a_string_function_ends_there_and_nothing_is_reported(tmp_path: Path) -> None:
    source = """
    import re
    from urllib.parse import urlsplit

    PATTERN = re.compile("x")

    def f(payload):
        href = payload.get("href")
        return urlsplit(href), PATTERN.fullmatch(href), isinstance(href, str)
    """

    assert not findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})


def test_a_function_on_a_call_cycle_is_opaque_for_every_caller_not_only_the_one_that_found_the_cycle(
    tmp_path: Path,
) -> None:
    source = """
    def first(node):
        return second(node.get("a"))

    def second(node):
        return first(node.get("b"))

    def start(payload):
        return first(payload)

    def other(payload):
        return second(payload)
    """
    found = findings_of(tmp_path, source, terminals={"m.py:start": ("payload",), "m.py:other": ("payload",)})

    assert {f.context for f in found if "recursion" in f.reason} == {"m.py:start", "m.py:other"}


def test_a_declared_scalar_return_ends_the_flow_of_a_body_leaf(tmp_path: Path) -> None:
    source = """
    def title(payload) -> str:
        return payload.get("title")

    def use(payload):
        return title(payload).capitalize()
    """

    assert not findings_of(tmp_path, source, terminals={"m.py:use": ("payload",)})


def test_a_property_that_returns_a_body_hands_it_to_the_reader(tmp_path: Path) -> None:
    ports = """
    from dataclasses import dataclass
    from typing import Any

    @dataclass
    class ThingRecord:
        payload: dict[str, Any]
    """
    source = """
    from typing import Any
    from .app.ports.thing import ThingRecord

    class Holder:
        _record: ThingRecord

        @property
        def body(self) -> dict[str, Any]:
            return self._record.payload.get("nested")

        def name(self):
            return self.body.get("phantom")
    """
    reads = reads_of(tmp_path, source, app__ports__thing=ports)

    assert (("nested",), "phantom", "get") in shape(reads["m.py:Holder.name"])


def test_a_scalar_annotation_does_not_erase_what_an_any_value_carried_in(tmp_path: Path) -> None:
    source = """
    from typing import Any

    def take(x: str):
        y: Any = x
        return y["phantom"]

    def give(x: Any) -> str:
        z: str = x
        return z

    def use(payload):
        return take(payload), give(payload)["phantom"]
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:use": ("payload",)})["m.py:use"]

    assert shape(reads) >= {((), "phantom", "sub")}


def test_an_imported_name_that_looks_like_a_string_function_is_not_one(tmp_path: Path) -> None:
    source = """
    from .helpers import urlsplit
    from .plugin import cache

    def f(payload):
        return urlsplit(payload)["phantom"], cache.search(payload)["other"]
    """
    helpers = "def urlsplit(payload):\n    return payload\n"
    plugin = "class Cache:\n    def search(self, payload):\n        return payload\n\ncache = Cache()\n"
    result = adapter_reads.analyse(
        plant(tmp_path, m=source, transport=PLANTED_TRANSPORT, helpers=helpers, plugin=plugin),
        terminals={"m.py:f": ("payload",)},
    )

    assert ((), "phantom", "sub") in shape(result.reads["m.py:f"])
    assert any(f.kind == "unresolved" and ".search()" in f.reason for f in result.findings)


def test_a_read_on_a_value_lost_in_an_unbound_function_is_unbound_not_silent(tmp_path: Path) -> None:
    source = """
    def f(payload):
        x = opaque(payload)
        return x["phantom"]
    """

    assert {(f.kind, f.context) for f in findings_of(tmp_path, source)} >= {("unbound", "m.py:f")}


def test_getattr_joins_its_default_and_a_json_decode_is_a_body_source(tmp_path: Path) -> None:
    source = """
    import json

    def f(payload):
        return getattr(object(), "missing", payload)["phantom"]

    def g(response):
        return json.loads(response)["a"], response.json()["b"]
    """
    result = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert ((), "phantom", "sub") in shape(result["m.py:f"])
    assert {r.key for r in result["m.py:g"]} == {"a", "b"}


def test_the_fixpoint_follows_class_types_through_a_rebinding_chain(tmp_path: Path) -> None:
    ports = """
    from dataclasses import dataclass
    from typing import Any

    @dataclass
    class ThingRecord:
        payload: dict[str, Any]
    """
    source = """
    from .app.ports.thing import ThingRecord

    def f(record: ThingRecord):
        a = b = c = d = e = None
        for _ in range(6):
            e = d
            d = c
            c = b
            b = a
            a = record
        return e.payload["phantom"]
    """
    reads = reads_of(tmp_path, source, app__ports__thing=ports)

    assert ((), "phantom", "sub") in shape(reads["m.py:f"])


def test_a_dataclass_field_inherited_from_a_base_is_a_body_source(tmp_path: Path) -> None:
    ports = """
    from dataclasses import dataclass
    from typing import Any

    @dataclass
    class ThingRecord:
        payload: dict[str, Any]

    @dataclass
    class SubRecord(ThingRecord):
        extra: int = 0
    """
    source = """
    from .app.ports.thing import SubRecord

    def f(record: SubRecord):
        return record.payload["phantom"]
    """

    assert ((), "phantom", "sub") in shape(reads_of(tmp_path, source, app__ports__thing=ports)["m.py:f"])


def test_a_type_alias_and_a_type_variable_do_not_hide_a_body_member(tmp_path: Path) -> None:
    (tmp_path / "app" / "ports").mkdir(parents=True)
    (tmp_path / "app" / "ports" / "thing.py").write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass
            from typing import Any, Protocol, TypeVar

            Json = dict[str, Any]
            Plain = dict[str, str]
            T = TypeVar("T")

            @dataclass
            class Holder:
                body: Json
                names: Plain
                anything: T

            class Api(Protocol):
                def fetch(self) -> Json: ...
            """
        )
    )
    found = {(m.kind, m.owner, m.name) for m in wire_sources.census(tmp_path)}

    assert found == {("field", "Holder", "body"), ("field", "Holder", "anything"), ("method", "Api", "fetch")}


def test_a_spread_a_max_a_keyword_catch_all_and_a_starred_literal_do_not_drop_a_body(tmp_path: Path) -> None:
    source = """
    def helper(**kw):
        return kw

    def f(payload):
        a = max(payload.get("elements", []))["one"]
        c = helper(payload=payload)
        d = helper(**{"payload": payload})
        return a, c, d

    def spread(payload):
        return [*payload.get("elements", [])]
    """
    result = adapter_reads.analyse(
        plant(tmp_path, m=source, transport=PLANTED_TRANSPORT),
        terminals={"m.py:f": ("payload",), "m.py:spread": ("payload",)},
    )

    assert (("elements", "*"), "one", "sub") in shape(result.reads["m.py:f"])
    reasons = {f.reason for f in result.findings}
    assert any("**kwargs" in r for r in reasons) and any("spread" in r for r in reasons)
    assert any(f.context == "m.py:spread" and "literal container" in f.reason for f in result.findings)


def test_an_attribute_or_method_a_port_declares_on_a_receiver_of_unknown_type_is_reported(tmp_path: Path) -> None:
    ports = """
    from dataclasses import dataclass
    from typing import Any

    @dataclass
    class ThingRecord:
        payload: dict[str, Any]
    """
    source = """
    def f():
        thing = object()
        return thing.payload["phantom"], thing.get_json("x")
    """
    found = findings_of(tmp_path, source, app__ports__thing=ports)

    assert {f.reason.split(" of a value")[0] for f in found if "unknown type" in f.reason} == {
        "attribute 'payload'",
        "method get_json()",
    }


def test_a_tuple_return_types_each_unpacked_name(tmp_path: Path) -> None:
    ports = """
    from dataclasses import dataclass
    from typing import Any

    @dataclass
    class ThingRecord:
        payload: dict[str, Any]
    """
    source = """
    from .app.ports.thing import ThingRecord

    def pair() -> tuple[ThingRecord, int]: ...

    def f():
        record, count = pair()
        return record.payload["phantom"]
    """

    assert ((), "phantom", "sub") in shape(reads_of(tmp_path, source, app__ports__thing=ports)["m.py:f"])


def test_a_method_called_through_its_class_with_an_explicit_self_binds_the_right_parameter(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    class A:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        def norm(self, payload):
            return payload.get("phantom")

        async def go(self):
            payload = await self._transport.get_json("x")
            return A.norm(self, payload)
    """

    assert ((), "phantom", "get") in shape(reads_of(tmp_path, source)["m.py:A.go"])


def test_a_terminal_that_returns_part_of_its_body_hands_it_to_the_caller(tmp_path: Path) -> None:
    source = """
    def links_of(payload):
        return payload.get("_links", {})

    def use(payload):
        return links_of(payload).get("project")
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:links_of": ("payload",), "m.py:use": ("payload",)})

    assert (("_links",), "project", "get") in shape(reads["m.py:use"])


def test_an_implementation_of_a_wire_protocol_parameter_has_its_body_bound_by_declaration(tmp_path: Path) -> None:
    transport = """
    from typing import Any, Protocol

    class ResponseLearner(Protocol):
        def learn(self, payload: Any) -> None: ...
    """
    source = """
    class Directory:
        def learn(self, payload):
            return payload.get("name"), payload.items()
    """
    package = plant(tmp_path, m=source, app__transport__learning_transport=transport)
    result = adapter_reads.analyse(package)

    assert shape(result.reads["m.py:Directory.learn"]) == {((), "name", "get")}
    assert any(f.kind == "unresolved" and f.context == "m.py:Directory.learn" for f in result.findings)
    assert not any(f.kind == "unbound" for f in result.findings)


def test_the_parameter_ledger_has_no_stale_entry_and_names_the_raw_form_of_every_form_parser() -> None:
    members = {(m.owner, m.name) for m in wire_sources.census(PACKAGE) if m.kind == "parameter"}

    assert (wire_sources._WIRE_PARAMETERS | wire_sources._REQUEST_PARAMETERS) == members
    assert not wire_sources._WIRE_PARAMETERS & wire_sources._REQUEST_PARAMETERS
    assert ("WorkPackageApi", "parse_form.form") in wire_sources._WIRE_PARAMETERS
    assert ("TimeEntryApi", "parse_form_result.form") in wire_sources._WIRE_PARAMETERS


def test_a_generator_that_yields_a_whole_body_hands_a_lost_value_to_the_caller(tmp_path: Path) -> None:
    source = """
    def each(payload):
        yield payload

    def use(payload):
        for item in each(payload):
            item.get("phantom")
    """
    found = findings_of(tmp_path, source, terminals={"m.py:use": ("payload",)})

    assert any(f.kind == "unclassified" and "'phantom'" in f.reason for f in found)


def test_every_statement_form_carries_the_body_and_records_its_reads(tmp_path: Path) -> None:
    source = """
    def helper(payload):
        return payload.get("by_keyword")

    def f(payload):
        try:
            payload.get("try_body")
        except ValueError:
            payload.get("handler")
        else:
            payload.get("try_else")
        finally:
            payload.get("finalbody")
        while payload.get("while_test"):
            payload.get("while_body")
        else:
            payload.get("while_else")
        for item in payload.get("loop", []):
            item.get("for_body")
        else:
            payload.get("for_else")
        with payload.get("ctx") as context:
            context.get("with_body")
        total = None
        total += payload.get("aug")
        total.get("after_aug")
        assert payload.get("assert_expr"), payload.get("assert_msg")
        helper(payload=payload)
        if "absent" not in payload:
            raise ValueError(payload.get("raise_expr"))
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert {r.key for r in reads} == {
        "try_body", "handler", "try_else", "finalbody", "while_test", "while_body", "while_else", "loop",
        "for_body", "for_else", "ctx", "with_body", "aug", "after_aug", "assert_expr", "assert_msg", "by_keyword",
        "absent", "raise_expr",
    }  # fmt: skip
    assert {(r.key, r.how) for r in reads if r.key == "absent"} == {("absent", "in")}


def test_a_union_with_a_raw_mapping_on_either_side_holds_a_body(tmp_path: Path) -> None:
    (tmp_path / "app" / "ports").mkdir(parents=True)
    (tmp_path / "app" / "ports" / "thing.py").write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass
            from typing import Any

            @dataclass
            class Holder:
                left: dict[str, Any] | None
                right: None | dict[str, Any]
                neither: int | None
            """
        )
    )

    assert {m.name for m in wire_sources.census(tmp_path)} == {"left", "right"}


RECORD_PORTS = """
from dataclasses import dataclass
from typing import Any

@dataclass
class ThingRecord:
    payload: dict[str, Any]
"""


def test_a_union_of_a_class_and_a_raw_mapping_keeps_the_provenance_of_what_it_receives(tmp_path: Path) -> None:
    source = """
    from typing import Any

    class Marker: ...

    def take(payload: Marker | dict[str, Any]):
        if isinstance(payload, dict):
            return payload["secret"]

    def give(payload: Any) -> Marker | dict[str, Any]:
        return payload

    def use(payload):
        return give(payload)["other"]
    """
    result = reads_of(tmp_path, source, terminals={"m.py:take": ("payload",), "m.py:use": ("payload",)})

    assert ((), "secret", "sub") in shape(result["m.py:take"])
    assert ((), "other", "sub") in shape(result["m.py:use"])


def test_two_alternatives_of_different_classes_are_an_unknown_type_and_the_net_reports_it(tmp_path: Path) -> None:
    ports = RECORD_PORTS + "\n@dataclass\nclass OtherRecord:\n    payload: str\n"
    source = """
    from .app.ports.thing import OtherRecord, ThingRecord

    def f(flag, a: OtherRecord, b: ThingRecord):
        chosen = a if flag else b
        return chosen.payload["secret"]
    """
    found = findings_of(tmp_path, source, app__ports__thing=ports)

    assert any("unknown type" in f.reason for f in found)


def test_an_alias_of_any_a_renamed_import_and_a_bare_container_hide_no_body_member(tmp_path: Path) -> None:
    (tmp_path / "app" / "ports").mkdir(parents=True)
    (tmp_path / "app" / "ports" / "thing.py").write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass
            from typing import Any as Wild, Dict

            Raw = Wild
            Plain = dict

            @dataclass
            class Holder:
                a: Raw
                b: Plain
                c: Dict[str, str]
                d: Wild
            """
        )
    )

    assert {m.name for m in wire_sources.census(tmp_path)} == {"a", "b", "d"}


def test_a_type_alias_with_two_meanings_in_the_tree_is_an_error_not_a_guess(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("from typing import Any\nBody = dict[str, Any]\n")
    (tmp_path / "two.py").write_text("Body = dict[str, str]\n")

    with pytest.raises(ValueError, match="Body"):
        wire_sources.type_names(tmp_path)


def test_a_function_called_quote_is_a_standard_library_function_only_when_it_was_imported_as_one(
    tmp_path: Path,
) -> None:
    source = """
    from third_party import quote
    from urllib.parse import urlsplit

    def foreign(payload):
        return quote(payload)

    def local(payload, format):
        return format(payload)

    def stdlib(payload):
        return urlsplit(payload.get("href"))
    """
    result = adapter_reads.analyse(
        plant(tmp_path, m=source, transport=PLANTED_TRANSPORT),
        terminals={"m.py:foreign": ("payload",), "m.py:local": ("payload",), "m.py:stdlib": ("payload",)},
    )

    assert {f.context for f in result.findings if f.kind == "unresolved"} == {"m.py:foreign", "m.py:local"}


def test_the_receiver_and_the_index_of_an_assignment_target_are_read(tmp_path: Path) -> None:
    source = """
    def f(payload, output):
        output[payload["one"]] = 1
        output[payload["two"]] += 1
        for output[payload["three"]] in range(2):
            pass
        del output[payload["four"]]
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert {r.key for r in reads} == {"one", "two", "three", "four"}


def test_a_try_star_a_handler_type_a_default_and_a_decorator_are_walked(tmp_path: Path) -> None:
    source = """
    def f(payload, errors):
        try:
            payload["body"]
        except* errors[payload["handler_type"]]:
            payload["handler"]

        def helper(value=payload["default"]):
            return value

        @errors[payload["decorator"]]
        def decorated():
            return 1

        return (lambda x=payload["lambda_default"]: x)
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert {r.key for r in reads} == {"body", "handler_type", "handler", "default", "decorator", "lambda_default"}


def test_a_get_fallback_is_joined_into_the_result(tmp_path: Path) -> None:
    source = """
    def f(payload, fallback):
        return payload.get("missing", fallback).get("secret")
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload", "fallback")})["m.py:f"]

    assert {(tuple(r.path), r.key) for r in reads} >= {(("missing",), "secret"), ((), "secret")}


def test_a_body_stored_through_an_augmented_assignment_is_reported(tmp_path: Path) -> None:
    source = """
    class Holder:
        def keep(self, payload, table):
            self.saved += payload
            table["k"] |= payload
    """
    found = findings_of(tmp_path, source, terminals={"m.py:Holder.keep": ("payload",)})

    assert {f.reason for f in found} >= {"a body held as an attribute", "a body stored into a container"}


def test_a_type_variable_return_does_not_become_the_class_of_the_result(tmp_path: Path) -> None:
    ports = (
        RECORD_PORTS
        + """
from typing import Protocol

class ThingApi(Protocol):
    async def get(self, thing_id: int) -> ThingRecord: ...
"""
    )
    gate = """
    from typing import Awaitable, Callable, TypeVar

    _T = TypeVar("_T")

    async def call_version_gated(call: Callable[[], Awaitable[_T]], *, feature: str) -> _T:
        return await call()
    """
    source = """
    from .app.ports.thing import ThingApi
    from .gate import call_version_gated

    class Service:
        def __init__(self, api: ThingApi) -> None:
            self._api = api

        async def go(self):
            record = await call_version_gated(lambda: self._api.get(1), feature="f")
            return record.payload["secret"]
    """
    found = findings_of(tmp_path, source, app__ports__thing=ports, gate=gate)

    assert any("unknown type" in f.reason for f in found)


def test_a_function_handed_over_by_name_stands_for_what_it_returns(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    async def page_of(offset, fetch):
        return await fetch(offset)

    class A:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def fetch_page(self, offset):
            return await self._transport.get_json("x")

        async def go(self):
            payload = await page_of(0, self.fetch_page)
            return payload.get("phantom")
    """

    assert ((), "phantom", "get") in shape(reads_of(tmp_path, source)["m.py:A.go"])


def test_a_port_call_with_a_scalar_argument_returns_the_record_it_declares(tmp_path: Path) -> None:
    ports = """
    from dataclasses import dataclass
    from typing import Any, Protocol

    @dataclass
    class ThingRecord:
        payload: dict[str, Any]

    class WorkPackageApi(Protocol):
        async def get(self, thing_id: int) -> ThingRecord: ...
        async def commit_update(self, payload: dict[str, Any]) -> ThingRecord: ...
    """
    source = """
    from .app.ports.thing import WorkPackageApi

    class Service:
        def __init__(self, api: WorkPackageApi) -> None:
            self._api = api

        async def get(self, thing_id: int):
            record = await self._api.get(thing_id)
            return record.payload["secret"]
    """
    result = adapter_reads.analyse(plant(tmp_path, m=source, transport=PLANTED_TRANSPORT, app__ports__thing=ports))

    assert ((), "secret", "sub") in shape(result.reads["m.py:Service.get"])
    assert not any("unknown type" in f.reason for f in result.findings)
    wired = (
        adapter_reads.analyse(
            plant(
                tmp_path / "b",
                m=source.replace('record.payload["secret"]', "record.name.strip()"),
                transport=PLANTED_TRANSPORT,
                app__ports__thing=ports,
            ),
            terminals={"m.py:Service.get": ("thing_id",)},
        )
        if (tmp_path / "b").mkdir() is None
        else None
    )
    assert wired is not None and [f.reason for f in wired.findings if f.kind == "unresolved"] == [
        "a body passed to the request-side parameter of WorkPackageApi.get()"
    ]


def test_a_finding_reached_through_a_terminal_and_a_concrete_origin_is_counted_once(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    def helper(value):
        return value.items()

    def normalize(payload):
        return helper(payload)

    class A:
        def __init__(self, transport: Transport) -> None:
            self._transport = transport

        async def go(self):
            return helper(await self._transport.get_json("x"))
    """
    found = findings_of(tmp_path, source, terminals={"m.py:normalize": ("payload",)})

    assert len([f for f in found if f.kind == "unresolved"]) == 1


def test_a_conditional_entry_without_a_live_read_is_stale_even_with_no_versions(tmp_path: Path) -> None:
    row = adapter_reads.Row(("r.rb",), conditional={"property|id": adapter_reads.Conditional((), "unused")})

    assert adapter_reads.stale_entries([], row, SNAPSHOT) == ["conditional property|id"]


def test_an_exemption_that_matches_every_finding_or_names_no_line_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="matches every finding"):
        adapter_reads.apply_exemptions(
            [], [adapter_reads.Exemption("unresolved", "m.py:f", ".*", "x", "lazy")], tmp_path
        )
    with pytest.raises(ValueError, match="names no source line"):
        adapter_reads.apply_exemptions(
            [], [adapter_reads.Exemption("unresolved", "m.py:f", "a", " ", "lazy")], tmp_path
        )


def test_an_exemption_is_bound_to_the_kind_of_the_finding(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def f(payload):\n    return payload.items()\n")
    findings = [adapter_reads.Finding("unclassified", "m.py:f", 2, "read of 'a' on a value of unknown origin")]
    exemptions = [adapter_reads.Exemption("unresolved", "m.py:f", "read of", "return payload.items()", "wrong kind")]

    open_findings, stale = adapter_reads.apply_exemptions(findings, exemptions, tmp_path)

    assert open_findings == findings and stale == exemptions


def test_a_function_that_returns_a_declared_class_hands_no_body_on_and_a_walrus_carries_its_type(
    tmp_path: Path,
) -> None:
    source = """
    from .app.ports.thing import ThingRecord

    def make(payload) -> ThingRecord:
        return payload

    def use(payload, loader):
        return make(payload).get("object"), (record := loader(payload))

    def typed(record: ThingRecord):
        if (other := record):
            return other.payload["walrus"]
    """
    result = reads_of(tmp_path, source, terminals={"m.py:use": ("payload",)}, app__ports__thing=RECORD_PORTS)

    assert "m.py:use" not in result or ((), "object", "get") not in shape(result["m.py:use"])
    assert ((), "walrus", "sub") in shape(result["m.py:typed"])


def test_a_type_variable_bound_to_a_body_free_class_is_an_object(tmp_path: Path) -> None:
    (tmp_path / "app" / "ports").mkdir(parents=True)
    (tmp_path / "app" / "ports" / "thing.py").write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass
            from typing import TypeVar

            class Base: ...
            Bound = TypeVar("Bound", bound=Base)
            Free = TypeVar("Free")

            @dataclass
            class Holder:
                tied: Bound
                loose: Free
            """
        )
    )

    assert {m.name for m in wire_sources.census(tmp_path)} == {"loose"}


def test_a_loop_that_walks_down_a_body_ends_at_the_path_cap(tmp_path: Path) -> None:
    source = """
    def walk(payload):
        node = payload
        while node:
            node = node.get("child")

    def use(payload):
        return walk(payload)
    """
    found = findings_of(tmp_path, source, terminals={"m.py:use": ("payload",)})

    assert any("depth cap" in f.reason for f in found)


def test_a_class_defined_inside_a_function_is_walked_with_the_body_it_captures(tmp_path: Path) -> None:
    source = """
    def f(payload):
        class Local:
            def read(self):
                return payload.get("captured")

        return Local
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert ((), "captured", "get") in shape(reads)


def test_a_module_function_handed_over_by_name_stands_for_what_it_returns(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    async def page_of(offset, fetch):
        return await fetch(offset)

    async def fetch_page(offset, transport: Transport):
        return await transport.get_json("x")

    async def go():
        payload = await page_of(0, fetch_page)
        return payload.get("phantom")
    """

    assert ((), "phantom", "get") in shape(reads_of(tmp_path, source)["m.py:go"])


def test_a_chained_comparison_tests_membership_against_the_preceding_comparator(tmp_path: Path) -> None:
    source = """
    def f(payload):
        return 0 == "phantom" in payload
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert ((), "phantom", "in") in shape(reads)


def test_a_zero_argument_call_cycle_marks_every_read_in_it_unresolved(tmp_path: Path) -> None:
    source = """
    import json

    def first():
        data = json.loads("{}")
        data.get("phantom")
        return second()

    def second():
        return first()
    """
    found = findings_of(tmp_path, source)

    assert any(f.kind == "unresolved" and "call cycle" in f.reason for f in found)


def test_a_function_handed_over_by_name_keeps_the_path_of_what_it_returns(tmp_path: Path) -> None:
    source = """
    import json

    def fetch():
        return json.loads("{}").get("_links", {})

    def go():
        fn = fetch
        return fn().get("phantom")
    """
    reads = reads_of(tmp_path, source)["m.py:go"]

    assert (("_links",), "phantom", "get") in shape(reads)


def test_a_mapping_handed_to_a_string_method_is_not_a_leaf(tmp_path: Path) -> None:
    source = """
    def f(payload):
        return payload.get("template").format_map(payload)
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert any("format_map" in f.reason for f in found)


def test_a_list_that_collects_pages_hands_its_elements_to_the_caller(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    async def collect(transport: Transport):
        items = []
        page = await transport.get_json("x")
        items.extend(page.get("_embedded", {}).get("elements", []))
        return items

    async def go(transport: Transport):
        for item in await collect(transport):
            item.get("phantom")
    """
    reads = reads_of(tmp_path, source)["m.py:go"]

    assert (("_embedded", "elements", "*"), "phantom", "get") in shape(reads)


def test_a_function_that_returns_a_tuple_hands_its_members_to_an_unpacking_caller(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    async def fetch_page(transport: Transport):
        payload = await transport.get_json("x")
        return payload.get("_embedded", {}).get("elements", []), int(payload["total"])

    async def go(transport: Transport):
        elements, total = await fetch_page(transport)
        for element in elements:
            element.get("phantom")
    """
    reads = reads_of(tmp_path, source)["m.py:go"]

    assert (("_embedded", "elements", "*"), "phantom", "get") in shape(reads)


def test_two_assignments_of_different_classes_to_one_name_are_an_unknown_type(tmp_path: Path) -> None:
    ports = RECORD_PORTS + "\n@dataclass\nclass OtherRecord:\n    payload: str\n"
    source = """
    from .app.ports.thing import OtherRecord, ThingRecord

    def f(flag, a: ThingRecord, b: OtherRecord):
        if flag:
            chosen = b
        else:
            chosen = a
        return chosen.payload["secret"]
    """
    found = findings_of(tmp_path, source, app__ports__thing=ports)

    assert any("unknown type" in f.reason for f in found)


def test_a_union_of_two_classes_in_an_annotation_is_an_unknown_type(tmp_path: Path) -> None:
    ports = RECORD_PORTS + "\n@dataclass\nclass OtherRecord:\n    payload: str\n"
    source = """
    from .app.ports.thing import OtherRecord, ThingRecord

    def f(record: ThingRecord | OtherRecord):
        return record.payload["secret"]
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("record",)}, app__ports__thing=ports)

    assert any("attribute 'payload' of a body" in f.reason for f in found)


def test_an_attribute_of_a_plain_class_declared_as_a_raw_container_is_reported(tmp_path: Path) -> None:
    source = """
    from typing import Any

    class Cache:
        entries: dict[str, Any]

        def __init__(self, loaded: dict[str, Any]) -> None:
            self.loaded = loaded

        def read(self):
            return self.entries.get("a"), self.loaded.get("b")
    """
    found = findings_of(tmp_path, source)

    assert {f.reason.split(" of ")[0] for f in found if "able to hold a body" in f.reason} == {
        "attribute 'entries'",
        "attribute 'loaded'",
    }


def test_a_typed_dict_a_new_type_and_an_unknown_name_hold_a_body_in_the_census(tmp_path: Path) -> None:
    (tmp_path / "app" / "ports").mkdir(parents=True)
    (tmp_path / "app" / "ports" / "thing.py").write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass
            from typing import NewType, TypedDict
            from pydantic import JsonValue

            class Shape(TypedDict):
                a: int

            class Plain: ...

            Body = NewType("Body", dict)
            Count = NewType("Count", int)
            Small = int
            Wrapped = Small
            Alias = Shape
            PlainAlias = Plain

            @dataclass
            class Holder:
                shaped: Shape
                newtyped: Body
                unknown: JsonValue
                aliased: Alias
                plain: int
                counted: Count
                wrapped: Wrapped
                classed: PlainAlias
            """
        )
    )

    assert {m.name for m in wire_sources.census(tmp_path)} == {"shaped", "newtyped", "unknown", "aliased"}


def test_a_def_under_a_module_level_statement_a_nested_class_and_a_global_are_reported_unsupported(
    tmp_path: Path,
) -> None:
    source = """
    import sys

    if sys.platform == "x":
        def hidden(payload):
            return payload["a"]

    class Outer:
        class Inner:
            pass

    def f():
        global STATE
        STATE = 1
    """
    found = [f for f in findings_of(tmp_path, source) if f.kind == "unsupported"]

    assert len(found) == 3


def test_a_function_handed_over_by_name_that_depends_on_its_parameters_returns_an_unknown_value(tmp_path: Path) -> None:
    source = """
    def identity(value):
        return value

    async def page_of(fetch):
        return await fetch()

    async def go():
        payload = await page_of(identity)
        return payload.get("phantom")
    """
    found = findings_of(tmp_path, source)

    assert any(f.kind == "unclassified" and "'phantom'" in f.reason for f in found)


def test_a_parameter_declared_as_a_typed_dict_keeps_its_provenance(tmp_path: Path) -> None:
    source = """
    from typing import TypedDict

    class Body(TypedDict):
        a: int

    def f(body: Body):
        return body.get("phantom")
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("body",)})["m.py:f"]

    assert ((), "phantom", "get") in shape(reads)


def test_a_bare_typing_dict_and_list_are_raw_containers_in_the_census(tmp_path: Path) -> None:
    (tmp_path / "app" / "ports").mkdir(parents=True)
    (tmp_path / "app" / "ports" / "thing.py").write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass
            from typing import Dict, List

            @dataclass
            class Holder:
                a: Dict
                b: List
                c: Dict[str, int]
            """
        )
    )

    assert {m.name for m in wire_sources.census(tmp_path)} == {"a", "b"}


def test_a_function_whose_assignments_do_not_settle_within_the_pass_limit_is_opaque(tmp_path: Path) -> None:
    names = [f"v{n}" for n in range(40)]
    chain = "\n".join(f"            {names[n]} = {names[n - 1]}" for n in range(39, 0, -1))
    source = f"""
    def walk(payload):
        {" = ".join(names)} = None
        for _ in range(20):
{chain}
        {names[0]} = payload
        return {names[39]}.get("seen")
    """
    package = plant(tmp_path, m=source, transport=PLANTED_TRANSPORT)
    interpreter = adapter_reads.Interpreter(adapter_reads.Index(package), terminals={"m.py:walk": ("payload",)})
    summary = interpreter.summary("m.py:walk")

    assert summary.opaque and any("did not settle" in f.reason for f in summary.findings)


def test_a_read_on_a_bound_parameter_in_a_call_cycle_is_unresolved_at_the_read(tmp_path: Path) -> None:
    source = """
    def walk(node):
        node.get("phantom")
        return walk(node.get("child"))

    def start(payload):
        return walk(payload)
    """
    found = findings_of(tmp_path, source, terminals={"m.py:start": ("payload",)})

    assert any(f.context == "m.py:walk" and f.kind == "unresolved" and "'phantom'" in f.reason for f in found)


def test_a_recursive_function_called_without_a_body_hands_an_unknown_value_to_its_caller(tmp_path: Path) -> None:
    source = """
    from .transport import Transport

    async def fetch(transport: Transport, depth: int):
        if depth:
            return await fetch(transport, depth - 1)
        return await transport.get_json("x")

    async def go(transport: Transport):
        payload = await fetch(transport, 3)
        return payload.get("phantom")
    """
    found = findings_of(tmp_path, source)

    assert any(f.kind == "unclassified" and "'phantom'" in f.reason for f in found)


def test_append_add_insert_and_extend_collect_into_a_local_container(tmp_path: Path) -> None:
    source = """
    def f(payload):
        elements = []
        for element in payload.get("elements", []):
            elements.append(element)
        other = []
        other.insert(0, payload.get("second", []))
        merged = {}
        merged.update(inner=payload.get("third", {}))
        return [e.get("a") for e in elements], merged.get("b")
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert {(tuple(r.path), r.key) for r in reads} >= {(("elements", "*"), "a"), (("third",), "b")}


def test_an_element_that_is_no_element_of_a_body_is_reported_when_appended_and_a_lost_one_is_kept(
    tmp_path: Path,
) -> None:
    source = """
    def f(payload, loader):
        items = []
        items.append(payload.get("whole"))
        items.append(loader(payload))
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert any("not an element appended" in f.reason for f in found)


def test_a_parameter_container_changed_in_place_is_reported(tmp_path: Path) -> None:
    source = """
    def fill(into, payload):
        into.extend(payload.get("elements", []))

    def use(payload):
        bucket = []
        fill(bucket, payload)
        return [e.get("a") for e in bucket]
    """
    found = findings_of(tmp_path, source, terminals={"m.py:fill": ("payload", "into")})

    assert any("changed in place" in f.reason for f in found)


def test_an_untyped_local_object_that_is_no_container_does_not_collect(tmp_path: Path) -> None:
    source = """
    from external import Sink

    def f(payload):
        sink = Sink()
        sink.add(payload.get("elements", []))
        return [e.get("a") for e in sink]
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert any(f.kind == "unresolved" and f.reason == "a call of .add() with a body" for f in found)


def test_an_unknown_assignment_invalidates_a_class_the_name_had(tmp_path: Path) -> None:
    ports = RECORD_PORTS
    source = """
    from .app.ports.thing import ThingRecord

    def f(record: ThingRecord, loader):
        record = loader()
        return record.payload["secret"]
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("loader",)}, app__ports__thing=ports)

    assert any("attribute 'payload' of a body" in f.reason for f in found)


def test_a_declared_type_wins_over_the_empty_literal_it_is_initialised_with(tmp_path: Path) -> None:
    source = """
    from .app.ports.thing import ThingRecord

    def f(records_in):
        records: list[ThingRecord] = []
        for record in records:
            record.payload["secret"]
    """
    reads = reads_of(tmp_path, source, app__ports__thing=RECORD_PORTS)

    assert ((), "secret", "sub") in shape(reads["m.py:f"])


def test_a_tuple_target_and_a_with_target_reset_the_type_of_a_name(tmp_path: Path) -> None:
    source = """
    from .app.ports.thing import ThingRecord

    def f(record: ThingRecord, pairs, manager):
        for record, other in pairs:
            record.payload["tuple"]
        with manager as record:
            record.payload["with"]
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("pairs", "manager")}, app__ports__thing=RECORD_PORTS)

    assert sum("attribute 'payload' of a body" in f.reason for f in found) == 2


def test_calling_a_callable_attribute_that_can_hold_a_body_is_reported(tmp_path: Path) -> None:
    source = """
    from collections.abc import Awaitable, Callable
    from typing import Any

    class Loader:
        _load: Callable[[], Awaitable[dict[str, Any]]]

        async def go(self):
            payload = await self._load()
            return payload.get("phantom")
    """
    found = findings_of(tmp_path, source)

    assert any("call of '_load'" in f.reason for f in found)


def test_an_exemption_that_matches_several_lines_names_the_occurrence(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "def f(payload):\n    for k in payload.items():\n        pass\n    for k in payload.items():\n        pass\n"
    )
    findings = [
        adapter_reads.Finding("unresolved", "m.py:f", 2, ".items() iteration over a body"),
        adapter_reads.Finding("unresolved", "m.py:f", 4, ".items() iteration over a body"),
    ]
    vague = adapter_reads.Exemption("unresolved", "m.py:f", r"\.items", "for k in payload.items()", "dynamic")

    with pytest.raises(ValueError, match="name the occurrence"):
        adapter_reads.apply_exemptions(findings, [vague], tmp_path)
    second = vague._replace(occurrence=2)
    open_findings, stale = adapter_reads.apply_exemptions(findings, [second], tmp_path)

    assert [f.line for f in open_findings] == [2] and stale == []


def test_a_mapping_handed_to_str_format_is_not_a_leaf(tmp_path: Path) -> None:
    source = """
    def f(payload):
        return payload.get("template").format(payload)
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert any("format" in f.reason for f in found)


def test_every_unbound_read_is_a_finding_at_its_own_line(tmp_path: Path) -> None:
    source = """
    def norm(payload, fetch):
        a = payload.get("one")
        b = payload.get("two")
        c = fetch().get("three")
        return a, b, c
    """
    found = [f for f in findings_of(tmp_path, source) if f.kind == "unbound"]

    assert sorted((f.line, f.reason.split("'")[1]) for f in found) == [(3, "one"), (4, "two"), (5, "three")]


def test_an_exemption_is_bound_to_a_source_line_and_does_not_slide_when_a_finding_disappears(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "def f(payload):\n    for k in payload.items():\n        pass\n    for k in payload.items():\n        pass\n"
    )
    first = adapter_reads.Finding("unresolved", "m.py:f", 2, ".items() iteration over a body")
    second = adapter_reads.Finding("unresolved", "m.py:f", 4, ".items() iteration over a body")
    exemption = adapter_reads.Exemption(
        "unresolved", "m.py:f", r"\.items", "for k in payload.items()", "dynamic keys", occurrence=1
    )

    still_open, stale = adapter_reads.apply_exemptions([first, second], [exemption], tmp_path)
    assert [f.line for f in still_open] == [4] and stale == []
    slid, stale_now = adapter_reads.apply_exemptions([second], [exemption], tmp_path)
    assert [f.line for f in slid] == [4] and stale_now == [exemption]


def test_a_lost_value_appended_to_a_local_list_is_kept_and_read_as_unclassified(tmp_path: Path) -> None:
    source = """
    def f(payload):
        items = []
        items.append(mystery(payload))
        return items[0].get("phantom")
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)})

    assert any(f.kind == "unclassified" and "'phantom'" in f.reason for f in found)


def test_a_local_list_declared_as_a_list_of_records_is_not_collected_into(tmp_path: Path) -> None:
    source = """
    from .app.ports.thing import ThingRecord

    def f(payload):
        records: list[ThingRecord] = []
        records.append(payload.get("whole"))
    """
    found = findings_of(tmp_path, source, terminals={"m.py:f": ("payload",)}, app__ports__thing=RECORD_PORTS)

    assert any(f.reason == "a call of .append() with a body" for f in found)


# --- the sources table --------------------------------------------------------------------------------------------


PACKAGE = Path(__file__).resolve().parents[1] / "src" / "openproject_ce_mcp"


def test_every_member_of_the_source_tree_that_holds_a_raw_dict_is_classified() -> None:
    for member in wire_sources.census(PACKAGE):
        wire_sources.classify(member)


def test_the_transport_methods_are_the_wire_sources_and_request_raw_is_not() -> None:
    members = wire_sources.wire_members(PACKAGE)

    assert {("Transport", name) for name in wire_sources.TRANSPORT_METHODS} <= members
    assert ("Transport", "request_raw") not in members
    assert ("FormResult", "payload") in members and ("WorkPackageRecord", "payload") in members
    assert ("WorkPackageApi", "to_record.payload") in members
    assert ("WorkPackageApi", "commit_create.payload") not in members
    assert ("_WriteOutcome", "payload") not in members and ("WorkPackageWriteResult", "payload") not in members


def test_a_new_port_method_with_a_raw_return_type_fails_the_completeness_rule(tmp_path: Path) -> None:
    (tmp_path / "app" / "ports").mkdir(parents=True)
    (tmp_path / "app" / "ports" / "other.py").write_text(
        "from typing import Any, Protocol\n\nclass NewApi(Protocol):\n    def fetch(self) -> dict[str, Any]: ...\n"
    )
    members = wire_sources.census(tmp_path)

    assert [(m.kind, m.name) for m in members] == [("method", "fetch")]
    assert wire_sources.classify(members[0])[0] == wire_sources.WIRE


def test_the_command_line_reports_counts_and_lists_findings_on_request(tmp_path: Path, capsys) -> None:
    package = plant(tmp_path, m="def orphan(payload):\n    return payload.get('name')\n")

    assert adapter_reads.main(["--src", str(package), "--findings"]) == 0
    out = capsys.readouterr().out

    assert "findings: unbound 1" in out and "m.py:orphan" in out


def test_a_substring_test_on_a_string_value_is_no_read_and_a_key_test_on_a_dict_is(tmp_path: Path) -> None:
    source = """
    def f(payload):
        links = payload.get("_links", {})
        href = links.get("resource", {}).get("href")
        return "work_packages/" in href, "update" in links, "title" in links.get("project", {})
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert {(tuple(r.path), r.key) for r in reads if r.how == "in"} == {
        (("_links",), "update"),
        (("_links", "project"), "title"),
    }


def test_a_slice_of_a_list_is_still_the_list_and_an_index_is_an_element(tmp_path: Path) -> None:
    source = """
    def f(payload):
        entries = payload.get("details", [])
        first = entries[0]
        return [item.get("raw") for item in entries[:5]], first.get("raw")
    """
    reads = reads_of(tmp_path, source, terminals={"m.py:f": ("payload",)})["m.py:f"]

    assert {tuple(r.path) for r in reads if r.key == "raw"} == {("details", "*")}


# --- reads against a snapshot -------------------------------------------------------------------------------------

SNAPSHOT = {
    "pinned": {"16.0": "a", "16.1": "b", "17.0": "c"},
    "link_object_members": ["href", "title"],
    "paths": {
        "r.rb": {
            "versions": "16.0-17.0",
            "fields": {
                "property|id": {"versions": "16.0-17.0"},
                "property|newer": {"versions": "17.0"},
                "property|gated": {"versions": "16.0-17.0", "enterprise": True},
                "link|project": {"versions": "16.0-17.0"},
                "link|assignee": {"versions": "16.0-17.0"},
                "link-member:assignee|*": {"versions": "16.0-17.0"},
                "link|self": {"versions": "16.0-17.0"},
                "link-member:self|href": {"versions": "16.0-17.0"},
                "link|parent": {"versions": "16.0-17.0"},
                "link-member:parent|displayId": {"versions": "17.0"},
                "property|description": {"versions": "16.0-17.0"},
                "value-member:description|raw": {"versions": "16.0-17.0"},
                "embedded|details": {"versions": "16.0-17.0"},
            },
        },
        "d.rb": {"versions": "16.0-17.0", "fields": {"property|value": {"versions": "16.0-17.0"}}},
    },
}


def verdict(path: tuple[str, ...], key: str, row: adapter_reads.Row | None = None) -> str:
    read = adapter_reads.Read("ctx", 1, "p:payload", path, key, "get")
    return adapter_reads.check(read, row or adapter_reads.Row(("r.rb",)), SNAPSHOT).status


def test_a_read_is_ok_missing_or_partial_against_the_snapshot_and_a_conditional_entry_makes_partial_ok() -> None:
    assert verdict((), "id") == "ok"
    assert verdict((), "nope") == "missing"
    assert verdict((), "newer") == "partial"
    conditional = adapter_reads.Conditional(("16.0", "16.1"), "since 17.0")
    assert verdict((), "newer", adapter_reads.Row(("r.rb",), conditional={"property|newer": conditional})) == "ok"
    too_narrow = adapter_reads.Conditional(("16.0",), "since 16.1")
    assert verdict((), "newer", adapter_reads.Row(("r.rb",), conditional={"property|newer": too_narrow})) == "partial"
    assert verdict((), "nope", adapter_reads.Row(("r.rb",), waivers={"property|nope": "a reason"})) == "waived"


def test_link_members_default_to_href_and_title_and_an_open_link_needs_a_waiver() -> None:
    assert verdict(("_links", "project"), "href") == "ok"
    assert verdict(("_links", "project"), "title") == "ok"
    assert verdict(("_links", "project"), "method") == "missing"
    assert verdict(("_links", "assignee"), "title") == "open"
    assert verdict(("_links", "parent"), "displayId") == "partial"


def test_value_members_embedded_resources_and_structure_are_resolved() -> None:
    assert verdict(("description",), "raw") == "ok" and verdict(("description",), "nope") == "missing"
    assert verdict(("description", "*"), "raw") == "opaque"
    assert verdict((), "_links") == "ok" and verdict((), "_embedded") == "ok"
    assert verdict(("_embedded",), "details") == "ok"
    row = adapter_reads.Row(("r.rb",), embedded={"details": ("d.rb",)})
    assert verdict(("_embedded", "details", "*"), "value", row) == "ok"
    assert verdict(("_embedded", "details", "*"), "value") == "opaque"


def test_the_union_of_the_representers_of_a_row_answers_a_read() -> None:
    assert verdict((), "value", adapter_reads.Row(("r.rb", "d.rb"))) == "ok"


def test_a_field_rendered_only_for_an_enterprise_token_is_gated_and_a_waiver_still_wins() -> None:
    assert verdict((), "gated") == "gated"
    assert verdict((), "gated", adapter_reads.Row(("r.rb",), waivers={"property|gated": "Enterprise only"})) == "waived"


def test_a_membership_test_that_may_be_a_substring_test_is_ambiguous_not_missing() -> None:
    ambiguous = adapter_reads.Read("ctx", 1, "p:payload", ("description",), "nope", "in?")
    certain = adapter_reads.Read("ctx", 1, "p:payload", ("description",), "nope", "in")
    row = adapter_reads.Row(("r.rb",))

    assert adapter_reads.check(ambiguous, row, SNAPSHOT).status == "ambiguous"
    assert adapter_reads.check(certain, row, SNAPSHOT).status == "missing"


def test_the_macro_defaults_of_a_link_do_not_apply_where_the_source_lists_its_members_by_hand() -> None:
    assert verdict(("_links", "self"), "href") == "ok"
    assert verdict(("_links", "self"), "title") == "missing"
    assert verdict(("_links", "project"), "title") == "ok"


def test_a_waiver_or_conditional_entry_that_no_read_needs_is_stale() -> None:
    reads = [
        adapter_reads.Read("ctx", 1, "p:payload", (), "id", "get"),
        adapter_reads.Read("ctx", 1, "p:payload", (), "newer", "get"),
        adapter_reads.Read("ctx", 1, "p:payload", (), "nope", "get"),
    ]
    fine = adapter_reads.Row(
        ("r.rb",),
        waivers={"property|nope": "a reason"},
        conditional={"property|newer": adapter_reads.Conditional(("16.0", "16.1"), "since 17.0")},
    )
    stale = adapter_reads.Row(
        ("r.rb",),
        waivers={"property|nope": "a reason", "property|id": "snapshot confirms it", "property|gone": "no read"},
        conditional={
            "property|newer": adapter_reads.Conditional(("16.0",), "wrong versions"),
            "property|id": adapter_reads.Conditional(("16.0",), "present everywhere"),
        },
    )

    assert adapter_reads.stale_entries(reads, fine, SNAPSHOT) == []
    assert adapter_reads.stale_entries(reads, stale, SNAPSHOT) == [
        "waiver property|id",
        "waiver property|gone",
        "conditional property|newer",
        "conditional property|id",
    ]


def test_a_field_is_gated_only_when_every_representer_that_renders_it_is_enterprise_only() -> None:
    snapshot = {
        "pinned": {"16.0": "a"},
        "paths": {
            "a.rb": {"versions": "16.0", "fields": {"property|x": {"versions": "16.0", "enterprise": True}}},
            "b.rb": {"versions": "16.0", "fields": {"property|x": {"versions": "16.0"}}},
        },
    }
    read = adapter_reads.Read("ctx", 1, "p:payload", (), "x", "get")

    assert adapter_reads.check(read, adapter_reads.Row(("a.rb",)), snapshot).status == "gated"
    assert adapter_reads.check(read, adapter_reads.Row(("a.rb", "b.rb")), snapshot).status == "ok"


def test_an_exemption_covers_one_finding_on_one_line_and_a_stale_one_is_reported(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "def f(payload):\n    a = payload.items()\n    b = 1\n    c = 2\n    d = 3\n    e = 4\n    f = 5\n"
        "    g = 6\n    h = payload.items()\n"
    )
    findings = [
        adapter_reads.Finding("unresolved", "m.py:f", 2, ".items() iteration over a body"),
        adapter_reads.Finding("unresolved", "m.py:f", 9, ".items() iteration over a body"),
        adapter_reads.Finding("unresolved", "m.py:g", 4, ".items() iteration over a body"),
    ]
    exemptions = [
        adapter_reads.Exemption("unresolved", "m.py:f", r"\.items\(\)", "a = payload.items()", "dynamic keys"),
        adapter_reads.Exemption("unresolved", "m.py:h", r"\.items\(\)", "payload", "gone"),
    ]

    open_findings, stale = adapter_reads.apply_exemptions(findings, exemptions, tmp_path)

    assert [(f.context, f.line) for f in open_findings] == [("m.py:f", 9), ("m.py:g", 4)]
    assert [e.context for e in stale] == ["m.py:h"]


def test_a_waiver_for_a_property_does_not_cover_the_same_name_inside_an_embedded_resource() -> None:
    row = adapter_reads.Row(("r.rb",), embedded={"details": ("d.rb",)}, waivers={"property|value": "top level only"})
    top = adapter_reads.Read("ctx", 1, "p:payload", (), "value", "get")
    nested = adapter_reads.Read("ctx", 1, "p:payload", ("_embedded", "details", "*"), "value", "get")

    assert adapter_reads.check(top, row, SNAPSHOT).status == "waived"
    assert adapter_reads.check(nested, row, SNAPSHOT).status == "ok"
    scoped = adapter_reads.Row(("r.rb",), embedded={"details": ("d.rb",)}, waivers={"details:property|value": "x"})
    assert adapter_reads.check(nested, scoped, SNAPSHOT).status == "waived"


def test_a_key_only_an_enterprise_representer_supplies_in_one_version_is_missing_there() -> None:
    snapshot = {
        "pinned": {"16.0": "a", "17.0": "b"},
        "paths": {
            "a.rb": {"versions": "16.0", "fields": {"property|x": {"versions": "16.0"}}},
            "b.rb": {"versions": "17.0", "fields": {"property|x": {"versions": "17.0", "enterprise": True}}},
        },
    }
    read = adapter_reads.Read("ctx", 1, "p:payload", (), "x", "get")
    outcome = adapter_reads.check(read, adapter_reads.Row(("a.rb", "b.rb")), snapshot)

    assert (outcome.status, outcome.versions) == ("partial", "17.0")
