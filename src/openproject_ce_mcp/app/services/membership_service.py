"""Application Service for the Memberships domain (ADR 0001).

Depends on the MembershipApi Protocol, never HttpxMembershipApi concretely
(enforced by the architecture-boundary test). No dedicated
MembershipResolver: unlike Versions (name -> id) or Projects
(identifier/name -> id), a `membership_id` is always a numeric value already
validated by tools.py -- there is no semantic-reference resolution for this
domain to warrant a Resolver in the ADR sense.

`_WriteOutcome`/`_finalize_write` are shared via `app/services/_write_outcome.py`
(unified once a 3rd domain needed the identical state machine).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ...config import Settings
from ...models import MembershipListResult, MembershipSummary, MembershipWriteResult, RoleListResult
from ..errors import InvalidInputError
from ..pagination import paginate_server
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.membership_api import MembershipApi
from ..ports.principal_ref import PrincipalRefResolver
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ._write_outcome import _finalize_write, _WriteOutcome


class MembershipService:
    def __init__(
        self,
        *,
        api: MembershipApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
        resolve_principal_ref: PrincipalRefResolver,
        list_roles: Callable[[], Awaitable[RoleListResult]],
        api_prefix: str,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref
        self._resolve_principal_ref = resolve_principal_ref
        self._list_roles = list_roles
        self._api_prefix = api_prefix

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("membership", value, settings=self._settings)

    def _api_href(self, relative_path: str) -> str:
        return f"/{self._api_prefix.lstrip('/')}{relative_path.lstrip('/')}"

    async def list_for_project(
        self,
        project_ref: str,
        *,
        offset: int = 1,
        limit: int | None = None,
        context: ProjectResolutionContext | None = None,
    ) -> MembershipListResult:
        access.ensure_read_enabled("membership", settings=self._settings)
        resolution_context = context or ProjectResolutionContext(self._resolve_project_ref)
        project_payload = await resolution_context.resolve(project_ref, write=False)
        effective_limit = min(
            limit or self._settings.default_page_size, self._settings.max_page_size, self._settings.max_results
        )
        href = project_payload.get("_links", {}).get("memberships", {}).get("href")
        if not href:
            return MembershipListResult(
                offset=offset, limit=effective_limit, total=0, count=0, next_offset=None, truncated=False, results=[]
            )
        page = await self._api.list_for_project(href, offset=offset, page_size=effective_limit)
        stamped = [self._stamp(record.summary) for record in page.records]
        total = page.server_total if page.server_total is not None else len(stamped)
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=total)
        return MembershipListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(stamped),
            next_offset=next_offset,
            truncated=truncated,
            results=stamped,
        )

    async def get(self, membership_id: int) -> MembershipSummary:
        access.ensure_read_enabled("membership", settings=self._settings)
        record = await self._api.get(membership_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.summary)

    async def create(
        self,
        *,
        project: str,
        principal: str,
        roles: list[str],
        notification_message: str | None = None,
        confirm: bool = False,
    ) -> MembershipWriteResult:
        project_payload = await self._resolve_project_ref(project, write=True)
        hidden_fields.ensure_field_writable("membership", "project_name", settings=self._settings)
        hidden_fields.ensure_field_writable("membership", "principal_name", settings=self._settings)
        hidden_fields.ensure_field_writable("membership", "role_names", settings=self._settings)
        project_id = str(project_payload["id"])
        principal_id = await self._resolve_principal_ref(principal)
        role_hrefs = await self._resolve_role_hrefs(roles)
        payload: dict[str, Any] = {
            "_links": {
                "project": {"href": self._api_href(f"projects/{project_id}")},
                "principal": {"href": self._api_href(f"users/{principal_id}")},
                "roles": [{"href": href} for href in role_hrefs],
            }
        }
        if notification_message is not None:
            payload["_meta"] = {"notificationMessage": {"format": "markdown", "raw": notification_message}}
        form = await self._api.create_form(payload)
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"membership_id": None, "project": project_payload.get("name")},
            ensure_write_enabled=lambda: access.ensure_write_enabled("membership", settings=self._settings),
            commit=self._api.commit_create,
            committed_identity=lambda summary: {"membership_id": summary.id, "project": summary.project_name},
            rejected_message="OpenProject rejected the proposed membership changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the membership. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Membership created successfully.",
        )
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        membership_id: int,
        roles: list[str],
        notification_message: str | None = None,
        confirm: bool = False,
    ) -> MembershipWriteResult:
        current = await self._api.get(membership_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        hidden_fields.ensure_field_writable("membership", "role_names", settings=self._settings)
        role_hrefs = await self._resolve_role_hrefs(roles)
        payload: dict[str, Any] = {"_links": {"roles": [{"href": href} for href in role_hrefs]}}
        if notification_message is not None:
            payload["_meta"] = {"notificationMessage": {"format": "markdown", "raw": notification_message}}
        form = await self._api.update_form(membership_id, payload)
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"membership_id": membership_id, "project": current.summary.project_name},
            ensure_write_enabled=lambda: access.ensure_write_enabled("membership", settings=self._settings),
            commit=lambda p: self._api.commit_update(membership_id, p),
            committed_identity=lambda summary: {"membership_id": summary.id, "project": summary.project_name},
            rejected_message="OpenProject rejected the proposed membership changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the membership change. Ask for confirmation, then call again with confirm=true to write it.",
            success_message="Membership updated successfully.",
        )
        return self._to_write_result("update", outcome)

    async def delete(self, *, membership_id: int, confirm: bool = False) -> MembershipWriteResult:
        current = await self._api.get(membership_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        membership = self._stamp(current.summary)
        payload = {"id": membership.id, "principal": membership.principal_name, "roles": membership.role_names}

        if not confirm:
            return MembershipWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the membership. Ask for confirmation, then call again with confirm=true to delete it.",
                membership_id=membership.id,
                project=membership.project_name,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("membership", settings=self._settings)
        await self._api.delete(membership_id)
        return MembershipWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Membership deleted successfully.",
            membership_id=membership.id,
            project=membership.project_name,
            payload=payload,
            validation_errors={},
            result=membership,
        )

    async def _resolve_role_hrefs(self, roles: list[str]) -> list[str]:
        # Verbatim port of client.py's _resolve_role_hrefs. Kept as a private
        # Service method (not a resolver) since it operates purely on the
        # injected list_roles() result, with no ID resolution against
        # MembershipApi itself.
        available_roles = await self._list_roles()
        hrefs: list[str] = []
        for role_ref in roles:
            normalized = role_ref.strip()
            if not normalized:
                continue
            if normalized.isdigit():
                hrefs.append(self._api_href(f"roles/{normalized}"))
                continue
            matches = [
                role for role in available_roles.results if (role.name or "").casefold() == normalized.casefold()
            ]
            if not matches:
                raise InvalidInputError(f"OpenProject role '{role_ref}' was not found.")
            if len(matches) > 1:
                raise InvalidInputError(f"OpenProject role '{role_ref}' is ambiguous. Pass a numeric role id.")
            hrefs.append(self._api_href(f"roles/{matches[0].id}"))
        if not hrefs:
            raise InvalidInputError("At least one role is required.")
        return hrefs

    def _to_write_result(self, action: str, outcome: _WriteOutcome[MembershipSummary]) -> MembershipWriteResult:
        return MembershipWriteResult(
            action=action,
            confirmed=outcome.confirmed,
            requires_confirmation=outcome.requires_confirmation,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=self._stamp(outcome.detail) if outcome.detail else None,
            **outcome.identity,
        )
