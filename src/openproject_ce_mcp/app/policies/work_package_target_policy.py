"""When a write must name its work package by display id, and what a refusal says.

A bare integer is the internal id; `PROJ-436` is another ticket. Where the record carries a semantic
display id, a write that was given only a bare integer must also say which ticket it means
(`expect_display_id`, or the sibling parameter of a write that names a second work package: the caller's
parameter name is printed in every refusal). The decisions are pure; the lookup of an expectation that differs from
the record's display id stays with the service.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ...config import Settings
from ...work_package_reference import canonical_display_id, has_semantic_display_id, is_numeric_ref
from ..errors import InvalidInputError
from . import hidden_fields

_ENTITY = "work_package"
DEFAULT_PARAMETER = "expect_display_id"


class GuardOutcome(Enum):
    PASS = "pass"
    NO_SEMANTIC_DISPLAY_ID = "no_semantic_display_id"
    EXPECTATION_REQUIRED = "expectation_required"


@dataclass(frozen=True)
class Lookup:
    """The expectation differs from the record's display id: only the backend can say whether it names
    the same work package (a former project identifier still resolves)."""

    expected: str


Decision = GuardOutcome | Lookup


def ensure_expectation_usable(
    expect_display_id: str | None, *, settings: Settings, parameter: str = DEFAULT_PARAMETER
) -> None:
    """A numeric expectation would resolve to the record the bare number already names, so it names no
    ticket; a hidden `display_id` cannot be compared, a match would confirm the hidden value."""
    if expect_display_id is None:
        return
    if canonical_display_id(expect_display_id) != expect_display_id:
        raise InvalidInputError(f"{parameter} must be a display id like 'PROJ-51' (project identifier case-sensitive).")
    if hidden_fields.field_hidden(_ENTITY, "display_id", settings=settings):
        raise InvalidInputError(
            f"{parameter} cannot be used: the display_id field is hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS."
        )


def decide(
    *, reference: str, record_display_id: str | None, expect_display_id: str | None, settings: Settings
) -> Decision:
    """The reference is canonical (`work_package_ref`), the expectation trimmed and display-id shaped."""
    semantic = has_semantic_display_id(record_display_id)
    if expect_display_id is not None:
        if not semantic:
            return GuardOutcome.NO_SEMANTIC_DISPLAY_ID
        return GuardOutcome.PASS if expect_display_id == record_display_id else Lookup(expect_display_id)
    ambiguous = is_numeric_ref(reference) and semantic
    if ambiguous and not hidden_fields.field_hidden(_ENTITY, "display_id", settings=settings):
        return GuardOutcome.EXPECTATION_REQUIRED
    return GuardOutcome.PASS


def named_ticket(*, display_id: str | None, project: str | None, work_package_id: int, settings: Settings) -> str:
    """The ticket as a guard message may name it: only fields the settings do not hide, never the subject
    (user content). `PROJ-7 (Project A)`, or `work package 7` when nothing else may be named."""
    shown_id = None if hidden_fields.field_hidden(_ENTITY, "display_id", settings=settings) else display_id
    shown_project = None if hidden_fields.field_hidden(_ENTITY, "project", settings=settings) else project
    name = shown_id or f"work package {work_package_id}"
    return f"{name} ({shown_project})" if shown_project else name


def ensure_expectation_has_reference(
    expect_display_id: str | None, *, reference_given: bool, parameter: str, reference: str
) -> None:
    """An expectation with no work package to check would be dropped without a word."""
    if expect_display_id is not None and not reference_given:
        raise InvalidInputError(
            f"{parameter} was given but {reference} names no work package to check; "
            f"omit {parameter} or pass {reference}."
        )


def no_semantic_display_id_message(work_package_id: int, *, parameter: str = DEFAULT_PARAMETER) -> str:
    return (
        f"Work package {work_package_id} has no semantic display id (classic identifier mode or no identifier "
        f"allocated); omit {parameter}."
    )


def expectation_required_message(
    *, reference: str, ticket: str, display_id: str | None, parameter: str = DEFAULT_PARAMETER
) -> str:
    """`display_id` is shown here: the requirement does not apply while it is hidden."""
    return (
        f"{reference} is {ticket}. If you mean {display_id}, repeat with {parameter} {display_id!r}; "
        "if you mean another ticket, pass its display id as the reference."
    )


def mismatch_message(
    *, expected: str, reference: str, ticket: str, detail: str | None = None, parameter: str = DEFAULT_PARAMETER
) -> str:
    base = f"{parameter} {expected!r} does not name the work package that {reference} resolved to ({ticket})."
    return f"{base} {detail}" if detail else base
