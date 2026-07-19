from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_CHECK_PATH = Path(__file__).resolve().parents[1] / "tools" / "api-check" / "check_field_completeness.py"
_spec = importlib.util.spec_from_file_location("check_field_completeness", _CHECK_PATH)
cfc = importlib.util.module_from_spec(_spec)
sys.modules["check_field_completeness"] = cfc
_spec.loader.exec_module(cfc)


# --- extractor unit tests -----------------------------------------------


def test_continuation_line_as_symbol_form():
    text = "        property :display_id,\n                 as: :displayId,\n                 render_nil: true,\n"
    fields = cfc._extract_macro_fields(text)
    assert fields == [cfc.RawField(macro="property", ruby_symbol="display_id", wire_name="displayId")]


def test_continuation_line_as_string_form():
    text = (
        "        date_property :effective_date,\n"
        '                      as: "endDate",\n'
        "                      writable: true\n"
    )
    fields = cfc._extract_macro_fields(text)
    assert fields == [cfc.RawField(macro="date_property", ruby_symbol="effective_date", wire_name="endDate")]


def test_inline_as_on_arg_less_associated_project():
    text = "        associated_project as: :definingProject\n"
    fields = cfc._extract_macro_fields(text)
    assert fields == [cfc.RawField(macro="associated_project", ruby_symbol="project", wire_name="definingProject")]


def test_bare_associated_project_defaults_symbol_and_wire_to_project():
    text = "        associated_project\n\n        property :id\n"
    fields = cfc._extract_macro_fields(text)
    assert cfc.RawField(macro="associated_project", ruby_symbol="project", wire_name="project") in fields


def test_associated_project_with_explicit_positional_symbol():
    # project_representer.rb:178 -- `associated_project :parent`, a project's
    # own parent-project relation, distinct from the bare/as: forms above.
    text = "        associated_project :parent\n"
    fields = cfc._extract_macro_fields(text)
    assert fields == [cfc.RawField(macro="associated_project", ruby_symbol="parent", wire_name="parent")]


def test_no_as_falls_back_to_camelize():
    text = "        property :done_ratio,\n                 render_nil: true\n"
    fields = cfc._extract_macro_fields(text)
    assert fields == [cfc.RawField(macro="property", ruby_symbol="done_ratio", wire_name="doneRatio")]


def test_formattable_property_counts_as_one_field():
    text = "        formattable_property :description\n"
    fields = cfc._extract_macro_fields(text)
    assert fields == [cfc.RawField(macro="formattable_property", ruby_symbol="description", wire_name="description")]
    assert not any(f.wire_name in ("format", "raw", "html") for f in fields)


def test_plural_associated_resources_macro_is_matched_distinctly():
    # membership_representer.rb:75 -- easy to miss if only the singular
    # `associated_resource` is matched.
    text = "        associated_resources :roles,\n                              readable: true\n"
    fields = cfc._extract_macro_fields(text)
    assert fields == [cfc.RawField(macro="associated_resources", ruby_symbol="roles", wire_name="roles")]


def test_data_bearing_link_is_extracted_and_not_confused_with_navigation():
    text = "        link :defaultAssignee do\n          next unless represented.assigned_to\n        end\n"
    fields = cfc._extract_macro_fields(text)
    assert fields == [cfc.RawField(macro="link", ruby_symbol="defaultAssignee", wire_name="defaultAssignee")]


def test_pure_navigation_link_is_suppressed_entirely():
    text = "        link :update,\n             cache_if: -> { true }\n"
    fields = cfc._extract_macro_fields(text)
    assert fields == []


def test_camelize():
    assert cfc._camelize("done_ratio") == "doneRatio"
    assert cfc._camelize("id") == "id"
    assert cfc._camelize("derived_start_date") == "derivedStartDate"
    assert cfc._camelize("_meta") == "_meta"


