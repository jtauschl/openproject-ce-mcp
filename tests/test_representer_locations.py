"""`representer_locations` finds where an OpenProject representer renders each name.

Fixture snippets pin one DSL form each; the real-file assertions and the golden comparison need the pinned OpenProject
checkouts and are skipped without them (they are not available in CI).
"""

from __future__ import annotations

import re

import check_field_completeness
import pytest
from op_sources import SOURCES, checkout_problems, pinned_versions
from representer_locations import (
    EMBEDDED,
    LINK,
    LINK_MEMBER,
    PROPERTY,
    UNREADABLE_MEMBERS,
    VALUE_MEMBER,
    Entry,
    camelize,
    extract_declarations,
    extract_extensions,
    patch_file,
    read_acronyms,
    representer_path,
    unparsed,
)
from representer_locations import entries as entries_of


def entries(text: str) -> set[tuple[str, str]]:
    return {(e.location, e.wire_name) for e in entries_of(extract_declarations(text))}


def test_a_property_is_a_property_and_a_formattable_property_has_value_members() -> None:
    found = entries("property :done_ratio, as: :percentageDone\nformattable_property :description\n")

    assert (PROPERTY, "percentageDone") in found
    assert {(VALUE_MEMBER + "description", member) for member in ("format", "raw", "html")} <= found


def test_date_and_duration_properties_are_properties() -> None:
    found = entries("date_time_property :created_at\nduration_property :estimated_time\ndate_property :due_date\n")

    assert found == {(PROPERTY, "createdAt"), (PROPERTY, "estimatedTime"), (PROPERTY, "dueDate")}


def test_embedded_true_embeds_the_property_and_the_next_macro_does_not_inherit_it() -> None:
    text = (
        "property :details,\n"
        "         exec_context: :decorator,\n"
        "         embedded: true\n"
        "\n"
        "property :created_at\n"
        "property :updated_at\n"
    )
    found = entries(text)

    assert (EMBEDDED, "details") in found and (PROPERTY, "details") not in found
    assert (EMBEDDED, "createdAt") not in found and (EMBEDDED, "updatedAt") not in found


def test_the_continuation_stops_at_the_next_macro_even_without_a_blank_line() -> None:
    text = "property :a,\n         getter: 1\n  property :b, embedded: true\n"

    assert (EMBEDDED, "a") not in entries(text)


def test_an_associated_resource_renders_a_link_and_an_embedded_resource() -> None:
    found = entries("associated_resource :priority\nassociated_resources :roles\nresource :type\n")

    assert {(LINK, "priority"), (EMBEDDED, "priority"), (LINK, "roles"), (EMBEDDED, "roles"), (LINK, "type")} <= found


def test_associated_project_defaults_to_the_project_and_honours_as() -> None:
    found = entries("associated_project\nassociated_project as: :definingProject\n")

    assert {(LINK, "project"), (LINK, "definingProject")} <= found


def test_a_polymorphic_resource_and_the_plural_visible_resources_are_links() -> None:
    found = entries("polymorphic_resource :resource\nassociated_visible_resources :children\n")

    assert {(LINK, "resource"), (EMBEDDED, "resource"), (LINK, "children")} <= found


def test_a_link_block_names_its_members() -> None:
    text = (
        "link :update do\n  {\n    href: api_v3_paths.work_package_form(represented.id),\n    method: :post\n  }\nend\n"
    )

    assert {(LINK, "update"), (LINK_MEMBER + "update", "href"), (LINK_MEMBER + "update", "method")} <= entries(text)


def test_a_links_block_with_a_display_id_member() -> None:
    text = (
        "links :children,\n"
        "      uncacheable: true do\n"
        "  represented.children.map do |child|\n"
        "    {\n"
        "      href: x,\n"
        "      title: child.subject,\n"
        "      displayId: child.display_id.to_s\n"
        "    }\n"
        "  end\n"
        "end\n"
    )

    assert (LINK_MEMBER + "children", "displayId") in entries(text)


def test_a_custom_link_lambda_of_an_associated_resource_names_its_members() -> None:
    text = (
        "associated_resource :parent,\n"
        "                    v3_path: :work_package,\n"
        "                    link: ->(*) {\n"
        "                      { href: x, title: y, displayId: z }\n"
        "                    },\n"
        "                    uncacheable_link: true\n"
    )

    assert (LINK_MEMBER + "parent", "displayId") in entries(text)


