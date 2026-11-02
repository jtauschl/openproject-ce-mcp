"""The work package a write was pointed at, fetched, checked and named once for all writes that take a reference.

A caller-typed work package reference can mean two tickets (the bare integer is the internal id, `PROJ-436`
another ticket). This is the only place that applies `expect_display_id` and its siblings, so no write can
differ: `write_target` fetches the record itself (`update`, `delete`, `add_comment`),
`resolved_target` takes a record the shared resolver already fetched and gated, and `check_target` is the
verdict both end in, called directly by a service that keeps its own fetch and gate.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypeVar

from ...config import Settings
from ...models import ResolvedWorkPackage
from ..errors import InvalidInputError, NotFoundError, OpenProjectServerError
from ..policies import work_package_target_policy as policy
from ..policies.scope import ensure_project_write_link_allowed
from ..ports.work_package_ref import ResolvedRecord, WorkPackageRecordResolver, work_package_ref
from ._work_package_presentation import present_target


class _HasPayload(Protocol):
    @property
    def payload(self) -> Mapping[str, Any]: ...


RecordT = TypeVar("RecordT", bound=_HasPayload)


async def check_target(
    reference: str,
    *,
    payload: Mapping[str, Any],
    resolve_expected: Callable[[str], Awaitable[ResolvedRecord]],
    settings: Settings,
    expect_display_id: str | None,
    parameter: str = policy.DEFAULT_PARAMETER,
) -> ResolvedWorkPackage:
    """Name the work package `payload` and apply the display id guard to `reference`.

    `payload` was fetched once and has passed the write gate; `reference` is canonical (`work_package_ref`)
    and `expect_display_id` was checked with `policy.ensure_expectation_usable`. A second request happens
    only to resolve an expectation that differs from the record's display id. Raises before any write
    request: a refusal of the guard is an `InvalidInputError`, a lookup failure keeps its own type.
    """
    target = present_target(payload, settings=settings)
    display_id = payload.get("displayId")
    outcome = policy.decide(
        reference=reference, record_display_id=display_id, expect_display_id=expect_display_id, settings=settings
    )
    if outcome is policy.GuardOutcome.PASS:
        return target
    work_package_id = int(payload["id"])
    project_link = payload.get("_links", {}).get("project")
    ticket = policy.named_ticket(
        display_id=display_id,
        project=project_link.get("title") if isinstance(project_link, dict) else None,
        work_package_id=work_package_id,
        settings=settings,
    )
    if outcome is policy.GuardOutcome.NO_SEMANTIC_DISPLAY_ID:
        raise InvalidInputError(policy.no_semantic_display_id_message(work_package_id, parameter=parameter))
    if outcome is policy.GuardOutcome.EXPECTATION_REQUIRED:
        raise InvalidInputError(
            policy.expectation_required_message(
                reference=reference, ticket=ticket, display_id=display_id, parameter=parameter
            )
        )
    try:
        expected_id = (await resolve_expected(outcome.expected)).id
    except NotFoundError as exc:
        raise InvalidInputError(
            policy.mismatch_message(
                expected=outcome.expected, reference=reference, ticket=ticket, detail=str(exc), parameter=parameter
            )
        ) from exc
    if expected_id != work_package_id:
        raise InvalidInputError(
            policy.mismatch_message(expected=outcome.expected, reference=reference, ticket=ticket, parameter=parameter)
        )
    return target


async def write_target(
    reference: str,
    *,
    fetch: Callable[[str], Awaitable[RecordT]],
    resolve_expected: Callable[[str], Awaitable[ResolvedRecord]],
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
    expect_display_id: str | None,
    parameter: str = policy.DEFAULT_PARAMETER,
) -> tuple[RecordT, ResolvedWorkPackage]:
    """Fetch the record `reference` names, apply the write scope and the display id guard, and name it.

    `fetch` carries the caller's own fetch arguments. `expect_display_id` arrives trimmed (the tool boundary does
    that) and is checked for shape here. Raises before any write request: a refusal of the
    guard is an `InvalidInputError`, a scope denial and a lookup failure keep their own type.
    """
    policy.ensure_expectation_usable(expect_display_id, settings=settings, parameter=parameter)
    record = await fetch(reference)
    project_link = record.payload.get("_links", {}).get("project")
    if not isinstance(project_link, dict) or project_link.get("href") is None:
        # A server-data anomaly, not a caller mistake: classified before the scope gate, which
        # would deny a missing link as a scope violation.
        raise OpenProjectServerError("OpenProject work package is missing a project link.")
    ensure_project_write_link_allowed(
        project_link, settings=settings, project_id_to_identifier=project_id_to_identifier
    )
    target = await check_target(
        reference,
        payload=record.payload,
        resolve_expected=resolve_expected,
        settings=settings,
        expect_display_id=expect_display_id,
        parameter=parameter,
    )
    return record, target


async def resolved_target(
    reference: int | str,
    *,
    resolve: WorkPackageRecordResolver,
    settings: Settings,
    expect_display_id: str | None,
    parameter: str = policy.DEFAULT_PARAMETER,
) -> tuple[ResolvedRecord, ResolvedWorkPackage]:
    """Resolve `reference` for a write through the shared resolver (one fetch, write gate inside) and apply
    the display id guard. The expectation, when it differs from the record's display id, resolves through the
    same resolver with the same write gate."""
    policy.ensure_expectation_usable(expect_display_id, settings=settings, parameter=parameter)
    canonical = work_package_ref(reference)
    record = await resolve(reference, write=True)
    target = await check_target(
        canonical,
        payload=record.payload,
        resolve_expected=lambda expected: resolve(expected, write=True),
        settings=settings,
        expect_display_id=expect_display_id,
        parameter=parameter,
    )
    return record, target
