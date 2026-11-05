"""Edits of a stored long text are computed against the stored text, for every field that has the pair.

The fields are the comment of a work package, the description and status explanation of a project, and the
description of a version, a document and a news entry. Each one runs through the same cases, so a field cannot
get the pair without passing them. The work package description has its own file
(`test_work_package_description_edit.py`); both use `app/services/_stored_text_edit.py`.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from _client_test_helpers import make_settings, started_client
from _tools_test_helpers import FakeContext

from openproject_ce_mcp.app.errors import InvalidInputError, OpenProjectPermissionDeniedError, ProjectScopeDeniedError
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.tool_errors import ToolInputError
from openproject_ce_mcp.tools import (
    update_document,
    update_news,
    update_project,
    update_version,
    update_work_package_comment,
)

PROJECT = (1, "demo", "Demo")
OTHER_PROJECT = (7, "other", "Other")
OTHER_STATUS = "Unrelated status explanation."
OTHER_DESCRIPTION = "Unrelated description."


@dataclass
class Store:
    """What the fake OpenProject holds for one record, and what was sent to it."""

    stored: str | None
    requests: list[str] = field(default_factory=list)
    bodies: list[dict[str, Any]] = field(default_factory=list)


def _hal(raw: str | None, fmt: str = "markdown") -> dict[str, Any] | None:
    return None if raw is None else {"format": fmt, "raw": raw, "html": "<p>ignored</p>"}


def _json(request: httpx.Request, payload: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=request)


def _unexpected(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _form(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    return _json(request, {"_type": "Form", "_embedded": {"schema": {}, "payload": body, "validationErrors": {}}})


# --- the six fields -------------------------------------------------------------------------------------------------


@dataclass
class Rig:
    """One field: its fake server, the way to edit it through the client, and where the text sits in a payload."""

    name: str
    param: str
    hidden: tuple[str, str]
    handler: Callable[[Store], Callable[[httpx.Request], httpx.Response]]
    edit: Callable[[OpenProjectClient, dict[str, Any], bool], Awaitable[Any]]
    text_of: Callable[[dict[str, Any]], str]
    payload_text: Callable[[Any], str]
    noun: str
    empty_stored_error: str | None = None


def _comment_handler(store: Store) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        store.requests.append(f"{method} {path}")
        if method == "GET" and path == "/api/v3/activities/77":
            return _json(
                request,
                {
                    "id": 77,
                    "_type": "Activity::Comment",
                    "comment": _hal(store.stored),
                    "_links": {
                        "user": {"title": "Alice"},
                        "workPackage": {"href": "/api/v3/work_packages/42"},
                        "update": {"href": "/api/v3/activities/77", "method": "patch"},
                    },
                },
            )
        if method == "GET" and path == "/api/v3/work_packages/42":
            return _json(request, {"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}})
        if method == "PATCH" and path == "/api/v3/activities/77":
            body = json.loads(request.content)
            store.bodies.append(body)
            return _json(
                request,
                {
                    "id": 77,
                    "_type": "Activity::Comment",
                    "comment": _hal(body["comment"]),
                    "_links": {"user": {"title": "Alice"}},
                },
            )
        return _unexpected(request)

    return handler


def _project_handler(param: str) -> Callable[[Store], Callable[[httpx.Request], httpx.Response]]:
    key = {"description": "description", "status_explanation": "statusExplanation"}[param]

    def build(store: Store) -> Callable[[httpx.Request], httpx.Response]:
        def record() -> dict[str, Any]:
            record = {
                "_type": "Project",
                "id": 1,
                "identifier": "demo",
                "name": "Demo",
                "description": _hal(OTHER_DESCRIPTION),
                "statusExplanation": _hal(OTHER_STATUS),
                "_links": {},
            }
            record[key] = _hal(store.stored)
            return record

        def handler(request: httpx.Request) -> httpx.Response:
            path, method = request.url.path, request.method
            store.requests.append(f"{method} {path}")
            if method == "GET" and path in ("/api/v3/projects/demo", "/api/v3/projects/1"):
                return _json(request, record())
            if method == "POST" and path == "/api/v3/projects/1/form":
                return _form(request)
            if method == "PATCH" and path == "/api/v3/projects/1":
                store.bodies.append(json.loads(request.content))
                return _json(request, record())
            return _unexpected(request)

        return handler

    return build


def _version_handler(store: Store) -> Callable[[httpx.Request], httpx.Response]:
    def record() -> dict[str, Any]:
        return {
            "_type": "Version",
            "id": 8,
            "name": "Release",
            "status": "open",
            "description": _hal(store.stored, "plain"),
            "_links": {"definingProject": {"href": "/api/v3/projects/1", "title": "Demo"}},
        }

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        store.requests.append(f"{method} {path}")
        if method == "GET" and path == "/api/v3/versions/8":
            return _json(request, record())
        if method == "POST" and path == "/api/v3/versions/8/form":
            return _form(request)
        if method == "PATCH" and path == "/api/v3/versions/8":
            store.bodies.append(json.loads(request.content))
            return _json(request, record())
        return _unexpected(request)

    return handler


def _document_handler(store: Store) -> Callable[[httpx.Request], httpx.Response]:
    def record() -> dict[str, Any]:
        return {
            "_type": "Document",
            "id": 5,
            "title": "Handbook",
            "description": _hal(store.stored),
            "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
        }

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        store.requests.append(f"{method} {path}")
        if method == "GET" and path == "/api/v3/documents/5":
            return _json(request, record())
        if method == "PATCH" and path == "/api/v3/documents/5":
            store.bodies.append(json.loads(request.content))
            return _json(request, record())
        return _unexpected(request)

    return handler


def _news_handler(store: Store) -> Callable[[httpx.Request], httpx.Response]:
    def record() -> dict[str, Any]:
        return {
            "_type": "News",
            "id": 3,
            "title": "Release",
            "summary": "Short.",
            "description": _hal(store.stored),
            "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
        }

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        store.requests.append(f"{method} {path}")
        if method == "GET" and path == "/api/v3/news/3":
            return _json(request, record())
        if method == "PATCH" and path == "/api/v3/news/3":
            store.bodies.append(json.loads(request.content))
            return _json(request, record())
        return _unexpected(request)

    return handler


def _kwargs(param: str, given: dict[str, Any]) -> dict[str, Any]:
    """`given` keys are the suffixes of the parameter family: '' (full), '_append', '_replace'."""
    return {f"{param}{suffix}": value for suffix, value in given.items()}


RIGS = [
    Rig(
        name="comment",
        param="comment",
        hidden=("activity", "comment"),
        handler=_comment_handler,
        edit=lambda client, given, confirm: client.work_package.update_comment(
            activity_id=77, **_kwargs("comment", given), confirm=confirm
        ),
        text_of=lambda body: body["comment"],
        payload_text=lambda result: result.payload["comment"],
        noun="comment",
        empty_stored_error="has no existing comment to edit",
    ),
    Rig(
        name="project description",
        param="description",
        hidden=("project", "description"),
        handler=_project_handler("description"),
        edit=lambda client, given, confirm: client.update_project(
            project_ref="demo", **_kwargs("description", given), confirm=confirm
        ),
        text_of=lambda body: body["description"]["raw"],
        payload_text=lambda result: result.payload["description"]["raw"],
        noun="description",
    ),
    Rig(
        name="project status explanation",
        param="status_explanation",
        hidden=("project", "status_explanation"),
        handler=_project_handler("status_explanation"),
        edit=lambda client, given, confirm: client.update_project(
            project_ref="demo", **_kwargs("status_explanation", given), confirm=confirm
        ),
        text_of=lambda body: body["statusExplanation"]["raw"],
        payload_text=lambda result: result.payload["statusExplanation"]["raw"],
        noun="status explanation",
    ),
    Rig(
        name="version description",
        param="description",
        hidden=("version", "description"),
        handler=_version_handler,
        edit=lambda client, given, confirm: client.version.update(
            version_id=8, **_kwargs("description", given), confirm=confirm
        ),
        text_of=lambda body: body["description"]["raw"],
        payload_text=lambda result: result.payload["description"]["raw"],
        noun="description",
    ),
    Rig(
        name="document description",
        param="description",
        hidden=("document", "description"),
        handler=_document_handler,
        edit=lambda client, given, confirm: client.document.update(
            document_id=5, **_kwargs("description", given), confirm=confirm
        ),
        text_of=lambda body: body["description"],
        payload_text=lambda result: result.payload["description"],
        noun="description",
    ),
    Rig(
        name="news description",
        param="description",
        hidden=("news", "description"),
        handler=_news_handler,
        edit=lambda client, given, confirm: client.news.update(
            news_id=3, **_kwargs("description", given), confirm=confirm
        ),
        text_of=lambda body: body["description"]["raw"],
        payload_text=lambda result: result.payload["description"]["raw"],
        noun="description",
    ),
]
rigs = pytest.mark.parametrize("rig", RIGS, ids=[rig.name for rig in RIGS])


def _settings(**overrides: Any) -> Settings:
    base = dataclasses.replace(
        make_settings(),
        enable_work_package_write=True,
        enable_project_write=True,
        enable_version_write=True,
    )
    return dataclasses.replace(base, **overrides)


class Session:
    def __init__(self, rig: Rig, stored: str | None, settings: Settings | None = None) -> None:
        self.rig = rig
        self.store = Store(stored)
        self.settings = settings or _settings()
        self.client: OpenProjectClient | None = None

    async def __aenter__(self) -> Session:
        self.client = await started_client(self.settings, self.rig.handler(self.store), [PROJECT, OTHER_PROJECT])
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self.client is not None
        await self.client.aclose()

    async def edit(self, confirm: bool = True, **given: Any) -> Any:
        """`given` maps '' / '_append' / '_replace' (passed as full / append / replace) to values."""
        assert self.client is not None
        suffixes = {"full": "", "append": "_append", "replace": "_replace"}
        return await self.rig.edit(self.client, {suffixes[key]: value for key, value in given.items()}, confirm)

    @property
    def written(self) -> list[str]:
        return [self.rig.text_of(body) for body in self.store.bodies]

    @property
    def writes_made(self) -> bool:
        return any(request.startswith("PATCH ") for request in self.store.requests)


def _hide(rig: Rig) -> Settings:
    entity, name = rig.hidden
    return _settings(hidden_fields={entity: (name,)})


# --- append ---------------------------------------------------------------------------------------------------------


@rigs
@pytest.mark.parametrize(
    ("stored", "text", "expected"),
    [
        ("Intro.", "More.", "Intro.\n\nMore."),
        ("Intro.\n\n\n", "More.", "Intro.\n\nMore."),
        ("Line one\r\nLine two\r\n", "More.", "Line one\r\nLine two\n\nMore."),
        ("  indented\n\n    code\n", "More.", "  indented\n\n    code\n\nMore."),
        ("Hard break  ", "More.", "Hard break  \n\nMore."),
    ],
)
async def test_an_append_lands_after_the_stored_text_and_leaves_it_byte_identical(
    rig: Rig, stored: str, text: str, expected: str
) -> None:
    async with Session(rig, stored) as session:
        await session.edit(append=text)

    assert session.written == [expected]


@rigs
@pytest.mark.parametrize("stored", ["", "  \n ", None])
async def test_an_append_to_an_empty_stored_text_is_the_text_itself(rig: Rig, stored: str | None) -> None:
    async with Session(rig, stored) as session:
        if rig.empty_stored_error:
            with pytest.raises(InvalidInputError, match=rig.empty_stored_error):
                await session.edit(append="More.")
            assert not session.writes_made
        else:
            await session.edit(append="More.")
            assert session.written == ["More."]


@rigs
@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
async def test_a_blank_append_is_rejected(rig: Rig, text: str) -> None:
    async with Session(rig, "Stored.") as session:
        with pytest.raises(InvalidInputError, match=f"{rig.param}_append must not be blank"):
            await session.edit(append=text)

    assert not session.writes_made


# --- replace --------------------------------------------------------------------------------------------------------


@rigs
@pytest.mark.parametrize(
    ("stored", "old", "new", "expected"),
    [
        ("Alpha beta gamma.", "beta", "BETA", "Alpha BETA gamma."),
        ("Alpha\n\n  beta   gamma\n", "beta gamma", "delta", "Alpha\n\n  delta\n"),
        ("Line one\r\nbeta\r\nLine three", "one beta", "x", "Line x\r\nLine three"),
        ("Keep this. Drop that. Keep the end.", "Drop that.", "", "Keep this.  Keep the end."),
    ],
)
async def test_a_replace_changes_one_passage_across_differences_in_whitespace(
    rig: Rig, stored: str, old: str, new: str, expected: str
) -> None:
    async with Session(rig, stored) as session:
        await session.edit(replace={"old": old, "new": new})

    assert session.written == [expected]


@rigs
async def test_a_passage_that_is_not_there_names_the_parameter_and_not_the_stored_text(rig: Rig) -> None:
    async with Session(rig, "Secret stored text.") as session:
        with pytest.raises(InvalidInputError) as raised:
            await session.edit(replace={"old": "absent passage", "new": "x"})

    assert f"{rig.param}_replace.old was not found in the stored {rig.noun}" in str(raised.value)
    assert "Secret" not in str(raised.value)
    assert not session.writes_made


@rigs
@pytest.mark.parametrize("stored", ["go go go", "ab ab", "x. x."])
async def test_a_passage_that_occurs_twice_is_refused(rig: Rig, stored: str) -> None:
    old = stored.split()[0]
    async with Session(rig, stored) as session:
        with pytest.raises(InvalidInputError, match=f"{rig.param}_replace.old matches 2 passages|matches 3 passages"):
            await session.edit(replace={"old": old, "new": "z"})

    assert not session.writes_made


@rigs
@pytest.mark.parametrize("old", ["", "   "])
async def test_a_blank_old_is_refused(rig: Rig, old: str) -> None:
    async with Session(rig, "text") as session:
        with pytest.raises(InvalidInputError, match="must not be blank"):
            await session.edit(replace={"old": old, "new": "z"})


@rigs
@pytest.mark.parametrize("replace", [{"old": "a"}, {"old": "a", "new": "b", "extra": "c"}, {"old": "a", "new": 1}])
async def test_a_replace_takes_exactly_the_string_keys_old_and_new(rig: Rig, replace: dict[str, Any]) -> None:
    async with Session(rig, "a") as session:
        with pytest.raises(InvalidInputError, match=f"{rig.param}_replace takes exactly the string keys"):
            await session.edit(replace=replace)


# --- exclusivity ----------------------------------------------------------------------------------------------------


@rigs
@pytest.mark.parametrize(
    "given",
    [
        {"full": "x", "append": "y"},
        {"full": "x", "replace": {"old": "a", "new": "b"}},
        {"append": "y", "replace": {"old": "a", "new": "b"}},
        {"full": "x", "append": "y", "replace": {"old": "a", "new": "b"}},
    ],
)
async def test_the_three_inputs_of_a_field_exclude_each_other(rig: Rig, given: dict[str, Any]) -> None:
    async with Session(rig, "a") as session:
        with pytest.raises(InvalidInputError, match="cannot be combined"):
            await session.edit(**given)

    assert not session.writes_made


# --- a cut copy -----------------------------------------------------------------------------------------------------


@rigs
@pytest.mark.parametrize(
    "text",
    [
        "The first paragraph of the stored text…",
        "The first paragraph of the stored text… And a new sentence after the cut.",
    ],
)
async def test_a_full_text_that_holds_a_cut_copy_of_the_stored_text_is_refused(rig: Rig, text: str) -> None:
    stored = "The first paragraph of the stored text.\n\nThe second paragraph, which a read would have cut."
    async with Session(rig, stored) as session:
        with pytest.raises(InvalidInputError) as raised:
            await session.edit(full=text)

    message = str(raised.value)
    assert f"{rig.param}_append" in message and f"{rig.param}_replace" in message
    assert "truncated read" in message
    assert not session.writes_made


@rigs
@pytest.mark.parametrize("text", ["Unrelated text.", "The first paragraph…", "Stored text.", "…", "… and more."])
async def test_a_full_text_that_is_not_a_cut_copy_is_written_as_given(rig: Rig, text: str) -> None:
    async with Session(rig, "Stored text.") as session:
        await session.edit(full=text)

    assert session.written == [text]


@rigs
async def test_a_cut_copy_whose_read_escaped_a_tag_look_alike_is_refused(rig: Rig) -> None:
    stored = "Use the <b> tag here and then continue with a very long second paragraph."
    async with Session(rig, stored) as session:
        with pytest.raises(InvalidInputError, match="truncated read"):
            await session.edit(full="Use the &lt;b> tag here and then…")

    assert not session.writes_made


@rigs
async def test_a_harmless_first_ellipsis_does_not_hide_a_cut_after_it(rig: Rig) -> None:
    stored = "Wait… what is next? This is the first part and here comes the rest of it."
    async with Session(rig, stored) as session:
        with pytest.raises(InvalidInputError, match="truncated read"):
            await session.edit(full="Wait… what is next? This is the first part…")

    assert not session.writes_made


@rigs
async def test_a_stored_ellipsis_at_the_cut_position_is_not_a_cut_copy(rig: Rig) -> None:
    async with Session(rig, "Wait… and see.") as session:
        await session.edit(full="Wait…")

    assert session.written == ["Wait…"]


# --- hidden field ---------------------------------------------------------------------------------------------------


@rigs
@pytest.mark.parametrize(
    "given",
    [{"append": "More."}, {"replace": {"old": "not in the text", "new": "x"}}, {"full": "Whole."}],
)
async def test_a_hidden_field_refuses_each_input_before_any_edit_runs(rig: Rig, given: dict[str, Any]) -> None:
    async with Session(rig, "Stored text.", _hide(rig)) as session:
        with pytest.raises(InvalidInputError, match=f"'{rig.hidden[1]}' is hidden"):
            await session.edit(**given)

    assert not session.writes_made


@rigs
async def test_a_hidden_field_is_reported_before_two_inputs_are_found_to_clash(rig: Rig) -> None:
    async with Session(rig, "Stored text.", _hide(rig)) as session:
        with pytest.raises(InvalidInputError, match=f"'{rig.hidden[1]}' is hidden"):
            await session.edit(full="a", append="b")

    assert not session.writes_made


# --- the write allowlist comes before anything the edit could reveal --------------------------------------------------


@rigs
async def test_a_record_outside_the_write_allowlist_gives_the_scope_error_and_not_a_match_error(rig: Rig) -> None:
    settings = _settings(write_projects=("other",))
    async with Session(rig, "Secret stored text.", settings) as session:
        with pytest.raises(ProjectScopeDeniedError):
            await session.edit(replace={"old": "absent passage", "new": "x"})

    assert not session.writes_made


# --- preview and confirm ----------------------------------------------------------------------------------------------


@rigs
async def test_the_preview_and_the_confirmed_call_carry_the_same_final_text_and_state_its_length(rig: Rig) -> None:
    stored = "Intro."
    async with Session(rig, stored) as session:
        preview = await session.edit(confirm=False, append="More.")
        assert not session.writes_made
        confirmed = await session.edit(confirm=True, append="More.")

    final = "Intro.\n\nMore."
    assert rig.payload_text(preview) == final == rig.payload_text(confirmed)
    sentence = f"The {rig.noun} changes from {len(stored)} to {len(final)} characters."
    assert sentence in preview.message
    assert sentence in confirmed.message


@rigs
async def test_a_large_shrink_is_called_out(rig: Rig) -> None:
    stored = "x" * 400
    async with Session(rig, stored) as session:
        result = await session.edit(confirm=False, replace={"old": stored, "new": "y"})

    assert f"The {rig.noun} changes from 400 to 1 characters. It shrinks by 399 characters." in result.message


@rigs
@pytest.mark.parametrize(("before", "after", "shrinks"), [(100, 10, False), (1000, 700, False), (300, 100, True)])
async def test_the_shrink_sentence_needs_half_the_text_and_two_hundred_characters(
    rig: Rig, before: int, after: int, shrinks: bool
) -> None:
    stored = "x" * before
    async with Session(rig, stored) as session:
        result = await session.edit(confirm=False, replace={"old": stored, "new": "y" * after})

    assert f"changes from {before} to {after} characters." in result.message
    assert ("It shrinks by" in result.message) is shrinks


@rigs
async def test_a_cut_copy_that_runs_across_a_paragraph_break_is_refused(rig: Rig) -> None:
    stored = "Paragraph one.\n\nParagraph two continues for a good while longer."
    async with Session(rig, stored) as session:
        with pytest.raises(InvalidInputError, match="truncated read"):
            await session.edit(full="Paragraph one. Paragraph two continues…")


@rigs
async def test_the_full_text_path_states_the_length_too(rig: Rig) -> None:
    async with Session(rig, "Old.") as session:
        result = await session.edit(confirm=False, full="Brand new text.")

    assert f"The {rig.noun} changes from 4 to 15 characters." in result.message


# --- what is specific to one field ------------------------------------------------------------------------------------


async def test_the_comment_needs_one_of_its_three_inputs() -> None:
    async with Session(RIGS[0], "Old.") as session:
        with pytest.raises(InvalidInputError, match="Give one of comment, comment_append and comment_replace"):
            await session.edit()

    assert session.store.requests == []


@pytest.mark.parametrize("new", ["", "   ", "\n"])
async def test_an_edit_that_leaves_the_comment_blank_is_refused(new: str) -> None:
    async with Session(RIGS[0], "Remove me") as session:
        with pytest.raises(InvalidInputError, match="would leave the comment blank"):
            await session.edit(replace={"old": "Remove me", "new": new})

    assert not session.writes_made


async def test_the_comment_edit_is_computed_against_the_raw_text_and_not_the_normalised_summary() -> None:
    stored = "First line\n\n- item one\n- item two"
    async with Session(RIGS[0], stored) as session:
        await session.edit(append="Tail.")

    assert session.written == [f"{stored}\n\nTail."]


async def test_the_version_append_is_written_as_plain_text() -> None:
    version = next(rig for rig in RIGS if rig.name == "version description")
    async with Session(version, "Focus.") as session:
        await session.edit(append="More.")

    assert session.store.bodies == [{"description": {"format": "plain", "raw": "Focus.\n\nMore."}}]


async def test_the_document_edit_is_sent_as_a_plain_string() -> None:
    document = next(rig for rig in RIGS if rig.name == "document description")
    async with Session(document, "Focus.") as session:
        await session.edit(append="More.")

    assert session.store.bodies == [{"description": "Focus.\n\nMore."}]


async def test_the_two_text_fields_of_a_project_edit_in_one_call_without_touching_each_other() -> None:
    store = Store("Old description.")
    client = await started_client(_settings(), _project_handler("description")(store), [PROJECT])
    result = await client.update_project(
        project_ref="demo",
        description_append="Added.",
        status_explanation_replace={"old": "Unrelated status", "new": "Changed status"},
        confirm=True,
    )
    await client.aclose()

    assert store.bodies == [
        {
            "description": {"format": "markdown", "raw": "Old description.\n\nAdded."},
            "statusExplanation": {"format": "markdown", "raw": "Changed status explanation."},
        }
    ]
    assert "The description changes from 16 to 24 characters." in result.message
    assert "The status explanation changes from 29 to 27 characters." in result.message


async def test_a_hidden_description_does_not_stop_an_edit_of_the_status_explanation() -> None:
    store = Store("Old description.")
    settings = _settings(hidden_fields={"project": ("description",)})
    client = await started_client(settings, _project_handler("description")(store), [PROJECT])

    await client.update_project(project_ref="demo", status_explanation_append="More.", confirm=True)
    await client.aclose()

    assert [body["statusExplanation"]["raw"] for body in store.bodies] == [f"{OTHER_STATUS}\n\nMore."]


@pytest.mark.parametrize("name", ["project description", "version description", "document description"])
async def test_an_update_that_does_not_touch_the_text_carries_no_length_sentence(name: str) -> None:
    rig = next(rig for rig in RIGS if rig.name == name)
    store = Store("Stored.")
    client = await started_client(_settings(), rig.handler(store), [PROJECT])
    if rig.name == "project description":
        result = await client.update_project(project_ref="demo", name="Renamed", confirm=False)
    elif rig.name == "version description":
        result = await client.version.update(version_id=8, name="Renamed", confirm=False)
    else:
        result = await client.document.update(document_id=5, title="Renamed", confirm=False)
    await client.aclose()

    assert "changes from" not in result.message


# --- the tool layer ---------------------------------------------------------------------------------------------------


def _tool_calls() -> dict[str, Callable[..., Awaitable[Any]]]:
    return {
        "comment": lambda ctx, **kw: update_work_package_comment(ctx, 77, **kw),
        "project description": lambda ctx, **kw: update_project(ctx, "demo", **kw),
        "project status explanation": lambda ctx, **kw: update_project(ctx, "demo", **kw),
        "version description": lambda ctx, **kw: update_version(ctx, 8, **kw),
        "document description": lambda ctx, **kw: update_document(ctx, 5, **kw),
        "news description": lambda ctx, **kw: update_news(ctx, 3, **kw),
    }


TOOL_CALLS = _tool_calls()


class ToolSession(Session):
    async def tool(self, **given: Any) -> Any:
        assert self.client is not None
        return await TOOL_CALLS[self.rig.name](FakeContext(self.client), **given)


@rigs
async def test_a_tool_call_with_the_pair_reaches_the_service_and_writes_the_edit(rig: Rig) -> None:
    async with ToolSession(rig, "Intro.") as session:
        await session.tool(**{f"{rig.param}_append": "More."}, confirm=True)
        await session.tool(
            **{f"{rig.param}_replace": {"old": "Intro", "new": "Start"}},
            confirm=True,
        )

    assert session.written == ["Intro.\n\nMore.", "Start."]


@rigs
async def test_the_tool_strips_the_read_wrapper_from_append_old_and_new(rig: Rig) -> None:
    async with ToolSession(rig, "Stored passage here.") as session:
        await session.tool(
            **{
                f"{rig.param}_replace": {
                    "old": "<user-content>passage</user-content>",
                    "new": "<user-content>section</user-content>",
                }
            },
            confirm=True,
        )
        await session.tool(**{f"{rig.param}_append": "<user-content>Tail.</user-content>"}, confirm=True)

    assert session.written == ["Stored section here.", "Stored passage here.\n\nTail."]


@rigs
async def test_the_tool_rejects_two_inputs_of_one_field_a_blank_append_and_a_malformed_replace_without_a_write(
    rig: Rig,
) -> None:
    async with ToolSession(rig, "x") as session:
        with pytest.raises(ToolInputError, match="cannot be combined"):
            await session.tool(**{rig.param: "a", f"{rig.param}_append": "b"})
        with pytest.raises(ValueError, match=f"{rig.param}_append must not be blank"):
            await session.tool(**{f"{rig.param}_append": "   "})
        with pytest.raises(ValueError, match="exactly the string keys"):
            await session.tool(**{f"{rig.param}_replace": {"old": "x"}})

    assert not session.writes_made


@rigs
async def test_the_tool_accepts_an_empty_new_to_delete_a_passage(rig: Rig) -> None:
    async with ToolSession(rig, "Keep this, drop that.") as session:
        await session.tool(**{f"{rig.param}_replace": {"old": ", drop that", "new": ""}}, confirm=True)

    assert session.written == ["Keep this."]


# --- fields that are checked on their own -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hidden", "edited", "other"),
    [("description", "status_explanation", "Hidden"), ("status_explanation", "description", "Hidden")],
)
async def test_the_hidden_check_of_a_project_text_names_its_own_field(hidden: str, edited: str, other: str) -> None:
    store = Store("Old description.")
    settings = _settings(hidden_fields={"project": (hidden,)})
    client = await started_client(settings, _project_handler("description")(store), [PROJECT])

    await client.update_project(project_ref="demo", **{f"{edited}_append": "More."}, confirm=True)
    with pytest.raises(InvalidInputError, match=f"'{hidden}' is hidden"):
        await client.update_project(project_ref="demo", **{f"{hidden}_replace": {"old": "zz", "new": "y"}})
    await client.aclose()

    assert len(store.bodies) == 1


@rigs
async def test_the_match_and_cut_copy_messages_name_the_fields_own_pair_and_no_other(rig: Rig) -> None:
    async with Session(rig, "The first paragraph of the stored text.\n\nThe rest.") as session:
        with pytest.raises(InvalidInputError) as no_match:
            await session.edit(replace={"old": "absent", "new": "x"})
        with pytest.raises(InvalidInputError) as cut_copy:
            await session.edit(full="The first paragraph of the stored text…")

    other = "status_explanation" if rig.param == "description" else "description"
    for raised in (no_match, cut_copy):
        assert other not in str(raised.value)
        assert "work package" not in str(raised.value)


@rigs
async def test_two_overlapping_matches_make_a_passage_ambiguous(rig: Rig) -> None:
    async with Session(rig, "aaa") as session:
        with pytest.raises(InvalidInputError, match="matches 2 passages"):
            await session.edit(replace={"old": "aa", "new": "b"})


@pytest.mark.parametrize("name", ["project description", "version description"])
async def test_a_rejected_form_preview_carries_no_length_sentence(name: str) -> None:
    rig = next(rig for rig in RIGS if rig.name == name)
    store = Store("Stored.")

    def rejecting(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/form"):
            body = json.loads(request.content)
            errors = {"name": {"message": "Name can't be blank.", "errorIdentifier": "x"}}
            return _json(
                request, {"_type": "Form", "_embedded": {"schema": {}, "payload": body, "validationErrors": errors}}
            )
        return rig.handler(store)(request)

    client = await started_client(_settings(), rejecting, [PROJECT])
    if name == "project description":
        result = await client.update_project(project_ref="demo", description_append="More.", confirm=False)
    else:
        result = await client.version.update(version_id=8, description_append="More.", confirm=False)
    await client.aclose()

    assert result.ready is False
    assert "changes from" not in result.message


async def test_a_comment_without_an_update_link_is_refused_before_the_edit() -> None:
    store = Store("Old.")
    inner = _comment_handler(store)

    def no_link(request: httpx.Request) -> httpx.Response:
        response = inner(request)
        if request.method == "GET" and request.url.path == "/api/v3/activities/77":
            payload = response.json()
            del payload["_links"]["update"]
            return _json(request, payload)
        return response

    client = await started_client(_settings(), no_link, [PROJECT])
    with pytest.raises(OpenProjectPermissionDeniedError, match="does not allow the configured user to edit"):
        await client.work_package.update_comment(
            activity_id=77, comment_replace={"old": "absent", "new": "x"}, confirm=True
        )
    await client.aclose()

    assert store.bodies == []
