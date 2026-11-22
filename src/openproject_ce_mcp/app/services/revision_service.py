"""Application Service for the Revisions domain.

The work package is judged first through the resolver every read uses. A revision belongs to the project of its
repository, which need not be the work package's project, so each row is then judged by its own project link and
a row outside the read scope is dropped.

Read scope reuses "work_package".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from ...config import Settings
from ...models import RevisionListResult, RevisionSummary
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.revision_api import RevisionApi
from ..ports.work_package_ref import WorkPackageIdResolver
from ._error_masking import redacted_server_errors


@redacted_server_errors("revision")
class RevisionService:
    def __init__(
        self,
        *,
        api: RevisionApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp(self, value: RevisionSummary) -> RevisionSummary:
        # The adapter measures the message before masking exists; a hidden message must not leak its length.
        if hidden_fields.field_hidden("revision", "message", settings=self._settings):
            value = replace(value, message_truncated=False, message_length=None)
        return hidden_fields.apply_hidden_fields("revision", value, settings=self._settings)

    async def list_for_work_package(self, work_package_id: int | str) -> RevisionListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        records = await self._api.list_for_work_package(resolved_id, text_limit=self._settings.text_limit)
        results = [
            self._stamp(record.summary)
            for record in records
            if scope_policy.project_link_allowed(
                record.project_link,
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
        ]
        return RevisionListResult(count=len(results), results=results)
