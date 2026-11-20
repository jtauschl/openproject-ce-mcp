"""Every service that creates something through the server is classified for context-derived defaults.

A new create service fails this test until it is classified, so the question "does the server fill an
attribute the caller left out from a related resource" is asked once per create tool, not forgotten.
The class: a create commits a value the server derived from a related resource (the parent of a work
package) and not a value the caller passed. The fix for the work package is
`_validate_create_under_a_parent`; the table records what was measured for the others (form endpoints of
op.nutrilytics.de, probed with and without the related resource, nothing written).

- handled: the create flow validates without the related resource and adds the link afterwards.
- none observed: the form payload with and without the related resource differs by the link only.
- by design: the tool takes its values from the related resource (a time entry's project from its work package).
- not probed: the create body names no related resource but the project it lives in; the form was not compared.
- no form call: the service sends the caller's values, so a derivation by the server is not visible to it and
  this method cannot remove one.

The scan reads calls and references on `self._api` of the service modules.
"""

from __future__ import annotations

import ast

import pytest
from _source_scan import SERVICES

CREATE_CALLS = frozenset(
    {"create", "commit_create", "create_form", "validate_create", "copy_form", "commit_copy", "init_occurrence"}
)

CLASSIFICATION = {
    "work_package_service.py": "handled",
    "project_service.py": "none observed (parent project; the copy takes its values from the source by design)",
    "version_service.py": "none observed (defining project)",
    "membership_service.py": "none observed (principal)",
    "meeting_service.py": "none observed (project)",
    "time_entry_service.py": "by design (project and entity come from the work package)",
    "board_service.py": "not probed (project only)",
    "grid_service.py": "not probed (scope only)",
    "user_service.py": "not probed (no related resource)",
    "recurring_meeting_service.py": "by design (an occurrence takes agenda and attachments from the series template)",
    "group_service.py": "no form call",
    "news_service.py": "no form call",
    "storage_service.py": "no form call",
    "attachment_service.py": "no form call",
    "meeting_agenda_item_service.py": "no form call",
    "meeting_outcome_service.py": "no form call",
    "meeting_section_service.py": "no form call",
    "relation_service.py": "no form call",
    "reminder_service.py": "no form call",
    "user_non_working_time_service.py": "no form call",
    "user_working_hours_service.py": "no form call",
    "wiki_page_link_service.py": "no form call",
}


def _services_that_create() -> set[str]:
    found = set()
    for path in sorted(SERVICES.glob("*.py")):
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.Attribute)
            and node.attr in CREATE_CALLS
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "_api"
            for node in ast.walk(tree)
        ):
            found.add(path.name)
    return found


def test_every_service_that_creates_is_classified_and_no_classified_service_is_gone() -> None:
    assert _services_that_create() == set(CLASSIFICATION)


@pytest.mark.parametrize("service", sorted(name for name, kind in CLASSIFICATION.items() if kind.startswith("handled")))
def test_a_handled_service_validates_through_the_parent_flow(service: str) -> None:
    source = (SERVICES / service).read_text()

    assert source.count("_validate_create_under_a_parent(") >= 2
    assert "validate_create(project_id, body)" in source


def test_the_work_package_service_has_no_other_commit_of_a_create() -> None:
    """A second commit site of a create would skip the flow: both creates commit through `_commit_create`."""
    tree = ast.parse((SERVICES / "work_package_service.py").read_text())
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "commit_create"
    ]

    assert len(sites) == 1
