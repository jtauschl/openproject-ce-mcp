"""The attributes a rejected write can name (`tools/api-check/error_keys.json`) against the client's error table.

`error_keys.py` reads the pinned OpenProject sources and writes a snapshot of every attribute a contract, model or
service of an entity can add an error for. The client judges a server error by that attribute
(`app/policies/error_fields.py`), so each attribute of the snapshot has to be in the table, or waived here with the
reason; the rest of the snapshot's duties are in the tool's own docstring (its boundary: patterns over Ruby, computed
names listed as `unparsed`, columns that need `db/schema` not found). The snapshot is compared with the sources only
where they are checked out (`op-sources/`, `tools/api-check/fetch-sources.sh`).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import op_sources
import pytest

from openproject_ce_mcp.app.policies.error_fields import ERROR_KEYS, EXTRA_ERROR_KEYS

_PATH = Path(__file__).resolve().parents[1] / "tools" / "api-check" / "error_keys.py"
_spec = importlib.util.spec_from_file_location("error_keys", _PATH)
ek = importlib.util.module_from_spec(_spec)
sys.modules["error_keys"] = ek
_spec.loader.exec_module(ek)

SNAPSHOT = json.loads(ek.SNAPSHOT.read_text())

_NO_FIELD = (
    "no field of this entity the hide settings can name: judged as an unknown attribute, hidden while any hide "
    "setting is active (fail closed)"
)
# (entity, attribute) -> why the table does not list it.
WAIVED: dict[tuple[str, str], str] = {
    **{
        (entity, key): _NO_FIELD
        for entity, keys in {
            "work_package": ["budget", "journalInternal", "journalNotes", "observedInVersions"],
            "project": [
                "LimitCustomFieldsValidationToSection",
                "availablePhases",
                "enabledModules",
                "projectCreationWizardAssigneeCustomField",
                "projectCreationWizardNotificationText",
                "projectCreationWizardStatusWhenSubmitted",
                "projectCreationWizardWorkPackageComment",
                "projectCreationWizardWorkPackageType",
                "repository",
                "settings",
                "template",
                "templated",
                "types",
                "wiki",
                "workspaceType",
            ],
            "user": [
                "authSource",
                "currentPassword",
                "forcePasswordChange",
                "ldapAuthSource",
                "notificationSettings",
                "password",
                "type",
            ],
            "version": ["wikiPageTitle"],
            "membership": ["entityType"],
            "time_entry": ["entityType", "tmonth", "tweek", "tyear"],
            "meeting": ["uid"],
            "grid": ["name", "options", "project", "type", "user", "widgets"],
            "board": [
                "displayRepresentation",
                "displaySums",
                "orderedWorkPackages",
                "orders",
                "selects",
                "timelineLabels",
            ],
            "relation": ["lag"],
        }.items()
        for key in keys
    },
}
# entity -> why the count of `errors.add` with a computed name is accepted.
UNPARSED_WAIVER = {
    "work_package": "the contract copies model errors (`base_contract.rb`) and marks every changed attribute read-only",
    "project": "the contract copies model errors of the custom field and the wizard sections",
    "grid": "the widget contract adds errors for the widget's own options",
}
# Message templates (`model.attributes.attribute.key`) of the entities' models that interpolate a value, and why the
# attribute-keyed judgement is enough. A template of another model has no write tool of this server.
QUOTING: dict[str, str] = {
    "project.attributes.enabled_modules.dependency_missing": "names a module, not a field: an unknown attribute, fail closed",
    "project.attributes.enabled_modules.format": "names a module, not a field: an unknown attribute, fail closed",
    "project.attributes.types.in_use_by_work_packages": "names a type in use: an unknown attribute, fail closed",
    "query.attributes.column_names.format": "quotes the caller's own column: an unknown attribute, fail closed",
    "query.attributes.column_names.invalid": "quotes the caller's own column: an unknown attribute, fail closed",
    "query.attributes.group_by.format": "quotes the caller's own group: an unknown attribute, fail closed",
    "query.attributes.group_by.invalid": "quotes the caller's own group: an unknown attribute, fail closed",
    "query.attributes.selects.format": "quotes the caller's own select: an unknown attribute, fail closed",
    "query.attributes.selects.nonexistent": "quotes the caller's own select: an unknown attribute, fail closed",
    "query.attributes.sort_criteria.format": "quotes the caller's own sort: an unknown attribute, fail closed",
    "query.attributes.sort_criteria.invalid": "quotes the caller's own sort: an unknown attribute, fail closed",
    "query.attributes.timestamps.forbidden": "quotes the caller's own timestamp: an unknown attribute, fail closed",
    "query.attributes.timestamps.format": "quotes the caller's own timestamp: an unknown attribute, fail closed",
    "query.attributes.timestamps.invalid": "quotes the caller's own timestamp: an unknown attribute, fail closed",
    "query.group_by_hierarchies_exclusive": "names no field value: an attribute-less error, fail closed",
    "relation.attributes.from_id.format": "quotes the caller's own id: judged by `from`, the relation ends",
    "relation.attributes.to_id.format": "quotes the caller's own id: an unknown attribute, fail closed",
    "user.attributes.password.requirements_not_met": "names rules, not a value of a field",
    "user.attributes.password.weak": "names rules, not a value of a field",
    "user.attributes.password_confirmation.format": "names the password field: an unknown attribute, fail closed",
    "work_package.attributes.assigned_to.format": "wraps the assignee error: judged by `assignee`",
    "work_package.attributes.id.format": "quotes the caller's own id: an unknown attribute, fail closed",
    "work_package.attributes.identifier.must_not_be_changed": "names no value: an unknown attribute, fail closed",
    "work_package.attributes.sequence_number.must_not_be_changed": "names no value: an unknown attribute, fail closed",
    "work_package.attributes.start_date.violates_relationships": (
        "quotes the soonest start the predecessors allow, on `startDate` and `dueDate`: judged by both date fields through `QUOTES`"
    ),
    "work_package.is_not_a_valid_target_for_time_entries": (
        "a `base` error of the work package that quotes the caller's own reassign id: judged by `base`"
    ),
}
IN_SCOPE_MODELS = (
    "project.",
    "query.",
    "relation.",
    "user.",
    "work_package.",
    "member.",
    "version.",
    "time_entry.",
    "meeting.",
    "grid.",
)


def test_every_attribute_of_the_snapshot_is_in_the_table_or_waived() -> None:
    missing = [
        (entity, key)
        for entity, keys in SNAPSHOT["keys"].items()
        for key in keys
        if key != "base" and key not in ERROR_KEYS.get(entity, {}) and (entity, key) not in WAIVED
    ]

    assert missing == []


def test_no_waiver_is_stale_and_every_extra_attribute_exists_in_the_sources() -> None:
    present = {(entity, key) for entity, keys in SNAPSHOT["keys"].items() for key in keys}

    assert set(WAIVED) - present == set(), "a waiver for an attribute the sources no longer have"
    assert {(entity, key) for entity in EXTRA_ERROR_KEYS for key in EXTRA_ERROR_KEYS[entity]} - present - {
        ("work_package", "assignee"),
        ("work_package", "responsible"),
        ("work_package", "estimatedTime"),
        ("work_package", "remainingTime"),
        ("work_package", "targetVersions"),
        ("work_package", "derivedEstimatedTime"),
        ("work_package", "derivedRemainingTime"),
        ("time_entry", "workPackage"),
        ("time_entry", "entity"),
        ("membership", "principal"),
        ("project", "statusCode"),
    } == set(), "an extra attribute the sources do not know"


def test_the_computed_error_names_are_accounted_for() -> None:
    computed = {entity for entity, versions in SNAPSHOT["unparsed"].items() if any(versions.values())}

    assert computed == set(UNPARSED_WAIVER)
    assert all(UNPARSED_WAIVER.values())


def test_every_message_template_that_quotes_a_value_has_a_reason() -> None:
    templates = {name for name in SNAPSHOT["quoting_templates"] if name.startswith(IN_SCOPE_MODELS)}

    assert templates - set(QUOTING) == set(), "a template that quotes a value and has no reason"
    assert set(QUOTING) - templates == set(), "a reason for a template the sources no longer have"


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("status_id", "status"),
        ("custom_field_5", "customField5"),
        ("cf_5", "customField5"),
        ("start_date", "startDate"),
        ("done_ratio", "percentageDone"),
        ("estimated_hours", "estimatedTime"),
        ("assigned_to", "assignee"),
        ("firstname", "firstName"),
        ("identity_url", "identityUrl"),
        ("o_auth_token", "oAuthToken"),
    ],
)
def test_the_port_of_from_ar_name_converts_like_the_server(attribute: str, expected: str) -> None:
    conversions = {
        "done_ratio": "percentageDone",
        "estimated_hours": "estimatedTime",
        "assigned_to": "assignee",
        "firstname": "firstName",
    }

    assert ek.from_ar_name(attribute, conversions=conversions, acronyms={}) == expected


def test_the_acronyms_of_the_inflections_are_kept() -> None:
    assert ek.from_ar_name("some_api_key", conversions={}, acronyms={"api": "API"}) == "someAPIKey"


def test_the_extractor_reads_the_three_forms_and_lists_a_computed_name() -> None:
    text = (
        "attribute :subject\n"
        "validates :name, :identifier, presence: true\n"
        "errors.add :base, :readonly_status\n"
        'errors.add("start_date", :taken)\n'
        "errors.add attribute, :invalid\n"
        "# errors.add :commented, :out\n"
    )

    found, computed = ek.extract(text)

    assert found == {"subject", "name", "identifier", "base", "start_date"}
    assert computed == [5]


needs_sources = pytest.mark.skipif(
    bool(op_sources.checkout_problems(dict(SNAPSHOT["pins"]), op_sources.SOURCES)),
    reason="the snapshot's source checkouts are not under op-sources/",
)


@needs_sources
def test_the_snapshot_is_what_the_sources_say() -> None:
    assert ek.build(SNAPSHOT["pins"]) == SNAPSHOT