def test_same_wire_name_collision_prefers_data_macro_over_link():
    # work_package_representer.rb has both `link :relations do ... end` and
    # `property :relations, ...` for the same wire name.
    text = (
        "        link :relations do\n"
        "          nil\n"
        "        end\n\n"
        "        property :relations,\n"
        "                 embedded: true\n"
    )
    fields = cfc._extract_macro_fields(text)
    matching = [f for f in cfc._dedup(fields) if f.wire_name == "relations"]
    assert len(matching) == 1
    assert matching[0].macro == "property"


# --- build_findings diff logic -------------------------------------------


@dataclasses.dataclass
class _StubModel:
    a: str
    b: str | None = None


@dataclasses.dataclass
class _StubModelCoveringOnlyA:
    a: str


def test_findings_classify_covered_excluded_untriaged():
    rc = cfc.ResourceCheck(name="widget", source_files=(), model_types=("_StubModel",))
    text = "        property :a\n        property :c\n        link :self do\n        end\n"
    stub_module = SimpleNamespace(_StubModel=_StubModel)

    # temporarily register an exclusion for "c" via monkeypatch-free direct call
    findings = cfc._findings_for_resource(rc, [text], model_module=stub_module)

    by_wire = {f.wire_name: f for f in findings}
    assert by_wire["a"].status == "COVERED"
    assert by_wire["c"].status == "UNTRIAGED"
    assert "self" not in by_wire  # pure navigation link, never a finding at all


def test_multi_file_source_union():
    rc = cfc.ResourceCheck(name="widget", source_files=(), model_types=("_StubModelCoveringOnlyA",))
    stub_module = SimpleNamespace(_StubModelCoveringOnlyA=_StubModelCoveringOnlyA)
    text_a = "        property :a\n"
    text_b = "        property :b\n"

    findings = cfc._findings_for_resource(rc, [text_a, text_b], model_module=stub_module)

    by_wire = {f.wire_name: f for f in findings}
    assert by_wire["a"].status == "COVERED"
    assert by_wire["b"].status == "UNTRIAGED"


def test_work_package_date_field_is_untriaged_against_the_real_model():
    # Regression guard for the tool's demonstration finding: milestone-only
    # `date_property :date` (work_package_representer.rb:380) has no
    # corresponding field on the real WorkPackageSummary/WorkPackageDetail.
    from openproject_ce_mcp import models

    rc = cfc.ResourceCheck(
        name="work_package", source_files=(), model_types=("WorkPackageSummary", "WorkPackageDetail")
    )
    text = "        date_property :date,\n                      getter: ->(*) {}\n"

    findings = cfc._findings_for_resource(rc, [text], model_module=models)

    assert len(findings) == 1
    assert findings[0].wire_name == "date"
    assert findings[0].status == "UNTRIAGED"


# --- exit-code policy -----------------------------------------------------


def test_exit_code_zero_when_all_covered_or_excluded(tmp_path, monkeypatch):
    findings = [
        cfc.Finding("widget", "a", "a", "property", "COVERED", None, None),
        cfc.Finding("widget", "b", "b", "property", "EXCLUDED", "internal_other", "reason"),
    ]
    (tmp_path / cfc.SOURCE_VERSION).mkdir()
    monkeypatch.setattr(cfc, "SOURCES", tmp_path)
    monkeypatch.setattr(cfc, "build_findings", lambda: findings)
    monkeypatch.setattr(sys, "argv", ["check_field_completeness.py"])

    assert cfc.main() == 0


def test_exit_code_one_when_untriaged_present(tmp_path, monkeypatch):
    findings = [cfc.Finding("widget", "a", "a", "property", "UNTRIAGED", None, None)]
    (tmp_path / cfc.SOURCE_VERSION).mkdir()
    monkeypatch.setattr(cfc, "SOURCES", tmp_path)
    monkeypatch.setattr(cfc, "build_findings", lambda: findings)
    monkeypatch.setattr(sys, "argv", ["check_field_completeness.py"])

    assert cfc.main() == 1