def test_self_link_is_the_self_link_with_href_and_title_unless_title_is_false() -> None:
    assert {(LINK, "self"), (LINK_MEMBER + "self", "href"), (LINK_MEMBER + "self", "title")} <= entries("self_link\n")
    assert (LINK_MEMBER + "self", "title") not in entries("self_link title: false\n")


def test_a_self_link_keyword_argument_is_no_macro() -> None:
    assert entries("    foo(x,\n        self_link: api_v3_paths.thing(1))\n") == set()


def test_link_without_resource_is_a_link() -> None:
    assert (LINK, "origin") in entries(
        "link_without_resource :origin,\n                      getter: 1,\n                      setter: 2\n"
    )


def test_a_collection_is_embedded_only_when_it_says_so() -> None:
    assert (EMBEDDED, "elements") in entries("collection :elements,\n           embedded: true\n")
    assert (PROPERTY, "groups") in entries("collection :groups,\n           render_nil: false\n")


def test_def_type_is_the_type_property() -> None:
    assert (PROPERTY, "_type") in entries("def _type\n  'Thing'\nend\n")


def test_a_leading_underscore_is_kept() -> None:
    assert (PROPERTY, "_meta") in entries("property :_meta\n")


def test_a_condition_naming_the_enterprise_token_marks_the_property() -> None:
    text = "property :readonly,\n         if: ->(*) { ::Status.can_readonly? }\nproperty :plain\n"
    by_wire = {e.wire_name: e for e in entries_of(extract_declarations(text))}

    assert by_wire["readonly"] == Entry(PROPERTY, "readonly", True)
    assert by_wire["plain"].enterprise is False


def test_the_sql_representer_forms_are_macros_of_the_same_dsl() -> None:
    text = (
        "link :self,\n"
        "     path: :user,\n"
        "     column: -> { 'id' }\n"
        "property :id, column: :id\n"
        "property :email, column: :mail, render_if: ->(*) { 'TRUE' }\n"
    )

    assert {(LINK, "self"), (PROPERTY, "id"), (PROPERTY, "email")} <= entries(text)


def test_a_block_less_link_does_not_take_the_block_of_the_next_link() -> None:
    text = "self_link\n\nlink :showUser do\n  { href: x, type: 'text/html' }\nend\n"
    found = entries(text)

    assert (LINK_MEMBER + "self", "type") not in found
    assert (LINK_MEMBER + "showUser", "type") in found


def test_an_embedded_option_after_a_multi_line_getter_is_found() -> None:
    text = (
        "collection :elements,\n"
        "           getter: ->(*) {\n"
        "             represented.map do |model|\n"
        "               build(model)\n"
        "             end\n"
        "           },\n"
        "           exec_context: :decorator,\n"
        "           embedded: true\n"
    )

    assert entries(text) == {(EMBEDDED, "elements")}


def test_a_link_lambda_with_a_blank_line_and_an_inner_end_still_names_its_members() -> None:
    text = (
        "associated_resource :section,\n"
        "                    link: ->(*) {\n"
        "                      if represented.section\n"
        "\n"
        "                        { href: path, title: name, displayId: shown }\n"
        "                      end\n"
        "                    },\n"
        "                    uncacheable_link: true\n"
    )

    assert (LINK_MEMBER + "section", "displayId") in entries(text)


def test_call_keywords_are_no_link_members() -> None:
    text = (
        "link :pdf do\n"
        "  {\n"
        "    href: work_package_path(id: represented.id, format: :pdf),\n"
        "    title: 'PDF'\n"
        "  }\n"
        "end\n"
    )
    found = entries(text)

    assert {(LINK_MEMBER + "pdf", "href"), (LINK_MEMBER + "pdf", "title")} <= found
    assert not {member for location, member in found if location == LINK_MEMBER + "pdf"} & {"id", "format"}


def test_templated_and_payload_members_are_link_members() -> None:
    text = "link :addWatcher do\n  { href: h, method: :post, payload: { user: u }, templated: true }\nend\n"
    members = {member for location, member in entries(text) if location == LINK_MEMBER + "addWatcher"}

    assert members == {"href", "method", "payload", "templated"}


def test_a_bare_link_keeps_its_rel_as_given_and_a_resource_macro_camelizes() -> None:
    found = entries("link :auth_source do\n  { href: x }\nend\nassociated_resource :default_assignee\n")

    assert (LINK, "auth_source") in found and (LINK, "authSource") not in found
    assert (LINK, "defaultAssignee") in found


