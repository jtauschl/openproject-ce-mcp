"""Shared preview/confirm write state machine for Application Services.

Shared by Versions, Projects, and Memberships -- this project's own standing
"unify at the 3rd identical instance" convention (also applied to
`document_policy.py`/`news_policy.py`/`version_policy.py`).

`_finalize_write` performs no I/O itself: `commit` is a port-bound callable
supplied by the calling Service, since an Application Service must depend
only on a port's Protocol (never call transport directly). Only used by
domains with 2+ write actions sharing the same preview/commit/reject shape;
a domain with exactly one write method (e.g. Documents' update-only) stays a
single flat method instead -- a shared state machine for one call site would
be pure indirection, not reuse.

Both exported names are underscore-prefixed (not just the module) -- the
architecture-boundary test requires every public class under app/services/
to be named `*Service`/`*Resolver`; this module holds neither, so its
exports stay private the same way every per-Service copy it replaces did.

`gate_before_preview` (default False): three domains -- Group (create/update/
delete), Storage (create/update/delete), and User (delete only) -- have no
prior GET to authorize an unauthorized preview request against, so they check
`ensure_write_enabled` unconditionally, even for confirm=False, rather than
only inside the confirmed branch every other domain uses. This is a real,
audited, minority-but-recurring shape, not a one-off bug: making
it an explicit parameter here keeps a single orchestration point for every
domain instead of forcing those three to hand-roll their own copy or forcing
every other domain to pay for a check it doesn't want. The gate still runs
after the validation_errors check would normally short-circuit -- these three
domains have no validation_errors/form concept at all (always called with
`validation_errors={}`), so ordering relative to that branch is moot for them
in practice.

`preview_detail` (default None): used by the domains that need to show the
about-to-be-affected record in a preview response -- currently Attachment,
News, Storage, TimeEntry, and WorkPackage (verified against actual call
sites, not assumed uniform: Version/Board/Grid/Membership/Meeting/Project's
delete previews return `result=None` instead, identical to their
pre-write-orchestration-unification behavior). Where used, the record is
fetched BEFORE the confirm branch (needed for scope/permission checks on the
target, independent of write-orchestration), then surfaced as `result` on
the preview response even though nothing was committed yet. This is
genuinely different from `commit`'s return value (which only exists on the
confirmed branch) -- passing the pre-fetched record through explicitly,
rather than threading it through `commit`, keeps `commit` a pure "do the
mutation" callable that's never invoked on a preview.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from ...models import WriteResultState
from ..form_result import ValidationFailure
from ..link_titles import without_foreign_capable_titles

_DetailT = TypeVar("_DetailT")


@dataclass(frozen=True)
class _WriteOutcome(Generic[_DetailT]):
    ready: bool
    state: WriteResultState
    message: str
    payload: dict[str, Any]
    validation_errors: dict[str, ValidationFailure]
    detail: _DetailT | None
    identity: dict[str, Any]


async def _finalize_write(
    *,
    confirm: bool,
    payload: dict[str, Any],
    validation_errors: dict[str, ValidationFailure],
    identity: dict[str, Any],
    ensure_write_enabled: Any,
    commit: Any,
    committed_identity: Any,
    rejected_message: str,
    preview_message: str,
    success_message: str,
    gate_before_preview: bool = False,
    preview_detail: Any = None,
) -> _WriteOutcome[Any]:
    """Rejected/preview/committed state machine, shared by every Service that
    needs it (Versions, Projects, Memberships, Group, Storage, User).

    See the module docstring for `gate_before_preview`/`preview_detail`."""
    if gate_before_preview:
        ensure_write_enabled()
    shown = without_foreign_capable_titles(payload)
    if validation_errors:
        return _WriteOutcome(
            ready=False,
            state="invalid" if confirm else "rejected",
            message=rejected_message,
            payload=shown,
            validation_errors=validation_errors,
            detail=None,
            identity=identity,
        )
    if not confirm:
        return _WriteOutcome(
            ready=True,
            state="preview",
            message=preview_message,
            payload=shown,
            validation_errors={},
            detail=preview_detail,
            identity=identity,
        )
    if not gate_before_preview:
        ensure_write_enabled()
    detail = await commit(payload)
    return _WriteOutcome(
        ready=True,
        state="confirmed",
        message=success_message,
        payload=shown,
        validation_errors={},
        detail=detail,
        identity=committed_identity(detail),
    )
