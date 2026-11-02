"""A typed project reference in a project write keeps the record it resolved to, not only its id.

`resolve_id` returns the id and drops the record, so a write built on it cannot show which project the
reference named. This is the structural proxy for the guard; the behavioral guard is the shown-versus-written
parent assertion in `tests/unit/test_project_parent_target.py`.
"""

from __future__ import annotations

from _source_scan import SERVICES, calls_named, matching_nodes

_PLANTED = """
class Service:
    async def _build_write_payload(self, parent):
        return await self._resolver.resolve_id(parent, write=True)
"""


def _offenders() -> list[str]:
    found = matching_nodes(calls_named("resolve_id"), directories=(SERVICES,))
    return sorted(name for name in found if name == "project_service.py:_build_write_payload")


def test_the_project_write_payload_builder_does_not_reduce_a_reference_to_its_id() -> None:
    assert _offenders() == []


def test_the_check_sees_a_resolve_id_call_in_the_builder() -> None:
    found = matching_nodes(calls_named("resolve_id"), source=_PLANTED)

    assert list(found) == ["planted.py:_build_write_payload"]