def test_a_rel_option_names_a_bare_link() -> None:
    assert (LINK, "readIAN") in entries("link rel: :readIAN do\n  { href: x }\nend\n")


def test_an_embedded_property_is_embedded_only_and_a_resource_can_opt_out_of_embedding() -> None:
    found = entries("property :details, embedded: true\nresource :scope, embedded: false\nassociated_resource :user\n")

    assert (EMBEDDED, "details") in found and (PROPERTY, "details") not in found
    assert (LINK, "scope") in found and (EMBEDDED, "scope") not in found
    assert (EMBEDDED, "user") in found


def test_schema_macros_declare_properties() -> None:
    text = (
        "schema :subject, type: 'String'\n"
        "schema_with_allowed_link :project, type: 'Project'\n"
        "schema_with_allowed_collection :versions\n"
        "schema_with_allowed_string_collection :tags\n"
        "schema_property :filters, getter: x\n"
    )

    assert entries(text) == {(PROPERTY, name) for name in ("subject", "project", "versions", "tags", "filters")}


def test_resource_link_is_a_link_without_an_embedded_resource() -> None:
    found = entries("resource_link :scope,\n              getter: x,\n              setter: y\n")

    assert found == {(LINK, "scope"), (LINK_MEMBER + "scope", UNREADABLE_MEMBERS)}


def test_associated_user_link_and_the_embedded_macro_and_the_custom_field_injector() -> None:
    found = entries("associated_user_link :author\nembedded :elements, getter: x\ncustom_field_injector type: :x\n")

    assert {(LINK, "author"), (EMBEDDED, "elements"), (PROPERTY, "customField*"), (LINK, "customField*")} <= found


def test_a_multi_line_condition_naming_the_enterprise_token_is_seen() -> None:
    text = (
        "property :readonly,\n"
        "         if: ->(*) {\n"
        "           ::EnterpriseToken.allows_to?(:thing) &&\n"
        "             represented.flag\n"
        "         },\n"
        "         getter: x\n"
        "property :other,\n"
        "         show_if: ->(*) { true }\n"
    )
    by_wire = {e.wire_name: e for e in entries_of(extract_declarations(text))}

    assert by_wire["readonly"].enterprise is True
    assert by_wire["other"].enterprise is False


def test_every_condition_key_is_read() -> None:
    text = "property :a, show_if: ->(*) { EnterpriseToken.x }\nproperty :b, skip_render: ->(*) { EnterpriseToken.x }\n"

    assert all(e.enterprise for e in entries_of(extract_declarations(text)))


def test_a_long_statement_keeps_its_trailing_options_and_members() -> None:
    body = "".join(f"                    # line {n}\n" for n in range(30))
    text = f"associated_resource :parent,\n{body}                    link: ->(*) {{ {{ href: h, displayId: d }} }}\n"

    assert (LINK_MEMBER + "parent", "displayId") in entries(text)


def test_a_statement_stops_at_the_def_or_end_that_closes_its_scope() -> None:
    text = "property :a,\n         getter: 1\nend\nproperty :b, embedded: true\n"

    assert (EMBEDDED, "a") not in entries(text) and (EMBEDDED, "b") in entries(text)


def test_a_computed_name_is_reported_as_unparsed_and_a_literal_one_is_not() -> None:
    text = 'property setting,\n         getter: 1\nproperty :"copy_#{identifier}"\nproperty :id\nlink = 3\nproperty.x\n'

    assert unparsed(text) == ["property setting,", 'property :"copy_#{identifier}"']


def test_an_acronym_decides_how_a_name_is_camelized() -> None:
    acronyms = read_acronyms('inflect.acronym "API"\n  inflect.acronym "OAuth"\n')

    assert acronyms == {"api": "API", "oauth": "OAuth"}
    assert camelize("maximum_api_v3_page_size", acronyms) == "maximumAPIV3PageSize"
    assert camelize("maximum_api_v3_page_size") == "maximumApiV3PageSize"
    assert (PROPERTY, "maximumAPIV3PageSize") in {
        (e.location, e.wire_name)
        for e in entries_of(extract_declarations("property :maximum_api_v3_page_size\n", acronyms))
    }


def test_a_local_variable_named_like_a_macro_is_no_declaration_and_cuts_no_statement() -> None:
    text = (
        "collection :elements,\n"
        "           getter: ->(*) {\n"
        "             self_link = model_self_link(model)\n"
        "             links = []\n"
        "             link = LinkObject.new(x)\n"
        "             foo(self_link)\n"
        "           },\n"
        "           embedded: true\n"
    )

    assert entries(text) == {(EMBEDDED, "elements")}


