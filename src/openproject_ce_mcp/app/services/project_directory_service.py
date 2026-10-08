"""Which projects the configured allowlists cover, by numeric project id.

A project link in a HAL response carries only an href and a title, so an
identifier- or name-based allowlist can match a linked project only through
an id -> identifier map. The map has to know projects that came into being
after the server started (a copy, the web UI, another client), not just the
ones present at startup. The directory learns them from every JSON response
before a policy sees it (see transport.learning_transport) and looks up an
id only when no response or scan has shown it yet.

The policies read `positives` synchronously; it is updated in place and never
rebound, because every service and resolver holds the same object.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Iterator
from typing import Any, NamedTuple
from urllib.parse import urlparse

from ...config import Settings
from ...models import ProjectSummary
from ..errors import NotFoundError, OpenProjectError
from ..policies.scope import project_record_candidates, scope_allows_all, scope_matches_candidates
from ..ports.project_api import ProjectApi

LOGGER = logging.getLogger(__name__)

# Bounds both how long a project created elsewhere can stay missing from the
# readable set and how long an out-of-scope verdict outlives a change in
# OpenProject.
FRESHNESS_SECONDS = 300.0

# One response can link any number of unseen projects.
_CONCURRENT_LOOKUPS = 10

# CE project links render as /api/v3/projects/<id>, and on 17.x also as
# /api/v3/workspaces/<id>; programs and portfolios are Enterprise.
_PROJECT_PATH = re.compile(r"(?:projects|workspaces)/(\d+)")


class ProjectDirectoryService:
    def __init__(
        self,
        *,
        api: ProjectApi,
        settings: Settings,
        origin: str,
        api_prefix: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api = api
        self._settings = settings
        self._origin = origin
        self._api_prefix = api_prefix
        self._clock = clock
        self._read_restricted = _restricted(settings.read_projects)
        self._write_restricted = _restricted(settings.write_projects)
        self.positives: dict[int, str] = {}
        self._readable: set[int] = set()
        self._negatives: dict[int, float] = {}
        self._seen_by_scan: set[int] = set()
        # A scan's results must not overwrite what record() learned after the
        # scan started; each write is stamped so the scan can tell.
        self._sequence = 0
        self._written_at: dict[int, int] = {}
        self._last_scan_attempt: float | None = None
        self._scan_task: asyncio.Task[None] | None = None
        self._lookups: dict[int, asyncio.Task[None]] = {}
        self._lookup_slots = asyncio.Semaphore(_CONCURRENT_LOOKUPS)

    @property
    def _active(self) -> bool:
        return self._read_restricted or self._write_restricted

    def readable_project_ids(self) -> frozenset[int]:
        return frozenset(self._readable)

    def record(self, project_id: int, identifier: str, name: str | None, *, archived: bool) -> None:
        if not self._active:
            return
        self._sequence += 1
        self._written_at[project_id] = self._sequence
        self._apply(_Project(project_id, identifier, name, archived), now=self._clock())

    def _apply(self, project: _Project, *, now: float) -> None:
        project_id = project.id
        readable, allowed = self._verdict(project_id, project.identifier, project.name)
        if allowed:
            self.positives[project_id] = project.identifier
            self._negatives.pop(project_id, None)
            # OpenProject hides an archived project's work packages and
            # rejects it as a work-package project filter value.
            if readable and not project.archived:
                self._readable.add(project_id)
            else:
                self._readable.discard(project_id)
        else:
            self.positives.pop(project_id, None)
            self._readable.discard(project_id)
            self._negatives[project_id] = now + FRESHNESS_SECONDS

    def _verdict(self, project_id: int, identifier: str, name: str | None) -> tuple[bool, bool]:
        candidates = project_record_candidates(project_id, identifier, name)
        readable = self._read_restricted and scope_matches_candidates(self._settings.read_projects, candidates)
        writable = self._write_restricted and scope_matches_candidates(self._settings.write_projects, candidates)
        return readable, readable or writable

    async def refresh(self) -> None:
        """Rescan all visible projects; at most one scan runs at a time."""
        if not self._active:
            return
        if self._scan_task is None or self._scan_task.done():
            self._scan_task = asyncio.create_task(self._scan())
        await asyncio.shield(self._scan_task)

    async def ensure_fresh(self) -> None:
        if not self._active:
            return
        if self._last_scan_attempt is not None and self._clock() - self._last_scan_attempt < FRESHNESS_SECONDS:
            return
        await self.refresh()

    async def _scan(self) -> None:
        started_at = self._sequence
        projects: list[_Project] = []
        try:
            offset = 1
            while True:
                page = await self._api.list(
                    server_offset=offset, server_page_size=self._settings.max_page_size, search=None
                )
                projects.extend(project for record in page.records if (project := _from_summary(record.summary)))
                if page.exhausted or not page.records:
                    break
                offset += 1
        except OpenProjectError as exc:
            LOGGER.warning(
                "Project allowlist scan failed; projects not seen in a response stay denied until a later scan: %s",
                exc,
            )
            return
        finally:
            self._last_scan_attempt = self._clock()
        self._replace_with_scan(projects, started_at)

    def _replace_with_scan(self, projects: list[_Project], started_at: int) -> None:
        newer = {project_id for project_id, sequence in self._written_at.items() if sequence > started_at}
        kept_positives = {pid: ident for pid, ident in self.positives.items() if pid in newer}
        kept_readable = self._readable & newer
        kept_negatives = {pid: expiry for pid, expiry in self._negatives.items() if pid in newer}
        now = self._clock()
        self.positives.clear()
        self._readable.clear()
        self._negatives.clear()
        for project in projects:
            if project.id not in newer:
                self._apply(project, now=now)
        self.positives.update(kept_positives)
        self._readable.update(kept_readable)
        self._negatives.update(kept_negatives)
        self._seen_by_scan = {project.id for project in projects}

    async def learn(self, payload: Any) -> None:
        """Record every project the payload shows or links to."""
        if not self._active or not isinstance(payload, dict):
            return
        linked: set[int] = set()
        for node in _hal_resources(payload):
            representation = self._project_representation(node)
            if representation is not None:
                self.record(
                    representation.id,
                    representation.identifier,
                    representation.name,
                    archived=representation.archived,
                )
            links = node.get("_links")
            if isinstance(links, dict):
                for link in _link_objects(links):
                    project_id = self._project_id_from_href(link.get("href"))
                    if project_id is not None:
                        linked.add(project_id)
        now = self._clock()
        rescan = False
        lookups: list[int] = []
        for project_id in linked:
            if project_id in self.positives:
                continue
            expiry = self._negatives.get(project_id)
            if expiry is not None and expiry > now:
                continue
            if project_id in self._seen_by_scan:
                rescan = True
            else:
                lookups.append(project_id)
        if rescan:
            await self.ensure_fresh()
        if lookups:
            await asyncio.gather(*(self._look_up(project_id) for project_id in lookups))

    async def _look_up(self, project_id: int) -> None:
        task = self._lookups.get(project_id)
        if task is None:
            task = asyncio.create_task(self._fetch(project_id))
            self._lookups[project_id] = task
            task.add_done_callback(lambda _: self._lookups.pop(project_id, None))
        await asyncio.shield(task)

    async def _fetch(self, project_id: int) -> None:
        try:
            async with self._lookup_slots:
                record = await self._api.get(str(project_id))
        except NotFoundError:
            self._sequence += 1
            self._written_at[project_id] = self._sequence
            self.positives.pop(project_id, None)
            self._readable.discard(project_id)
            self._negatives[project_id] = self._clock() + FRESHNESS_SECONDS
            return
        except OpenProjectError as exc:
            LOGGER.warning("Project %s could not be looked up for the allowlist; it stays denied: %s", project_id, exc)
            return
        project = _from_summary(record.summary)
        if project is not None:
            self.record(project.id, project.identifier, project.name, archived=project.archived)

    def _project_representation(self, node: dict[str, Any]) -> _Project | None:
        # A form's _embedded.payload carries a proposed identifier but no id
        # and no self link, so it never qualifies.
        if node.get("_type") != "Project":
            return None
        project_id, identifier = node.get("id"), node.get("identifier")
        if not isinstance(project_id, int) or not isinstance(identifier, str) or not identifier:
            return None
        links = node.get("_links")
        self_link = links.get("self") if isinstance(links, dict) else None
        if not isinstance(self_link, dict) or self._project_id_from_href(self_link.get("href")) != project_id:
            return None
        name = node.get("name")
        return _Project(project_id, identifier, name if isinstance(name, str) else None, node.get("active") is False)

    def _project_id_from_href(self, href: Any) -> int | None:
        if not isinstance(href, str):
            return None
        parsed = urlparse(href)
        if (parsed.scheme or parsed.netloc) and f"{parsed.scheme}://{parsed.netloc}" != self._origin:
            return None
        path = parsed.path
        if not path.startswith(self._api_prefix):
            return None
        match = _PROJECT_PATH.fullmatch(path[len(self._api_prefix) :].rstrip("/"))
        return int(match.group(1)) if match else None


class _Project(NamedTuple):
    id: int
    identifier: str
    name: str | None
    archived: bool


def _from_summary(summary: ProjectSummary) -> _Project | None:
    if not summary.identifier:
        return None
    return _Project(summary.id, summary.identifier, summary.name, summary.active is False)


def _restricted(scope: tuple[str, ...]) -> bool:
    return bool(scope) and not scope_allows_all(scope)


def _hal_resources(resource: Any) -> Iterator[dict[str, Any]]:
    """The server's own resources in a response body, never the free-form
    content inside them: a property such as a grid's options holds whatever
    an editor wrote, so a project or link there would let any editor widen
    access or make this server issue requests."""
    if not isinstance(resource, dict):
        return
    yield resource
    if resource.get("_type") == "JobStatus":
        # Written by the job itself; a finished copy links the new project here.
        yield from _hal_resources(resource.get("payload"))
    embedded = resource.get("_embedded")
    if isinstance(embedded, dict):
        for child in embedded.values():
            for item in child if isinstance(child, list) else [child]:
                yield from _hal_resources(item)


def _link_objects(links: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for link in links.values():
        if isinstance(link, dict):
            yield link
        elif isinstance(link, list):
            yield from (item for item in link if isinstance(item, dict))
