"""The work package a write was pointed at, fetched, checked and named once for all single-target writes.

`update`, `delete` and `add_comment` take a caller-typed reference that can mean two tickets (the bare
integer is the internal id, `PROJ-436` another ticket). This is the only place that fetches the record,
checks the write scope and applies `expect_display_id`, so the three cannot differ.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from ...config import Settings
from ...models import ResolvedWorkPackage
from ..errors import InvalidInputError, NotFoundError, OpenProjectServerError
from ..policies import work_package_target_policy as policy
from ..policies.scope import ensure_project_write_link_allowed
from ..ports.work_package_api import WorkPackageRecord
from ..ports.work_package_ref import ResolvedRecord
from ._work_package_presentation import present_target


async def write_target(
    reference: str,
    *,
    fetch: Callable[[str], Awaitable[WorkPackageRecord]],
    resolve_expected: Callable[[str], Awaitable[ResolvedRecord]],
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
    expect_display_id: str | None,
) -> tuple[WorkPackageRecord, ResolvedWorkPackage]:
    """Fetch the record `reference` names, apply the write scope and the display id guard, and name it.

    `fetch` carries the caller's own fetch arguments. `expect_display_id` arrives trimmed (the tool boundary does
    that) and is checked for shape here. Raises before any write request: a refusal of the
    guard is an `InvalidInputError`, a scope denial and a lookup failure keep their own type.
    """
    policy.ensure_expectation_usable(expect_display_id, settings=settings)
    record = await fetch(reference)
    project_link = record.payload.get("_links", {}).get("project")
    if not isinstance(project_link, dict) or project_link.get("href") is None:
        # A server-data anomaly, not a caller mistake: classified before the scope gate, which
        # would deny a missing link as a scope violation.
        raise OpenProjectServerError("OpenProject work package is missing a project link.")
    ensure_project_write_link_allowed(
        project_link, settings=settings, project_id_to_identifier=project_id_to_identifier
    )
    target = present_target(record.payload, settings=settings)
    display_id = record.payload.get("displayId")
    outcome = policy.decide(
        reference=reference, record_display_id=display_id, expect_display_id=expect_display_id, settings=settings
    )
    if outcome is policy.GuardOutcome.PASS:
        return record, target
    work_package_id = int(record.payload["id"])
    ticket = policy.named_ticket(
        display_id=display_id,
        project=project_link.get("title"),
        work_package_id=work_package_id,
        settings=settings,
    )
    if outcome is policy.GuardOutcome.NO_SEMANTIC_DISPLAY_ID:
        raise InvalidInputError(policy.no_semantic_display_id_message(work_package_id))
    if outcome is policy.GuardOutcome.EXPECTATION_REQUIRED:
        raise InvalidInputError(
            policy.expectation_required_message(reference=reference, ticket=ticket, display_id=display_id)
        )
    try:
        expected_id = (await resolve_expected(outcome.expected)).id
    except NotFoundError as exc:
        raise InvalidInputError(
            policy.mismatch_message(expected=outcome.expected, reference=reference, ticket=ticket, detail=str(exc))
        ) from exc
    if expected_id != work_package_id:
        raise InvalidInputError(policy.mismatch_message(expected=outcome.expected, reference=reference, ticket=ticket))
    return record, target