def test_a_bare_self_link_inside_a_method_body_is_no_declaration() -> None:
    text = "self_link title: false\n\ndef self_v3_path\n  self_link\nend\n"

    assert (LINK_MEMBER + "self", "title") not in entries(text)


def test_string_contents_are_no_link_members() -> None:
    text = (
        "link :status do\n"
        "  { href: \"#{PREFIX}sprints:status:#{id}\", title: 'x' }\n"
        "end\n"
        "link :other do\n"
        '  { href: "{ href: 1, phantom: true }" }\n'
        "end\n"
    )
    found = entries(text)

    assert {(LINK_MEMBER + "status", "href"), (LINK_MEMBER + "status", "title")} <= found
    assert not {member for _, member in found} & {"sprints", "phantom"}


def test_a_setter_hash_of_a_resource_macro_adds_no_link_member() -> None:
    text = (
        "associated_resource :parent,\n"
        "                    link: ->(*) { { href: h, title: t } },\n"
        "                    setter: ->(fragment:, **) { { href: x, phantom: true } }\n"
    )
    members = {member for location, member in entries(text) if location == LINK_MEMBER + "parent"}

    assert members == {"href", "title"}


def test_a_resource_that_opts_out_of_embedding_also_renders_a_top_level_property() -> None:
    found = entries("resources :values,\n          embedded: false\n")

    assert {(LINK, "values"), (PROPERTY, "values")} <= found and (EMBEDDED, "values") not in found


def _unreadable(text: str) -> set[str]:
    return {
        e.location.removeprefix(LINK_MEMBER)
        for e in entries_of(extract_declarations(text))
        if e.location.startswith(LINK_MEMBER) and e.wire_name == UNREADABLE_MEMBERS
    }


def test_a_link_object_built_by_a_helper_or_a_factory_is_marked_unreadable() -> None:
    assert _unreadable("link :a do\n  build_link(x)\nend\n") == {"a"}
    assert _unreadable("resource_link :scope, getter: g, setter: s\n") == {"scope"}
    assert _unreadable("associated_resource :remindable,\n                    link: associated_remindable_link\n") == {
        "remindable"
    }
    assert _unreadable("link :b do\n  { href: h }\nend\n") == set()


def test_a_link_object_built_by_more_than_a_hash_literal_is_unreadable_and_a_literal_is_not() -> None:
    mixed = (
        "associated_resource :version,\n"
        "                    link: ->(*) {\n"
        "                      next({ href: nil }) if x.nil?\n"
        "                      ::API::Decorators::LinkObject.new(x).to_hash\n"
        "                    }\n"
    )
    assigned = (
        "resources :values,\n"
        "          link: ->(*) {\n"
        "            link_object = { href: h, title: t }\n"
        "            link_object[:templated] = true\n"
        "            link_object\n"
        "          }\n"
    )
    literal = "associated_resource :parent,\n                    link: ->(*) { { href: h, title: t } }\n"

    assert _unreadable(mixed) == {"version"} and _unreadable(assigned) == {"values"}
    assert _unreadable(literal) == set()


def test_a_self_link_with_an_empty_title_getter_has_no_title_member() -> None:
    text = "self_link title_getter: ->(*) {}\n"

    assert (LINK_MEMBER + "self", "title") not in entries(text) and (LINK_MEMBER + "self", "href") in entries(text)
    assert (LINK_MEMBER + "self", "title") in entries("self_link title_getter: ->(*) { represented.name }\n")


def test_a_do_lambda_and_odd_lambda_forms_never_leak_a_later_hash() -> None:
    do_form = (
        "associated_resource :parent,\n"
        "                    link: ->(*) do\n"
        "                      { href: h, title: t }\n"
        "                    end,\n"
        "                    setter: ->(fragment:, **) { { href: x, phantom: true } }\n"
    )
    nested_params = "associated_resource :p,\n    link: ->(a = f(1)) { { href: h } },\n    setter: ->(**) { { href: x, phantom: true } }\n"
    brace_in_string = 'associated_resource :p,\n    link: ->(*) { { href: "{", title: t } },\n    setter: ->(**) { { href: x, phantom: true } }\n'

    for text in (do_form, nested_params, brace_in_string):
        assert "phantom" not in {member for _, member in entries(text)}
    assert _unreadable(do_form) == {"parent"}
    assert _unreadable(nested_params) == set() and _unreadable(brace_in_string) == set()
    assert (LINK_MEMBER + "p", "href") in entries(nested_params)
    assert (LINK_MEMBER + "p", "title") in entries(brace_in_string)


