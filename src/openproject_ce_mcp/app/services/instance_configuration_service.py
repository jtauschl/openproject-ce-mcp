"""Application Service for the Instance Configuration domain.

Depends on the InstanceConfigurationApi Protocol, never HttpxInstanceConfigurationApi
concretely (enforced by the architecture-boundary test). No Resolver, no
Policy module: self-scoped to the whole instance, no project link and no
allowlist concept at all -- same shape as Roles/Extended Metadata.

Gates on the `"project"` read scope, NOT an `"instance_configuration"`-named
scope -- a deliberate quirk, kept as-is rather than "fixed".

Deliberately NOT reused by `HttpxAttachmentApi.get_max_attachment_size_bytes()`,
which independently makes its own raw `GET configuration` call for a single
field (`maximumAttachmentFileSize`) it needs to validate an upload against --
a documented narrow exception (see docs/architecture.md).

`cache` is a `SingletonCache` constructed once in `client.py` -- instance
configuration is global, non-per-user, essentially static at runtime, safe
to cache for the server process's lifetime (see `app/caches.py`).
"""

from __future__ import annotations

from ...config import Settings
from ...models import InstanceConfiguration
from ..caches import SingletonCache
from ..policies import access, hidden_fields
from ..ports.instance_configuration_api import InstanceConfigurationApi, InstanceConfigurationRecord


class InstanceConfigurationService:
    def __init__(
        self, *, api: InstanceConfigurationApi, settings: Settings, cache: SingletonCache[InstanceConfigurationRecord]
    ) -> None:
        self._api = api
        self._settings = settings
        self._cache = cache

    async def get_instance_configuration(self) -> InstanceConfiguration:
        access.ensure_read_enabled("project", settings=self._settings)
        if self._cache.value is None:
            self._cache.value = await self._api.get_configuration()
        return hidden_fields.apply_hidden_fields(
            "instance_configuration", self._cache.value.summary, settings=self._settings
        )
