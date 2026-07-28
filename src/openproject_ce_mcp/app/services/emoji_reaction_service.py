"""Application Service for the Emoji Reactions domain (ADR 0001, OPM-318
third consumer).

Depends on the `EmojiReactionApi` Protocol (never `HttpxEmojiReactionApi`
concretely -- enforced by the architecture-boundary test), on
`WorkPackageLookupApi` directly, and on `WorkPackageIdResolver`. Three
Protocol dependencies -- the same shape as File Links, for the same reason:

- `list_for_work_package()` uses `WorkPackageIdResolver(ref, write=False)`.
  client.py's original called `self.get_work_package(work_package_id)`
  purely as an existence+read-allowlist check, discarding the full
  `WorkPackageDetail` it returned -- `resolve_id` does the identical fetch +
  allowlist check without the wasted normalization/hierarchy-filtering work
  `get_work_package` also does, a strictly better fit than the flat code's
  own choice of helper.
- `toggle()` uses `WorkPackageLookupApi.get()` directly, NOT
  `WorkPackageIdResolver`/`WorkPackageProjectAllowedCheck` -- mirroring File
  Links' `delete()` reasoning exactly: the work-package id here is already a
  concrete int derived from the activity's own `_links.workPackage` link
  (not a caller-supplied reference to resolve), and the method must itself
  raise a specific, fail-closed error when that link is missing --
  `WorkPackageProjectAllowedCheck`'s bool return would need re-wrapping to
  raise again, adding indirection for no benefit over calling
  `scope_policy.ensure_project_write_link_allowed` directly (already how
  `FileLinkService.delete()` does the equivalent check).

No `to_detail`, no Policy module: neither method filters a list of records
against a per-record project-link predicate.

`toggle()` is a single flat method (not the shared `_write_outcome.py` state
machine, since this domain has exactly one write action) -- its preview
cannot predict the resulting add/remove state (OpenProject decides that
server-side), so the preview names the toggle's nature instead of a real
result, verbatim behavior of client.py's original.

Read/write scope reuses `"work_package"` (not a dedicated `"emoji_reaction"`
scope) -- verbatim behavior of client.py's `_ensure_read_enabled`/
`_ensure_write_enabled("work_package")` calls.
"""

from __future__ import annotations

from ...config import Settings
from ...models import EmojiReactionListResult, EmojiReactionSummary, EmojiReactionWriteResult
from ..errors import InvalidInputError, OpenProjectServerError
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..policies.scope import id_from_href
from ..ports.emoji_reaction_api import EmojiReactionApi
from ..ports.work_package_lookup_api import WorkPackageLookupApi
from ..ports.work_package_ref import WorkPackageIdResolver

#: Valid reactions per the OpenProject API spec, verbatim port of
#: client.py's EMOJI_REACTIONS tuple.
EMOJI_REACTIONS = (
    "thumbs_up",
    "thumbs_down",
    "grinning_face_with_smiling_eyes",
    "confused_face",
    "heart",
    "party_popper",
    "rocket",
    "eyes",
)


class EmojiReactionService:
    def __init__(
        self,
        *,
        api: EmojiReactionApi,
        work_package_lookup_api: WorkPackageLookupApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._work_package_lookup_api = work_package_lookup_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp(self, summary: EmojiReactionSummary) -> EmojiReactionSummary:
        return hidden_fields.apply_hidden_fields("emoji_reaction", summary, settings=self._settings)

    async def list_for_work_package(self, work_package_id: int | str) -> EmojiReactionListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        summaries = await self._api.list_for_work_package(resolved_id)
        results = [self._stamp(summary) for summary in summaries]
        return EmojiReactionListResult(count=len(results), results=results)

    async def toggle(self, activity_id: int, reaction: str, *, confirm: bool = False) -> EmojiReactionWriteResult:
        if reaction not in EMOJI_REACTIONS:
            raise InvalidInputError(f"reaction must be one of: {', '.join(EMOJI_REACTIONS)}.")
        # Enforce the project write allowlist against the activity's work
        # package. Fail closed: if the activity has no resolvable
        # workPackage link, refuse rather than patch an unchecked target.
        # This check always runs, even in preview mode -- it is an
        # authorization gate, not the mutation itself (verbatim behavior of
        # client.py's original).
        activity = await self._api.get_activity(activity_id)
        work_package_id = id_from_href(activity.get("_links", {}).get("workPackage", {}).get("href"))
        if not work_package_id:
            raise OpenProjectServerError(
                "OpenProject activity is missing a work package link; cannot verify project write access."
            )
        work_package_payload = await self._work_package_lookup_api.get(str(work_package_id))
        scope_policy.ensure_project_write_link_allowed(
            work_package_payload.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        if not confirm:
            # The resulting add/remove state is not predicted here --
            # OpenProject decides that server-side and doing so ourselves
            # would need an extra lookup. The preview names the toggle's
            # nature instead.
            return EmojiReactionWriteResult(
                action="toggle_reaction",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=(
                    f"Toggles the '{reaction}' reaction on activity {activity_id} — adds it if not "
                    "already present, removes it if present. Ask for confirmation, then call again "
                    "with confirm=true to apply it."
                ),
                activity_id=activity_id,
                reaction=reaction,
                result=None,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        summaries = await self._api.toggle(activity_id, reaction)
        results = [self._stamp(summary) for summary in summaries]
        return EmojiReactionWriteResult(
            action="toggle_reaction",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=f"Toggled '{reaction}' reaction on activity {activity_id}.",
            activity_id=activity_id,
            reaction=reaction,
            result=EmojiReactionListResult(count=len(results), results=results),
        )