def test_an_endless_def_and_an_end_with_a_comment_do_not_swallow_the_following_macros() -> None:
    text = "def foo(a) = bar\nself_link\ndef baz\n  1\nend # done\nassociated_project\n"

    assert {(LINK, "self"), (LINK, "project")} <= entries(text)


def test_a_rel_in_the_body_of_a_link_does_not_rename_it() -> None:
    assert (LINK, "self") in entries("link :self do\n  { href: path(rel: :other) }\nend\n")
    assert (LINK, "other") not in entries("link :self do\n  { href: path(rel: :other) }\nend\n")


def test_comments_are_no_link_members_and_a_sql_link_renders_href_and_title() -> None:
    commented = "link :x do\n  # { href: 1, phantom: 2 }\n  { href: h }\nend\n"
    sql = "include API::Decorators::Sql::Hal\nlink :author,\n     href: a,\n     title: b\n"

    assert "phantom" not in {member for _, member in entries(commented)}
    assert {(LINK_MEMBER + "author", "href"), (LINK_MEMBER + "author", "title")} <= entries(sql)
    assert _unreadable(sql) == set()


def _members(text: str, link: str) -> set[str]:
    return {member for location, member in entries(text) if location == LINK_MEMBER + link}


_SQL = "include API::Decorators::Sql::Hal\n"


def test_a_sql_link_renders_href_a_title_unless_it_is_empty_and_every_extra_option() -> None:
    text = (
        _SQL + "link :self,\n     href: ->(w) { 'x' },\n     title: -> {}\n"
        "link :jumpTo,\n     href: h,\n     title: -> {},\n     templated: true\n"
        "link :author,\n     path: :user,\n     column: -> { 'id' }\n"
    )

    assert _members(text, "self") == {"href"}
    assert _members(text, "jumpTo") == {"href", "templated"}
    assert _members(text, "author") == {"href", "title"}


def test_a_raw_sql_link_is_unreadable_and_a_mention_of_sql_is_no_sql_representer() -> None:
    assert _unreadable(_SQL + "link :ancestors,\n     sql: -> { 'select 1' }\n") == {"ancestors"}
    assert _unreadable("# Sql:: is mentioned here\nlink :x,\n     title: -> {}\n") == {"x"}
    assert _members(_SQL + "associated_user_link :author, column_name: :x\n", "author") == {"href", "title"}


def test_link_object_members_given_as_options_of_the_macro_are_members() -> None:
    text = "link :favor,\n     method: :post,\n     cache_if: -> { x } do\n  { href: h }\nend\n"

    assert _members(text, "favor") == {"href", "method"}


@pytest.mark.parametrize(
    "construction",
    [
        "link_object = { href: h }\n link_object[:templated] = true\n link_object",
        "{ href: h }.merge(extra)",
        "{ href: h }.merge!(extra)",
        "h = { href: h }\n h.update(method: :get)\n h",
        "h = { href: h }\n h.store(:method, 1)\n h",
        "{ href: h, **extra }",
        "{ href: h }.tap { |o| o[:x] = 1 }",
        "{ href: h }.to_h",
        "Hash[href: h]",
        "h = { href: h }\n h[:title] ||= t\n h",
        "{ href: h }.reverse_merge(extra)",
        "::API::Decorators::LinkObject.new(x).to_hash",
    ],
)
def test_every_other_way_of_building_a_link_object_makes_the_members_unreadable(construction: str) -> None:
    text = "link :x do\n  " + construction + "\nend\n"

    assert _unreadable(text) == {"x"}, construction


def test_a_setter_def_is_a_method_body_and_an_endless_def_with_spaces_is_not_one() -> None:
    assert (LINK, "self") not in entries("def foo=(value)\n  self_link\nend\n")
    assert (LINK, "self") in entries("def foo(a) = bar\nself_link\n")


def test_a_closing_bracket_at_the_macro_indent_belongs_to_the_statement() -> None:
    text = (
        "associated_resource :provider,\n"
        "                    link: ->(*) {\n"
        "                      { href: h, title: t }\n"
        "}\n"
        "associated_project\n"
    )

    assert (LINK_MEMBER + "provider", "title") in entries(text)


def test_a_rel_in_a_comment_of_the_header_does_not_rename_the_link() -> None:
    assert (LINK, "a") in entries("link :a do # rel: :commented\n  { href: h }\nend\n")


