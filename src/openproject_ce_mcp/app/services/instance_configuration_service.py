"""Application Service for the Instance Configuration domain.

Depends on the InstanceConfigurationApi Protocol, never HttpxInstanceConfigurationApi
concretely (enforced by the architecture-boundary test). No Resolver, no
Policy module: self-scoped to the whole instance, no project link and no
allowlist concept at all -- same shape as Roles/Extended Metadata.

Gates on the `"project"` read scope, NOT an `"instance_configuration"`-named
scope -- a pre-existing quirk of client.py's original get_instance_configuration,
preserved exactly rather than "fixed" during migration.

Deliberately NOT reused by `HttpxAttachmentApi.get_max_attachment_size()`,
which independently makes its own raw `GET configuration` call for a single
field (`maximumAttachmentFileSize`) it needs to validate an upload against --
a pre-existing, documented narrow exception (see docs/architecture.md), not
something this migration should "clean up" by rewiring it onto this Service.
"""

from __future__ import annotations

from ...config import Settings
from ...models import InstanceConfiguration
from ..policies import access, hidden_fields
from ..ports.instance_configuration_api import InstanceConfigurationApi


class InstanceConfigurationService:
    def __init__(self, *, api: InstanceConfigurationApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    async def get_instance_configuration(self) -> InstanceConfiguration:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get_configuration()
        return hidden_fields.apply_hidden_fields("instance_configuration", record.summary, settings=self._settings)