def test_exit_code_two_when_sources_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfc, "SOURCES", tmp_path / "does-not-exist")
    monkeypatch.setattr(sys, "argv", ["check_field_completeness.py"])
    write_target = tmp_path / "FIELD_COMPLETENESS.md"
    monkeypatch.setattr(cfc, "FIELD_COMPLETENESS_MD", write_target)

    result = cfc.main()

    assert result == 2
    assert "missing source clone" in capsys.readouterr().err
    assert not write_target.exists()


def test_exit_code_two_with_write_flag_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(cfc, "SOURCES", tmp_path / "does-not-exist")
    write_target = tmp_path / "FIELD_COMPLETENESS.md"
    monkeypatch.setattr(cfc, "FIELD_COMPLETENESS_MD", write_target)
    monkeypatch.setattr(sys, "argv", ["check_field_completeness.py", "--write"])

    assert cfc.main() == 2
    assert not write_target.exists()


def test_exit_code_two_when_a_single_curated_source_file_is_missing(tmp_path, monkeypatch, capsys):
    # .op-sources/<version>/ itself exists (unlike the two tests above), but
    # one specific ResourceCheck.source_files entry doesn't -- an incomplete
    # sparse checkout or a stale source_files entry, not "no sources at all".
    # This used to escape as an uncaught RuntimeError/traceback defaulting to
    # exit 1, indistinguishable from the documented "real UNTRIAGED findings"
    # exit 1 -- caught in review.
    (tmp_path / cfc.SOURCE_VERSION).mkdir()
    monkeypatch.setattr(cfc, "SOURCES", tmp_path)
    monkeypatch.setattr(
        cfc,
        "RESOURCE_CHECKS",
        [cfc.ResourceCheck(name="widget", source_files=("does/not/exist.rb",), model_types=())],
    )
    write_target = tmp_path / "FIELD_COMPLETENESS.md"
    monkeypatch.setattr(cfc, "FIELD_COMPLETENESS_MD", write_target)
    monkeypatch.setattr(sys, "argv", ["check_field_completeness.py", "--write"])

    result = cfc.main()

    assert result == 2
    stderr = capsys.readouterr().err
    assert "source_files entry missing" in stderr
    assert "widget" in stderr
    assert not write_target.exists()


# --- exclusion table hygiene -----------------------------------------------


def test_every_exclusion_has_a_non_empty_reason():
    for exclusion in cfc.EXCLUSIONS:
        assert exclusion.reason.strip(), exclusion


# --- --write renderer -------------------------------------------------------


def test_write_renderer_includes_untriaged_and_exclusions_sections(monkeypatch):
    # render_exclusions_section() renders the module's own curated EXCLUSIONS
    # table (not the findings passed in) -- that table is the actual
    # machine-readable/maintained exclusion record the acceptance criteria
    # ask for, so this monkeypatches it directly to keep the test isolated
    # from the real table's current content.
    monkeypatch.setattr(
        cfc,
        "EXCLUSIONS",
        [cfc.FieldExclusion("widget", "b", cfc.ExclusionCategory.INTERNAL_OTHER, "some reason")],
    )
    findings = [
        cfc.Finding("widget", "a", "a", "property", "UNTRIAGED", None, None),
        cfc.Finding("widget", "b", "b", "property", "EXCLUDED", "internal_other", "some reason"),
    ]

    body = cfc.render_report(findings)

    assert "## Untriaged drift" in body
    assert "widget.a" in body
    assert "## Intentional exclusions" in body
    assert "widget.b" in body
    assert "some reason" in body


def test_write_renderer_reports_clean_when_nothing_untriaged():
    findings = [cfc.Finding("widget", "a", "a", "property", "COVERED", None, None)]

    section = cfc.render_untriaged_section(findings)

    assert "None" in section