def test_a_statement_at_the_cap_is_read_and_one_line_longer_is_an_error() -> None:
    ok = "property :a,\n" + "         x: 1,\n" * 398 + "         embedded: true\n"
    too_long = "property :a,\n" + "         x: 1,\n" * 399 + "         embedded: true\n"

    assert (EMBEDDED, "a") in entries(ok)
    with pytest.raises(ValueError, match="statement longer than"):
        extract_declarations(too_long)


def test_call_keywords_named_like_members_are_not_members() -> None:
    text = "link :x do\n  { href: path(id: 1, format: :pdf, name: n, type: t), title: 'T' }\nend\n"
    members = {member for location, member in entries(text) if location == LINK_MEMBER + "x"}

    assert members == {"href", "title"}


def test_extend_api_response_gives_the_representer_path_and_the_inline_body() -> None:
    text = (
        "    extend_api_response(:v3, :work_packages, :work_package) do\n"
        "      link :logCosts do\n"
        "        {}\n"
        "      end\n"
        "    end\n"
    )
    [extension] = extract_extensions(text)

    assert extension.target == "lib/api/v3/work_packages/work_package_representer.rb"
    assert extension.patch_class is None and extension.inline_body is not None
    assert (LINK, "logCosts") in entries(extension.inline_body)


def test_extend_api_response_with_a_patch_names_the_patch_constant_and_its_file() -> None:
    text = (
        "    extend_api_response(:v3, :work_packages, :work_package,\n"
        "                        &::OpenProject::Backlogs::Patches::API::WorkPackageRepresenter.extension)\n"
    )
    [extension] = extract_extensions(text)

    assert extension.patch_class == "::OpenProject::Backlogs::Patches::API::WorkPackageRepresenter"
    assert (
        patch_file("modules/backlogs/lib/open_project/backlogs/engine.rb", extension.patch_class)
        == "modules/backlogs/lib/open_project/backlogs/patches/api/work_package_representer.rb"
    )


def test_representer_paths_for_schema_root_and_nested_targets() -> None:
    assert (
        representer_path(":v3, :work_packages, :schema, :work_package_schema")
        == "lib/api/v3/work_packages/schema/work_package_schema_representer.rb"
    )
    assert representer_path(":v3, :root") == "lib/api/v3/root_representer.rb"


def test_an_extend_api_response_it_cannot_parse_is_an_error() -> None:
    with pytest.raises(ValueError, match="cannot parse extend_api_response"):
        extract_extensions("extend_api_response(dynamic_args)\n")


# --- the pinned sources ---------------------------------------------------------------------------------------------

_SOURCES_PRESENT = not checkout_problems(pinned_versions())
needs_sources = pytest.mark.skipif(not _SOURCES_PRESENT, reason="the pinned OpenProject sources are not checked out")


def _real(version: str, path: str) -> set[tuple[str, str]]:
    return entries((SOURCES / version / path).read_text())


@needs_sources
def test_the_notification_representer_renders_read_ian_as_property_and_link_and_has_no_read() -> None:
    found = _real("17.9", "lib/api/v3/notifications/notification_representer.rb")

    assert {(PROPERTY, "readIAN"), (LINK, "readIAN"), (LINK, "resource"), (EMBEDDED, "details")} <= found
    assert (PROPERTY, "read") not in found and (LINK, "read") not in found


@needs_sources
def test_the_project_phase_representer_renders_no_dates() -> None:
    found = _real("17.9", "lib/api/v3/project_phases/project_phase_representer.rb")

    assert (PROPERTY, "active") in found
    assert not {name for location, name in found if location == PROPERTY} & {"startDate", "finishDate"}


@needs_sources
def test_the_work_package_representer_renders_the_display_id_link_members_and_the_gated_readonly() -> None:
    path = "lib/api/v3/work_packages/work_package_representer.rb"
    found = _real("17.9", path)

    assert {(LINK_MEMBER + link, "displayId") for link in ("parent", "children", "ancestors")} <= found
    assert not _real("17.4", path) & {(LINK_MEMBER + "parent", "displayId")}
    [readonly] = [
        e for e in entries_of(extract_declarations((SOURCES / "17.9" / path).read_text())) if e.wire_name == "readonly"
    ]
    assert readonly.enterprise


