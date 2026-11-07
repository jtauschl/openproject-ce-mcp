"""The release a sort or group column first exists in, as one rule for every entity's columns.

A pure rule shared by the tool layer and `app/`, neither of which may import the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def release_key(release: str) -> tuple[int, ...]:
    return tuple(int(part) for part in release.split("."))


def floors_used(fields: Iterable[str | None], floors: Mapping[str, str]) -> list[tuple[str, str]]:
    """The (column, release) pairs the fields use, oldest release first."""
    used = {field for field in fields if field is not None and field in floors}
    return sorted(((field, floors[field]) for field in used), key=lambda pair: release_key(pair[1]))


def describe_floors(floors: Mapping[str, str]) -> str:
    return ", ".join(f"{field} {floor}+" for field, floor in sorted(floors.items(), key=lambda p: release_key(p[1])))
