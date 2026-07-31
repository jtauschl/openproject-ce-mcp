"""HTTP-backed ActivityApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `link_title`/`delimit_user_content` come from
`app/adapters/_text.py` -- verified against client.py's real
`normalize_activity` (client.py:3475-3515), which needs `link_title` (user)
and `delimit_user_content` (each details-array entry's `raw` text).

`_trim_text_with_meta`/`_extract_formattable_text_with_meta` stay LOCAL
(deliberately not `_text.py`-shared, per the documented per-adapter
exception -- see `httpx_time_entry_api.py`'s identical local copy for the
established precedent): client.py's original called the hide-aware
`_visible_formattable_text_with_meta` for `comment`, which is
`_field_hidden("activity", "comment")` gating PLUS the unconditional
extraction below. Both this adapter's `"activity"` entity string and the
Service's own `apply_hidden_fields("activity", ...)` stamp resolve to the
identical `field_hidden` predicate against the identical entity/field name
(`"activity"`/`"comment"`) -- the "double masking, same predicate" case the
runbook documents as harmless legacy redundancy, not a second independent
control (per its own step-1 "verify, don't assume" trap). The adapter
therefore extracts unconditionally; masking is applied once, in the Service.

`normalize_activity` returns `(summary, comment_truncated)` is NOT the
shape -- it takes `text_limit` directly (verbatim of the original's own
parameter), called by the Service only on the elements that survive
slicing, never on every element (see module docstring in `activity_api.py`
port for the eager-vs-lazy reasoning this avoids).
"""

from __future__ import annotations

from typing import Any

from ...models import ActivitySummary
from ..ports.activity_api import ActivityRecord
from ..transport.protocol import Transport
from ._text import delimit_user_content as _delimit_user_content
from ._text import link_title as _link_title

ACTIVITY_DETAILS_LIMIT = 20
FORMATTABLE_LIMIT = 1_200


def _normalize_text(value: Any, *, preserve_newlines: bool) -> str:
    """Verbatim port of client.py's module-level `_normalize_text`.

    Default (``preserve_newlines=False``): collapse all whitespace/newlines
    to single spaces. ``preserve_newlines=True`` (the only mode this adapter
    actually uses, for `comment`): keep paragraph/list structure -- CRLF->LF,
    collapse inline whitespace per line, strip trailing whitespace per line,
    strip leading/trailing blank lines, collapse any run of blank lines to a
    single blank line.
    """
    if not preserve_newlines:
        return " ".join(str(value).split())
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        stripped = " ".join(line.split())
        if stripped:
            blank_run = 0
            normalized.append(stripped)
        else:
            blank_run += 1
            if blank_run <= 1:
                normalized.append("")
    while normalized and normalized[0] == "":
        normalized.pop(0)
    while normalized and normalized[-1] == "":
        normalized.pop()
    return "\n".join(normalized)


def _trim_text_with_meta(
    value: Any, *, limit: int | None, preserve_newlines: bool = False
) -> tuple[str | None, bool, int | None]:
    if value is None:
        return None, False, None
    text = _normalize_text(value, preserve_newlines=preserve_newlines)
    if not text:
        return None, False, None
    full_length = len(text)
    if limit is None or full_length <= limit:
        return text, False, full_length
    return text[: limit - 1].rstrip() + "…", True, full_length


def _extract_formattable_text_with_meta(
    value: Any, *, limit: int | None = FORMATTABLE_LIMIT, preserve_newlines: bool = False
) -> tuple[str | None, bool, int | None]:
    raw = value.get("raw") or value.get("html") if isinstance(value, dict) else value
    return _trim_text_with_meta(raw, limit=limit, preserve_newlines=preserve_newlines)


def normalize_activity(payload: dict[str, Any], *, text_limit: int | None = None) -> ActivitySummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_activity, minus the
    _apply_hidden_fields call and the hide-aware gate -- masking is a
    Service-layer concern applied after this returns (see module docstring).
    """
    links = payload.get("_links", {})
    raw_comment, truncated, length = _extract_formattable_text_with_meta(
        payload.get("comment"), limit=text_limit, preserve_newlines=True
    )
    # `_visible_formattable_text_with_meta`'s original docstring: "The
    # returned text is always wrapped by _delimit_user_content" -- verbatim
    # here, since masking (the hide-aware gate that method also applied)
    # moved to the Service layer, but the delimiter wrap did not.
    comment = _delimit_user_content(raw_comment)

    # Details array with limit. OpenProject sends each entry as both a
    # plain-text "raw" and a markup "html" rendering of the SAME change
    # description — keep only "raw" (dropping the duplicate "html"/"format"
    # keys) and delimit it like every other free-text field here, since
    # it is equally untrusted user-authored content.
    details_raw = payload.get("details", [])
    details = None
    details_truncated = False
    if details_raw:
        details = [
            {"raw": _delimit_user_content(item.get("raw"))}
            for item in details_raw[:ACTIVITY_DETAILS_LIMIT]
            if isinstance(item, dict)
        ]
        details_truncated = len(details_raw) > ACTIVITY_DETAILS_LIMIT

    return ActivitySummary(
        id=int(payload["id"]),
        type=payload.get("_type"),
        version=payload.get("version"),
        user=_link_title(links.get("user")),
        comment=comment,
        created_at=payload.get("createdAt"),
        comment_truncated=truncated,
        comment_length=length,
        details=details,
        details_truncated=details_truncated,
    )


def _record(payload: dict[str, Any]) -> ActivityRecord:
    def to_summary(text_limit: int | None) -> ActivitySummary:
        return normalize_activity(payload, text_limit=text_limit)

    return ActivityRecord(to_summary=to_summary)


class HttpxActivityApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def list_for_work_package(self, work_package_id: int) -> list[ActivityRecord]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/activities")
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        return [_record(item) for item in elements]

    def to_record(self, payload: dict[str, Any]) -> ActivityRecord:
        return _record(payload)

    async def get_raw(self, activity_id: int) -> dict[str, Any]:
        return await self._transport.get_json(f"activities/{activity_id}")
