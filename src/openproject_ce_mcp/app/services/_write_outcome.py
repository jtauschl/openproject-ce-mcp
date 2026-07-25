"""Shared preview/confirm write state machine for Application Services (ADR 0001).

Extracted from three byte-identical per-Service copies (Versions, Projects,
Memberships) once a third domain needed it -- this project's own standing
"unify at the 3rd identical instance" convention (already applied once
before, to `document_policy.py`/`news_policy.py`/`version_policy.py`).

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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

_DetailT = TypeVar("_DetailT")


@dataclass(frozen=True)
class _WriteOutcome(Generic[_DetailT]):
    ready: bool
    confirmed: bool
    requires_confirmation: bool
    message: str
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    detail: _DetailT | None
    identity: dict[str, Any]


async def _finalize_write(
    *,
    confirm: bool,
    payload: dict[str, Any],
    validation_errors: dict[str, str],
    identity: dict[str, Any],
    ensure_write_enabled: Any,
    commit: Any,
    committed_identity: Any,
    rejected_message: str,
    preview_message: str,
    success_message: str,
) -> _WriteOutcome[Any]:
    """Rejected/preview/committed state machine, shared by every Service that
    needs it (Versions, Projects, Memberships)."""
    if validation_errors:
        return _WriteOutcome(
            ready=False,
            confirmed=False,
            requires_confirmation=not confirm,
            message=rejected_message,
            payload=payload,
            validation_errors=validation_errors,
            detail=None,
            identity=identity,
        )
    if not confirm:
        return _WriteOutcome(
            ready=True,
            confirmed=False,
            requires_confirmation=True,
            message=preview_message,
            payload=payload,
            validation_errors={},
            detail=None,
            identity=identity,
        )
    ensure_write_enabled()
    detail = await commit(payload)
    return _WriteOutcome(
        ready=True,
        confirmed=True,
        requires_confirmation=False,
        message=success_message,
        payload=payload,
        validation_errors={},
        detail=detail,
        identity=committed_identity(detail),
    )
