"""A version, sprint or backlog bucket a work package result may name.

They are shared into projects other than the one that defines them, and the link a work package
carries names the resource without its defining project. A result names one only when it is in the
`VisibleReferences` the service decided on, so a reference the adapter does not recognize loses its
title instead of leaking it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..resource_href import ResourceLinks

ReferenceKind = Literal["version", "sprint", "backlog_bucket"]
_KIND_OF_NAMESPACE: dict[str, ReferenceKind] = {
    "versions": "version",
    "sprints": "sprint",
    "backlog_buckets": "backlog_bucket",
}


@dataclass(frozen=True)
class ScopedReference:
    kind: ReferenceKind
    id: int


def reference_of_link(link: Any, links: ResourceLinks) -> ScopedReference | None:
    """The version, sprint or backlog bucket a link names, or None for any other link."""
    parsed = links.parse(link)
    if parsed is None or parsed.namespace not in _KIND_OF_NAMESPACE:
        return None
    return ScopedReference(_KIND_OF_NAMESPACE[parsed.namespace], parsed.id)


class VisibleReferences:
    """The references a result may name. Built only by `_scoped_references`, which makes the
    decision; the adapters receive it and keep a title only if it contains the reference."""

    __slots__ = ("_visible",)

    def __init__(self, visible: frozenset[ScopedReference] | None) -> None:
        self._visible = visible

    @classmethod
    def everything(cls) -> VisibleReferences:
        return cls(None)

    @classmethod
    def only(cls, references: Iterable[ScopedReference]) -> VisibleReferences:
        return cls(frozenset(references))

    def contains(self, reference: ScopedReference) -> bool:
        return self._visible is None or reference in self._visible


class ScopedRecord(Protocol):
    """A record whose presentation needs a decision on its references: `references` maps the result field
    that shows a reference (`version`, `sprint`, `customField<N>`, ...) to the references it names, so a field
    a hide setting removes costs no lookup."""

    @property
    def references(self) -> Mapping[str, frozenset[ScopedReference]]: ...


class ScopedReferencesAllowedBulkCheck(Protocol):
    """Narrow seam onto `ScopedReferenceResolver.references_allowed`.

    Returns `bool | Exception` per reference, so the caller re-raises the first failure only for a
    reference it needs.
    """

    def __call__(self, references: Iterable[ScopedReference]) -> Awaitable[dict[ScopedReference, bool | Exception]]: ...
