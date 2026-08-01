"""Instance Configuration Domain API port (ADR 0001).

Single global GET, no project link, no list/create/update/delete --
OpenProject exposes one read-only `configuration` resource for the whole
instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import InstanceConfiguration


@dataclass(frozen=True)
class InstanceConfigurationRecord:
    summary: InstanceConfiguration


class InstanceConfigurationApi(Protocol):
    """Narrow, Instance-Configuration-only Domain API port.
    InstanceConfigurationService depends on this Protocol, never on
    HttpxInstanceConfigurationApi concretely (enforced by the
    architecture-boundary test).
    """

    async def get_configuration(self) -> InstanceConfigurationRecord: ...