@needs_sources
def test_the_backlogs_patch_and_the_costs_engine_extension_are_parsed() -> None:
    patch = _real("17.9", "modules/backlogs/lib/open_project/backlogs/patches/api/work_package_representer.rb")
    engine = (SOURCES / "17.9" / "modules/costs/lib/costs/engine.rb").read_text()
    inline = [e for e in extract_extensions(engine) if e.inline_body is not None]

    assert (LINK, "sprint") in patch
    assert any((LINK, "logCosts") in entries(e.inline_body or "") for e in inline)


@needs_sources
def test_every_engine_extension_of_every_pinned_version_parses_and_a_patch_constant_resolves_to_a_file() -> None:
    for label in pinned_versions():
        for engine in sorted((SOURCES / label / "modules").glob("*/lib/**/engine.rb")):
            text = engine.read_text()
            if "extend_api_response" not in text:
                continue
            for extension in extract_extensions(text):
                if extension.patch_class:
                    relative = str(engine.relative_to(SOURCES / label))
                    assert (SOURCES / label / patch_file(relative, extension.patch_class)).is_file(), (label, relative)


@needs_sources
def test_the_file_link_and_time_entry_representers_resolve_as_and_associated_project() -> None:
    time_entry = _real("17.9", "modules/costs/lib/api/v3/time_entries/time_entry_representer.rb")
    file_link = _real("17.9", "modules/storages/lib/api/v3/file_links/file_link_representer.rb")

    assert {(PROPERTY, "comment"), (LINK, "project")} <= time_entry
    assert (PROPERTY, "originData") in file_link


@needs_sources
def test_the_timestamped_representer_embeds_the_attributes_by_timestamp() -> None:
    found = _real("17.9", "lib/api/v3/work_packages/timestamped_representer.rb")

    assert (EMBEDDED, "attributesByTimestamp") in found and (PROPERTY, "attributesByTimestamp") not in found


@needs_sources
def test_the_collection_decorator_and_the_user_representer_are_read_with_their_real_names() -> None:
    collection = _real("17.9", "lib/api/decorators/collection.rb")
    user = _real("17.9", "lib/api/v3/users/user_representer.rb")

    assert {(PROPERTY, "total"), (PROPERTY, "count"), (EMBEDDED, "elements")} <= collection
    assert (LINK, "auth_source") in user and (LINK, "authSource") not in user


@needs_sources
def test_the_storage_link_without_resource_carries_only_its_own_members() -> None:
    found = _real("17.9", "modules/storages/lib/api/v3/storages/storage_representer.rb")

    assert (LINK, "authenticationMethod") in found
    assert {member for location, member in found if location == LINK_MEMBER + "authenticationMethod"} == {"href"}


@needs_sources
def test_sql_and_resource_link_and_schema_declarations_of_17_9_are_read() -> None:
    assert {(LINK, "author"), (LINK, "assignee")} <= _real(
        "17.9", "lib/api/v3/work_packages/work_package_sql_representer.rb"
    )
    assert (LINK, "scope") in _real("17.9", "modules/grids/app/representers/api/v3/grids/grid_representer.rb")
    assert (PROPERTY, "subject") in _real("17.9", "lib/api/v3/work_packages/schema/work_package_schema_representer.rb")


@needs_sources
def test_the_narrow_as_rule_finds_the_same_override_as_the_whole_statement_in_every_pinned_representer() -> None:
    import representer_locations as module

    compared = 0
    for label in pinned_versions():
        for path in sorted((SOURCES / label).rglob("*representer*.rb")):
            lines = path.read_text().splitlines()
            for i, line in enumerate(lines):
                macro = module._MACRO_RE.match(line)
                if not macro or macro.group("rest").startswith(":"):
                    continue
                rest = macro.group("rest")
                if module._positional_symbol(rest) is None and macro.group("macro") not in (
                    "associated_project",
                    "self_link",
                ):
                    continue
                narrow = module._resolve_as(rest, module._continuation(lines[i + 1 :], module._indent(line)))
                whole = module._AS_RE.search("\n".join(module.statement(lines, i)))
                assert whole is None or narrow == whole.group(1), (label, str(path), line.strip())
                compared += 1
    assert compared > 10000


@needs_sources
def test_the_configuration_representer_renders_the_acronym_inflected_page_size_name() -> None:
    path = "lib/api/v3/configuration/configuration_representer.rb"
    acronyms = read_acronyms((SOURCES / "17.9/config/initializers/inflections.rb").read_text())
    found = {
        (e.location, e.wire_name)
        for e in entries_of(extract_declarations((SOURCES / "17.9" / path).read_text(), acronyms))
    }

    assert (PROPERTY, "maximumAPIV3PageSize") in found and (PROPERTY, "maximumApiV3PageSize") not in found


