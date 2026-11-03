"""Which projects the configured allowlists cover, by numeric project id.

A project link in a HAL response carries only an href and a title, so an
identifier-based allowlist can match a linked project only through
an id -> identifier map. The map has to know projects that came into being
after the server started (a copy, the web UI, another client), not just the
ones present at startup. The directory learns them from every JSON response
before a policy sees it (see transport.learning_transport) and looks up an
id when no response or scan has shown it yet. A known project is read
again, in one request for all such projects of a response, whenever its
recorded identifier alone would admit a link to it: the link carries no
identifier, and the recorded one may predate a rename. Once per tool call is
enough: what a call relies on cannot change under it any more than a check
can be made atomic with the request it guards.

The policies read `positives` synchronously; it is updated in place and never
rebound, because every service and resolver holds the same object.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterator, Sequence
from functools import partial
from typing import Any, NamedTuple

from ... import http_request_counter
from ...config import Settings
from ...context_gather import gather_in_current_context
from ...models import ProjectSummary
from ..call_scope import current_tool_call
from ..errors import NotFoundError, OpenProjectError
from ..policies.scope import (
    LinkedProject,
    parse_project_href,
    project_link_candidates,
    project_record_candidates,
    scope_allows_all,
    scope_matches_candidates,
)
from ..ports.project_lookup_api import ProjectLookupApi

LOGGER = logging.getLogger(__name__)

# Bounds both how long a project created elsewhere can stay missing from the
# readable set and how long an out-of-scope verdict outlives a change in
# OpenProject.
FRESHNESS_SECONDS = 300.0

# One response can link any number of unseen projects.
_CONCURRENT_LOOKUPS = 10


class ProjectDirectoryService:
    def __init__(
        self,
        *,
        api: ProjectLookupApi,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api = api
        self._settings = settings
        self._clock = clock
        self._read_restricted = _restricted(settings.read_projects)
        self._write_restricted = _restricted(settings.write_projects)
        self.positives: dict[int, str] = {}
        self._readable: set[int] = set()
        self._negatives: dict[int, float] = {}
        self._seen_by_scan: set[int] = set()
        # Every entry is stamped with the tick at which the read it came from
        # began (a scan, a lookup, the request whose response showed it, or
        # the moment it was dropped). Older data never overwrites newer, and a response relies on
        # an identifier only if it was read after the response arrived: one
        # read earlier can predate a rename the response already reflects.
        self._ticks = 0
        self._as_of: dict[int, int] = {}
        # The tool call that last read the project's identifier again.
        self._reread_in_call: dict[int, int] = {}
        self._last_scan_attempt: float | None = None
        self._scan_task: asyncio.Task[None] | None = None
        self._lookups: dict[int, _Lookup] = {}
        self._lookup_slots = asyncio.Semaphore(_CONCURRENT_LOOKUPS)

    @property
    def _active(self) -> bool:
        return self._read_restricted or self._write_restricted

    def readable_project_ids(self) -> frozenset[int]:
        return frozenset(self._readable)

    async def current_readable_project_ids(self) -> frozenset[int]:
        """The readable projects, each re-read from OpenProject unless its id
        alone matches the read allowlist: a recorded identifier can
        predate a rename, and OpenProject counts and sums everything a
        work-package filter names."""
        await self.ensure_fresh()
        by_id = {
            project_id
            for project_id in self._readable
            if scope_matches_candidates(self._settings.read_projects, {str(project_id)})
        }
        recorded = sorted(self._readable - by_id)
        if not recorded:
            return frozenset(by_id)
        started = self._tick()
        current = {project.id: project for project in await self._list_projects(ids=recorded)}
        for project_id in recorded:
            project = current.get(project_id)
            if project is None:
                self._forget(project_id, as_of=started)
            else:
                self._store(project, as_of=started)
        # What was recorded while the request ran may be newer than its answer.
        return frozenset(self._readable & (by_id | set(recorded)))

    async def readable_descendant_ids(self, project_id: int) -> frozenset[int]:
        """The readable projects below `project_id`, at any depth, judged on what OpenProject
        answers now: it adds every descendant of a project a work-package filter names,
        readable or not, and counts and sums them."""
        started = self._tick()
        projects = await self._list_projects(ids=None, ancestor_id=project_id)
        for project in projects:
            self._store(project, as_of=started)
        return frozenset(project.id for project in projects if project.id in self._readable)

    def _tick(self) -> int:
        self._ticks += 1
        return self._ticks

    def record(self, project_id: int, identifier: str, *, archived: bool) -> None:
        self._store(_Project(project_id, identifier, archived), as_of=self._tick())

    def _store(self, project: _Project, *, as_of: int) -> None:
        if not self._active or self._as_of.get(project.id, 0) > as_of:
            return
        self._as_of[project.id] = as_of
        self._apply(project, now=self._clock())

    def _apply(self, project: _Project, *, now: float) -> None:
        project_id = project.id
        readable, allowed = self._verdict(project_id, project.identifier)
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

    def _verdict(self, project_id: int, identifier: str) -> tuple[bool, bool]:
        candidates = project_record_candidates(project_id, identifier)
        readable = self._read_restricted and scope_matches_candidates(self._settings.read_projects, candidates)
        writable = self._write_restricted and scope_matches_candidates(self._settings.write_projects, candidates)
        return readable, readable or writable

    async def refresh(self) -> None:
        """Rescan all visible projects; at most one scan runs at a time."""
        if not self._active:
            return
        if self._scan_task is not None and not self._scan_task.done():
            await asyncio.shield(self._scan_task)
            return
        self._scan_task, adopt_requests = http_request_counter.start_owned(self._scan())
        try:
            await asyncio.shield(self._scan_task)
        finally:
            adopt_requests()

    async def ensure_fresh(self) -> None:
        if not self._active:
            return
        if self._last_scan_attempt is not None and self._clock() - self._last_scan_attempt < FRESHNESS_SECONDS:
            return
        await self.refresh()

    async def _scan(self) -> None:
        started = self._tick()
        try:
            projects = await self._list_projects(ids=None)
        except OpenProjectError as exc:
            LOGGER.warning(
                "Project allowlist scan failed; projects not seen in a response stay denied until a later scan: %s",
                exc,
            )
            return
        finally:
            self._last_scan_attempt = self._clock()
        self._replace_with_scan(projects, started)

    async def _list_projects(self, *, ids: Sequence[int] | None, ancestor_id: int | None = None) -> list[_Project]:
        projects: list[_Project] = []
        offset = 1
        while True:
            page = await self._api.list(
                server_offset=offset,
                server_page_size=self._settings.max_page_size,
                search=None,
                ids=ids,
                ancestor_id=ancestor_id,
            )
            projects.extend(project for record in page.records if (project := _from_summary(record.summary)))
            if page.exhausted or not page.records:
                return projects
            offset += 1

    def _replace_with_scan(self, projects: list[_Project], started: int) -> None:
        newer = {project_id for project_id, as_of in self._as_of.items() if as_of > started}
        kept_positives = {pid: ident for pid, ident in self.positives.items() if pid in newer}
        kept_readable = self._readable & newer
        kept_negatives = {pid: expiry for pid, expiry in self._negatives.items() if pid in newer}
        now = self._clock()
        self.positives.clear()
        self._readable.clear()
        self._negatives.clear()
        for project in projects:
            if project.id not in newer:
                self._as_of[project.id] = started
                self._apply(project, now=now)
        # Absence from the scan is a finding as of its start too, so a response
        # sent before it cannot bring a project back.
        scanned = {project.id for project in projects}
        for project_id in self._as_of.keys() - newer - scanned:
            self._as_of[project_id] = started
        self.positives.update(kept_positives)
        self._readable.update(kept_readable)
        self._negatives.update(kept_negatives)
        # A project forgotten after the scan started stays unknown, so the
        # next link looks it up instead of waiting for the next scan.
        self._seen_by_scan = scanned - newer

    def request_sent(self) -> int:
        return self._tick()

    async def learn(self, payload: Any, *, sent: int) -> None:
        """Record every project the payload shows or links to; `sent` is
        request_sent() from just before the request that returned it."""
        if not self._active or not isinstance(payload, dict):
            return
        received = self._tick()
        shown: set[int] = set()
        linked: dict[int, list[dict[str, Any]]] = {}
        for node in _hal_resources(payload):
            representation = self._project_representation(node)
            if representation is not None:
                self._store(representation, as_of=sent)
                shown.add(representation.id)
            links = node.get("_links")
            if isinstance(links, dict):
                for link in _link_objects(links):
                    project_id = self._project_id_from_href(link.get("href"))
                    if project_id is not None:
                        linked.setdefault(project_id, []).append(link)
        unshown = [project_id for project_id in linked if project_id not in shown]
        now = self._clock()
        rescan = False
        lookups: dict[int, None] = {}
        for project_id in unshown:
            if project_id in self.positives:
                continue
            expiry = self._negatives.get(project_id)
            if expiry is not None and expiry > now:
                continue
            if project_id in self._seen_by_scan:
                rescan = True
            else:
                lookups[project_id] = None
        if rescan:
            await self.ensure_fresh()
        # A link carries no identifier, so a recorded one read before this
        # response arrived is read again wherever it alone would admit the link.
        call = current_tool_call()
        stale = [
            project_id
            for project_id in unshown
            if (identifier := self.positives.get(project_id)) is not None
            and self._as_of.get(project_id, 0) < received
            and (call is None or self._reread_in_call.get(project_id) != call)
            and any(self._identifier_decides(link, project_id, identifier) for link in linked[project_id])
        ]
        reads = [self._look_up(project_id, received=received) for project_id in lookups]
        if stale:
            reads.append(self._read_again(stale, call=call))
        if reads:
            # Lookups run in shared, deduplicated tasks that may serve several tool calls, so their
            # requests belong to no single call's counters; the re-read is this call's own.
            await gather_in_current_context(*reads)

    def _identifier_decides(self, link: dict[str, Any], project_id: int, identifier: str) -> bool:
        without = project_link_candidates(link, settings=self._settings, project_id_to_identifier={})
        with_identifier = project_link_candidates(
            link, settings=self._settings, project_id_to_identifier={project_id: identifier}
        )
        return any(
            scope_matches_candidates(scope, with_identifier) and not scope_matches_candidates(scope, without)
            for scope in (self._settings.read_projects, self._settings.write_projects)
        )

    async def _read_again(self, project_ids: list[int], *, call: int | None) -> None:
        """One request for the projects whose recorded identifier decided a link. A project the
        answer leaves out is forgotten, so the next link to it is looked up on its own."""
        started = self._tick()
        try:
            current = {project.id: project for project in await self._list_projects(ids=project_ids)}
        except OpenProjectError as exc:
            LOGGER.warning(
                "Projects %s could not be read again for the allowlist; only their id matches until a "
                "lookup succeeds: %s",
                project_ids,
                exc,
            )
            current = {}
        for project_id in project_ids:
            project = current.get(project_id)
            if project is None:
                self._forget(project_id, as_of=started)
            else:
                self._store(project, as_of=started)
            if call is not None:
                self._reread_in_call[project_id] = call

    async def _look_up(self, project_id: int, *, received: int) -> None:
        lookup = self._lookups.get(project_id)
        if lookup is not None and lookup.started >= received:
            await asyncio.shield(lookup.task)
            return
        started = self._tick()
        task, adopt_requests = http_request_counter.start_owned(self._fetch(project_id, started))
        lookup = _Lookup(task, started)
        self._lookups[project_id] = lookup
        lookup.task.add_done_callback(partial(self._lookup_done, project_id, lookup))
        try:
            await asyncio.shield(lookup.task)
        finally:
            adopt_requests()

    def _lookup_done(self, project_id: int, lookup: _Lookup, _task: asyncio.Task[None]) -> None:
        if self._lookups.get(project_id) is lookup:
            del self._lookups[project_id]

    async def _fetch(self, project_id: int, started: int) -> None:
        try:
            async with self._lookup_slots:
                record = await self._api.get(str(project_id))
        except NotFoundError:
            if self._drop(project_id, as_of=started):
                self._negatives[project_id] = self._clock() + FRESHNESS_SECONDS
            return
        except OpenProjectError as exc:
            LOGGER.warning(
                "Project %s could not be looked up for the allowlist; only its id matches until a lookup succeeds: %s",
                project_id,
                exc,
            )
            self._forget(project_id, as_of=started)
            return
        project = _from_summary(record.summary)
        if project is None:
            self._forget(project_id, as_of=started)
            return
        self._store(project, as_of=started)

    def _drop(self, project_id: int, *, as_of: int) -> bool:
        """Drop what a read that began at `as_of` can no longer vouch for,
        unless a later read has recorded the project since."""
        if self._as_of.get(project_id, 0) > as_of:
            return False
        self._as_of[project_id] = as_of
        self.positives.pop(project_id, None)
        self._readable.discard(project_id)
        return True

    def _forget(self, project_id: int, *, as_of: int) -> None:
        if self._drop(project_id, as_of=as_of):
            # Unknown again, so the next link to it looks it up instead of waiting for a rescan.
            self._seen_by_scan.discard(project_id)

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
        return _Project(project_id, identifier, node.get("active") is False)

    def _project_id_from_href(self, href: Any) -> int | None:
        # Learning runs on every response; a link under another root path is
        # reported where it is checked, not here.
        parsed = parse_project_href(href, settings=self._settings)
        return parsed.id if isinstance(parsed, LinkedProject) else None


class _Lookup(NamedTuple):
    task: asyncio.Task[None]
    started: int


class _Project(NamedTuple):
    id: int
    identifier: str
    archived: bool


def _from_summary(summary: ProjectSummary) -> _Project | None:
    if not summary.identifier:
        return None
    return _Project(summary.id, summary.identifier, summary.active is False)


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