@needs_sources
def test_no_sql_representer_of_any_pinned_version_declares_a_snake_case_name() -> None:
    for label in pinned_versions():
        for path in sorted((SOURCES / label).rglob("*sql_representer.rb")):
            names = [e.wire_name for e in entries_of(extract_declarations(path.read_text()))]
            assert not [name for name in names if "_" in name.lstrip("_")], (label, str(path))


@needs_sources
def test_known_misreads_are_gone_from_the_real_representers() -> None:
    schema = _real("17.9", "lib/api/v3/schemas/schema_collection_representer.rb")
    values = _real("17.9", "lib/api/v3/values/property_representer.rb")
    sprint = _real("17.9", "modules/backlogs/lib/api/v3/sprints/sprint_representer.rb")

    assert (EMBEDDED, "elements") in schema and (LINK, "self") not in schema
    assert (LINK_MEMBER + "self", "title") not in values
    assert not {member for location, member in sprint if location == LINK_MEMBER + "status"} - {"href", "title"}


# A copy of the extractor `check_field_completeness` had before it became a filter over `representer_locations`, the
# oracle of the golden comparison below. The copy was itself compared with the original code once (0 differences over
# every Ruby file of the 17 pinned versions), so a transcription error would have shown.
_LEGACY_MACROS = (
    "formattable_property",
    "date_time_property",
    "date_property",
    "associated_visible_resource",
    "associated_resources",
    "associated_resource",
    "associated_project",
    "resources",
    "resource",
    "property",
)
_LEGACY_LINKS = ("links", "link")
_LEGACY_MACRO_RE = re.compile(r"^[ \t]*(?P<macro>" + "|".join(_LEGACY_MACROS + _LEGACY_LINKS) + r")\b(?P<rest>.*)$")
_LEGACY_POSITIONAL = re.compile(r"^\s*:(\w+)")
_LEGACY_AS = re.compile(r"\bas:\s*[:\"']?(\w+)")


def _legacy_camelize(name: str) -> str:
    if name.startswith("_"):
        return name
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _legacy_resolve_as(rest: str, following: list[str], indent: int) -> str | None:
    m = _LEGACY_AS.search(rest)
    if m:
        return m.group(1)
    for line in following[:15]:
        if not line.strip() or (len(line) - len(line.lstrip())) <= indent:
            break
        m = _LEGACY_AS.search(line)
        if m:
            return m.group(1)
    return None


def _legacy_extract(text: str) -> list[tuple[str, str, str]]:
    lines = text.splitlines()
    out: list[tuple[str, str, str]] = []
    for i, line in enumerate(lines):
        m = _LEGACY_MACRO_RE.match(line)
        if not m:
            continue
        macro, rest = m.group("macro"), m.group("rest")
        indent = len(line) - len(line.lstrip())
        positional = _LEGACY_POSITIONAL.match(rest)
        symbol = positional.group(1) if positional else ("project" if macro == "associated_project" else None)
        if symbol is None:
            continue
        out.append((macro, symbol, _legacy_resolve_as(rest, lines[i + 1 :], indent) or _legacy_camelize(symbol)))
    return out


@needs_sources
def test_the_new_extractor_reproduces_the_legacy_one_over_every_representer_file_of_every_pinned_version() -> None:
    compared = 0
    for label in pinned_versions():
        paths = sorted((SOURCES / label).rglob("*representer*.rb")) + sorted(
            (SOURCES / label).glob("lib/api/decorators/*.rb")
        )
        for path in paths:
            text = path.read_text()
            new = [
                (d.macro, d.symbol, d.wire_name)
                for d in extract_declarations(text)
                if d.macro in _LEGACY_MACROS + _LEGACY_LINKS
            ]
            assert new == _legacy_extract(text), (label, str(path.relative_to(SOURCES / label)))
            filtered = [
                (f.macro, f.ruby_symbol, f.wire_name)
                for f in check_field_completeness._extract_macro_fields(text)
                if f.ruby_symbol not in check_field_completeness.NAVIGATION_LINKS or f.macro not in ("link", "links")
            ]
            assert filtered == [
                x
                for x in _legacy_extract(text)
                if x[1] not in check_field_completeness.NAVIGATION_LINKS or x[0] not in ("link", "links")
            ]
            compared += 1
    assert compared > 5000
