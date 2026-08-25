# Idempotent test seed for a local OpenProject container.
#
# Run via:  docker compose exec -T <service> bundle exec rails runner - < seed.rb
# (up.sh does this for you.)
#
# Creates, if missing:
#   - an API token for the admin user, printing its plaintext to stdout so the
#     test harness can capture it (the plaintext is only available at creation;
#     OpenProject stores a hash)
#   - a restricted-permission role + user + API token (log_own_time granted,
#     log_time/view_time_entries/manage_members withheld), for tests that need
#     a REAL OpenProject permission boundary rather than this MCP server's own
#     allowlist config
#   - a project with identifier "TST" plus one work package
#   - on 17.5+ only, when SEED_SEMANTIC=1: switches the instance to project-based
#     (semantic) identifiers so displayId becomes "TST-<n>"
#
# Output lines are prefixed "SEED:" so up.sh can parse them.

def log(msg)
  puts("SEED: #{msg}")
end

admin = User.admin.active.first || User.where(admin: true).first
raise "no admin user found" unless admin

# --- API token (print plaintext once) -----------------------------------------
# Token::API.create! returns an instance exposing the plaintext via #plain_value.
token = Token::API.create!(user: admin)
log("API_TOKEN=#{token.plain_value}")

# --- Restricted-permission role + user -----------------------------------------
# Grants log_own_time but withholds log_time/view_time_entries/manage_members,
# reproducing the exact permission-gating asymmetry GitHub issue #10 covers
# (see app/services/time_entry_service.py's own docstring): OpenProject's
# CreateContract#allowed_to_log_own? only validates log_own_time against a
# concrete WorkPackage/Meeting entity link, never a project-only link.
# Integration tests need a REAL restricted OpenProject role to exercise this --
# denied_client only tests this MCP server's OWN allowlist config, never an
# actual OpenProject permission boundary.
restricted_role = Role.find_by(name: "Integration Test Restricted") || ProjectRole.create!(
  name: "Integration Test Restricted",
  permissions: [:view_work_packages, :view_project, :log_own_time]
  # explicitly NOT granted: :log_time, :view_time_entries, :manage_members
)
# Must satisfy the instance's password complexity policy (lower/upper/digit/
# special) -- SecureRandom.hex alone is lowercase-hex-only and fails it.
restricted_password = "Aa1!#{SecureRandom.hex(16)}"
restricted_user = User.find_by(login: "integration-test-restricted") || User.create!(
  login: "integration-test-restricted",
  firstname: "Integration",
  lastname: "Restricted",
  mail: "integration-test-restricted@example.invalid",
  password: restricted_password,
  password_confirmation: restricted_password,
  status: User.statuses[:active]
)

# --- Test project + one work package ------------------------------------------
# Project identifiers are validated as lowercase regardless of the semantic/
# classic work-package-identifier display setting -- always create as
# lowercase. Semantic mode's required uppercase identifier is applied
# afterward via update_column (below), which intentionally bypasses that
# validation; a direct create! with an uppercase identifier fails it instead.
project = Project.find_by(identifier: "tst") || Project.find_by(identifier: "TST")
if project.nil?
  attrs = {name: "TST Test", identifier: "tst", public: false}
  attrs[:workspace_type] = "project" if Project.new.respond_to?(:workspace_type)
  project = Project.create!(**attrs)
  log("created project #{project.identifier} (id=#{project.id})")
else
  log("project #{project.identifier} already present (id=#{project.id})")
end

# A freshly created project has no modules enabled and no members, so the admin
# cannot see its work packages via the API. Enable every available project module
# (work packages, time/costs, news, wiki, boards, backlogs, …) and make the admin
# a project member with a work-package-capable role.
all_modules = OpenProject::AccessControl.available_project_modules.map(&:to_s)
project.enabled_module_names = (project.enabled_module_names | all_modules)
# A new project also has no work-package types enabled; assign them all so
# create_work_package (Task, etc.) works.
project.types = Type.all
project.save!
log("enabled modules: #{project.reload.enabled_module_names.sort.join(', ')}")
wp_role = Role.givable.find { |r| r.permissions.include?(:view_work_packages) }
if wp_role
  member = Member.find_or_initialize_by(project: project, principal: admin)
  member.roles = [wp_role] if member.roles.empty?
  member.save!
  log("admin is a member of tst with role #{wp_role.name}")
end

# Restricted user needs project membership too, with the restricted role
# (not wp_role) -- must happen after the project exists.
restricted_member = Member.find_or_initialize_by(project: project, principal: restricted_user)
restricted_member.roles = [restricted_role] if restricted_member.roles.empty?
restricted_member.save!
log("integration-test-restricted is a member of tst with role #{restricted_role.name}")

restricted_token = Token::API.create!(user: restricted_user)
log("RESTRICTED_API_TOKEN=#{restricted_token.plain_value}")

# Instance-wide setting: without this, OpenProject silently discards any
# `startTime` written to a time entry (TimeEntry.can_track_start_and_end_time?
# stays false) instead of storing it or rejecting it -- integration tests for
# create_time_entry/update_time_entry/create_time_entry_until/
# update_time_entry_until's start_time/end_time handling can't meaningfully
# assert anything without this being on.
unless Setting.allow_tracking_start_and_end_times?
  Setting.allow_tracking_start_and_end_times = true
  log("enabled allow_tracking_start_and_end_times")
else
  log("allow_tracking_start_and_end_times already enabled")
end

# Instance-wide setting: OFF by default in a fresh OpenProject install --
# without it, Users::DeleteContract.deletion_allowed? always returns false
# for an admin-initiated delete, and delete_user fails with a 403
# "may not be accessed" that has nothing to do with this MCP server's own
# write-allowlist logic. Needed for delete_user's integration test to
# exercise the real DELETE /users/{id} endpoint at all.
unless Setting.users_deletable_by_admins?
  Setting.users_deletable_by_admins = true
  log("enabled users_deletable_by_admins")
else
  log("users_deletable_by_admins already enabled")
end

# Instance-wide feature flag, present only on 16.6.10 of the pinned versions
# below (removed again by 17.4.1 -- the documents_api.rb gate this flag
# controlled is gone there, patch runs unconditionally). Where it exists and
# is OFF (the fresh-install default), PATCH /documents/{id} unconditionally
# raises Unauthorized *before* any permission/ownership check ever runs, so
# even a full admin token gets a generic 403 "not authorized" that has
# nothing to do with document permissions. Needed for update_document's
# integration test to exercise the real PATCH endpoint at all on 16.6.
if Setting.respond_to?(:feature_block_note_editor_active?)
  unless Setting.feature_block_note_editor_active?
    Setting.feature_block_note_editor_active = true
    log("enabled feature_block_note_editor_active")
  else
    log("feature_block_note_editor_active already enabled")
  end
else
  log("feature_block_note_editor_active not present on this version (expected on 17.4+)")
end

# Instance-wide feature flag, present on 17.3-17.6 of the pinned versions
# below (the route becomes generally available with no gate on 17.7, and
# does not exist at all before 17.3). Where it exists and is OFF (the
# fresh-install default), every User Non-Working Times / User Working Hours
# tool unconditionally raises NotFound -- not a permission error, a route
# that simply won't route. Needed for the user_schedule integration tests to
# exercise the real endpoints at all on 17.3-17.6 (see
# tests/integration/test_user_schedule.py's module docstring for the full
# per-version breakdown, verified against op-sources).
if Setting.respond_to?(:feature_user_working_times_active?)
  unless Setting.feature_user_working_times_active?
    Setting.feature_user_working_times_active = true
    log("enabled feature_user_working_times_active")
  else
    log("feature_user_working_times_active already enabled")
  end
else
  log("feature_user_working_times_active not present on this version (expected on 17.3-17.6; generally available 17.7+)")
end

# Per-user notification setting: the admin's default global NotificationSetting
# has watched=true but work_package_commented=false -- being a watcher alone
# does NOT trigger an in-app notification for a new comment; the specific
# work_package_commented flag must also be on. Needed for
# test_mark_notification_read_confirmed_roundtrip (a genuinely triggered,
# then confirmed-read notification) to have anything real to mark read.
notification_setting = NotificationSetting.find_or_initialize_by(user_id: admin.id, project_id: nil)
if notification_setting.work_package_commented
  log("admin already has work_package_commented notifications enabled")
else
  notification_setting.work_package_commented = true
  notification_setting.save!
  log("enabled work_package_commented notifications for admin")
end

# Instance-wide setting: OpenProject batches/delays journal aggregation by
# this many minutes (default: 5) before a Notifications::WorkflowJob for a
# new comment actually fires -- verified live via GoodJob::Job records
# (Journals::CompletedJob's scheduled_at is created_at + this setting's
# value). Without setting this to 0, a test that waits a realistic handful
# of seconds for a real notification (e.g.
# test_mark_notification_read_confirmed_roundtrip) can never see it appear.
if Setting.journal_aggregation_time_minutes.to_i.zero?
  log("journal_aggregation_time_minutes already 0")
else
  Setting.journal_aggregation_time_minutes = 0
  log("set journal_aggregation_time_minutes to 0")
end

if project.work_packages.empty?
  type = project.types.first || Type.first
  status = Status.respond_to?(:default) && Status.default ? Status.default : Status.first
  priority = (IssuePriority.respond_to?(:default) && IssuePriority.default) || IssuePriority.active.first || IssuePriority.first
  wp = WorkPackage.create!(
    project: project,
    type: type,
    status: status,
    priority: priority,
    author: admin,
    subject: "Seed work package"
  )
  display = wp.respond_to?(:display_id) ? wp.display_id : wp.id
  log("created work package id=#{wp.id} display_id=#{display}")
else
  log("project TST already has work packages")
end

# list_categories/get_category have no create endpoint in this server's API
# to seed one through -- a pre-existing category is needed here.
if project.categories.empty?
  category = Category.create!(project: project, name: "Seed Category")
  log("created category id=#{category.id} name=#{category.name}")
else
  log("project TST already has categories")
end

# list_documents/get_document/update_document have no create endpoint in
# this server's API to seed one through -- two pre-existing documents are
# needed here (two, not one, so a pagination test can exercise a real
# multi-page walk the same way test_list_versions_search_walks_every_server_page
# does for versions).
if project.documents.count < 2
  # Document's classification association was renamed and made optional
  # between 16.6 and 17.x -- verified directly against source (documents
  # module's app/models/document.rb on each version):
  #   16.6: `belongs_to :category, class_name: "DocumentCategory"`,
  #         `validates_presence_of :category` (required; DocumentCategory
  #         constant exists).
  #   17.6/17.7: `belongs_to :type, class_name: "DocumentType", optional:
  #              true` -- category/DocumentCategory do not exist at all
  #              (Document.new(category: ...) raises NoMethodError there).
  # Both branches pass their own version's real attribute key rather than
  # omitting it and relying on Document's own after_initialize default --
  # the seed should be explicit about which entity it creates.
  document_attrs = {
    project: project,
    description: "Seeded for integration tests"
  }
  if Object.const_defined?(:DocumentCategory)
    document_attrs[:category] = DocumentCategory.first
  elsif Object.const_defined?(:DocumentType)
    document_attrs[:type] = DocumentType.first
  end
  (project.documents.count...2).each do |i|
    document = Document.create!(document_attrs.merge(title: "Seed Document #{i + 1}"))
    log("created document id=#{document.id} title=#{document.title}")
  end
else
  log("project TST already has #{project.documents.count} documents")
end

# A freshly wiki-module-enabled project has zero wiki pages -- get_wiki_page
# has no create/list counterpart in this server's API to seed one through, so
# integration tests need a pre-existing page here.
#
# WikiPage#text= takes a raw String on OpenProject 16.6 (a plain `text` column
# on wiki_pages itself), but a WikiContent instance on 17.x (content moved to
# a separate, versioned/journaled association). Check for the constant rather
# than branching on version number, since that's the actual thing that
# differs.
if project.wiki && project.wiki.pages.empty?
  page = WikiPage.create!(wiki: project.wiki, title: "Seed wiki page", author: admin)
  page.text = if defined?(WikiContent)
    WikiContent.new(text: "Seeded content for integration tests.", author: admin)
  else
    "Seeded content for integration tests."
  end
  page.save!
  log("created wiki page id=#{page.id} title=#{page.title}")
else
  log("project TST already has wiki pages (or no wiki)")
end

# get_post has no create/list counterpart in this server's API (see
# app/ports/post_api.py's own comment on this) -- a Message always requires a
# parent Forum (Message#validates :forum, :subject, :content, presence:
# true; Forum#validates :name, :description, presence: true -- see
# app/models/message.rb / app/models/forum.rb), even though nothing in this
# MCP's API surface ever reads the Forum resource back. The forums module is
# already enabled unconditionally above (all_modules), so no extra
# module-enablement step is needed here.
if Forum.where(project: project).empty?
  forum = Forum.create!(project: project, name: "Seed Forum", description: "Seeded for integration tests")
  message = Message.create!(forum: forum, author: admin, subject: "Seed post", content: "Seeded content for integration tests.")
  log("created forum id=#{forum.id} message id=#{message.id} subject=#{message.subject}")
else
  log("project TST already has a forum")
end

# get_work_package/list_work_packages custom_fields (OPM-94) need at least
# one real, activated CE-compatible custom field on the TST project's work
# packages -- a fresh instance has none. Create one simple "string"-format
# field (is_for_all: true so it applies without a per-type
# custom_fields_projects/custom_fields_types join row).
#
# NOT has_comment: true -- verified live against a real 17.7.1 instance
# (ActiveRecord::RecordInvalid: "Add a comment text field must be blank"):
# CustomField#can_have_comment? delegates to
# `customized_class.can_have_custom_comments?`, which reads
# `acts_as_customizable`'s per-MODEL `comments:` option -- and
# app/models/work_package.rb's own `acts_as_customizable
# validate_on: :saving_custom_fields` call never passes `comments: true`
# (only app/models/project.rb does: `comments: true, admin_only_allowed:
# true`). So customComment<N> is Project-only, structurally impossible on a
# WorkPackage on this codebase, regardless of OpenProject version -- not
# merely gated to 17.2+ as OPM-94's original plan assumed from
# CustomFieldInjector#inject_comment_value alone (that method is generic
# over any customizable resource; it never fires for WorkPackage because
# has_comment? is always false there). custom_comments/
# custom_comments_truncated on WorkPackageSummary/WorkPackageDetail are kept
# regardless (harmless, forward-compatible if a future OpenProject version
# ever changes this), but will always be None in practice for this
# resource -- see this project's own docs/field-hiding.md and the OPM-94
# implementation report for this finding.
custom_field = WorkPackageCustomField.find_by(name: "Seed Text Field") || WorkPackageCustomField.create!(
  name: "Seed Text Field",
  field_format: "string",
  is_for_all: true,
  is_required: false
)
log("custom field '#{custom_field.name}' present (id=#{custom_field.id}, format=#{custom_field.field_format})")

# is_for_all only auto-applies a custom field to every PROJECT; it must also
# be attached to the relevant work-package TYPE(s) for
# available_custom_fields (what CustomFieldInjector actually renders) to
# include it -- attach it to every type already enabled on TST above.
missing_types = project.types.reject { |t| t.custom_fields.include?(custom_field) }
unless missing_types.empty?
  custom_field.types << missing_types
  log("attached custom field '#{custom_field.name}' to types: #{missing_types.map(&:name).join(', ')}")
end

# Give the seed work package an actual value for the new custom field so a
# read-path integration test has something real to assert on, not just
# "the key exists but is nil".
seed_wp = project.work_packages.first
if seed_wp && seed_wp.custom_value_for(custom_field)&.value.to_s.empty?
  seed_wp.custom_field_values = { custom_field.id => "Seeded custom field value" }
  seed_wp.save!
  log("set custom field '#{custom_field.name}' value on work package id=#{seed_wp.id}")
else
  log("seed work package already has a value for custom field '#{custom_field.name}' (or no seed work package yet)")
end

# get_project_phase/get_project_phase_definition have no list/create endpoint
# in this server's API -- a project has zero Project::Phase rows by default
# (they're an opt-in "life cycle" concept, not automatically present), so
# integration tests need one pre-existing here. Project::PhaseDefinition rows
# ARE instance-wide and pre-seeded by OpenProject itself (Initiating/Planning/
# Executing/Closing) -- only the per-project Phase instance needs creating.
if defined?(Project::Phase) && Project::Phase.where(project_id: project.id).empty?
  definition = Project::PhaseDefinition.first
  if definition
    phase = Project::Phase.create!(
      project: project,
      definition_id: definition.id,
      active: true,
      start_date: Date.today,
      finish_date: Date.today + 7
    )
    log("created project phase id=#{phase.id} definition=#{definition.name}")
  else
    log("no Project::PhaseDefinition exists on this instance -- skipping project phase seed")
  end
else
  log("project TST already has a project phase (or Project::Phase model unavailable)")
end

# --- Semantic identifiers (17.5+, opt-in) -------------------------------------
if ENV["SEED_SEMANTIC"] == "1"
  if defined?(Setting::WorkPackageIdentifier)
    Setting.work_packages_identifier = "semantic"
    log("set work_packages_identifier = semantic")
    # The project above is always created/found as lowercase "tst" -- uppercase
    # it now, every time (fresh or pre-existing), via the same validation-bypass.
    if project.identifier != "TST"
      # Skip the unique validation by updating directly — old "tst" conflicts with
      # new "TST" on case-insensitive DBs; update_column bypasses that.
      project.update_column(:identifier, "TST")
      log("uppercased identifier to #{project.reload.identifier} for semantic mode")
    end
    # Allocate semantic ids for existing work packages. Saving is not enough —
    # OpenProject exposes an explicit allocation method for this. Clear any stale
    # aliases first so repeated seeds don't accumulate duplicates.
    sample_wp = project.work_packages.first
    if sample_wp && sample_wp.respond_to?(:allocate_and_register_semantic_id)
      project.work_packages.find_each do |w|
        w.semantic_aliases.destroy_all
        w.allocate_and_register_semantic_id
      end
      log("sample display_id=#{project.work_packages.first.reload.display_id}")
    end
  else
    log("semantic identifiers not supported on this version — left as classic")
  end
else
  log("semantic mode not requested (classic identifiers)")
end

# --- Nextcloud storage fixture (opt-in, for OPM-179 storages/project_storages
# read-tool tests) -------------------------------------------------------------
# Creates a Storages::NextcloudStorage + Storages::ProjectStorage row directly,
# bypassing the live host-reachability/app-installed contract validation
# (NextcloudCompatibleHostValidator probes the host for the Nextcloud-side
# "OpenProject Integration" app on every contract-path save, which this
# fixture doesn't attempt to satisfy). This is NOT a live-connected, browsable
# storage -- no OAuth handshake happens, storage_files browsing does not work
# against it. It exists only so GET /api/v3/storages and
# GET /api/v3/project_storages have a real row to return, for the read-only
# OPM-179 MCP tools' integration tests. See docker/test/README.md.
if ENV["SEED_NEXTCLOUD_STORAGE"] == "1"
  if defined?(Storages::NextcloudStorage)
    storage = Storages::NextcloudStorage.find_by(name: "Seed Nextcloud Storage")
    if storage.nil?
      storage = Storages::NextcloudStorage.new(
        name: "Seed Nextcloud Storage",
        host: "http://nextcloud/",
        creator: admin
      )
      storage.save(validate: false)
      log("created nextcloud storage id=#{storage.id} host=#{storage.host}")
    else
      log("nextcloud storage already present (id=#{storage.id})")
    end

    project_storage = Storages::ProjectStorage.find_by(project: project, storage: storage)
    if project_storage.nil?
      project_storage = Storages::ProjectStorage.new(
        project: project,
        storage: storage,
        creator: admin,
        project_folder_mode: "inactive"
      )
      project_storage.save(validate: false)
      log("created project_storage id=#{project_storage.id} project=#{project.identifier} storage=#{storage.id}")
    else
      log("project_storage already present (id=#{project_storage.id})")
    end
  else
    log("Storages::NextcloudStorage not defined on this version -- skipping nextcloud storage seed")
  end
else
  log("nextcloud storage seed not requested (SEED_NEXTCLOUD_STORAGE unset)")
end

# --- File link fixtures (opt-in, for OPM-360 delete_file_link coverage) --------
# Requires the Nextcloud storage fixture above (SEED_NEXTCLOUD_STORAGE=1) to
# already have created a Storages::Storage + Storages::ProjectStorage on this
# project -- a FileLink's create contract requires the work package's project
# to actually have that storage linked (validate_project_storage_link), so
# this only runs when that fixture ran successfully. Bypasses AR validation
# the same way the storage/project_storage rows above do: creating through
# Storages::FileLinks::CreateContract would additionally require a live
# Enterprise-token check (check_for_enterprise_token_requirements), which
# this fixture -- like the storage connection itself -- deliberately never
# satisfies. This is NOT a live-connected file: origin_id/origin_name are
# fabricated, nothing in Nextcloud actually exists at that id.
#
# Two rows, not one: "seed-file-link-persistent.txt" stays untouched for
# tests/integration/test_write_denials.py's read-then-deny check (that test
# must never see its target vanish out from under it), and
# "seed-file-link-deletable.txt" is what
# test_storages.py::test_delete_file_link_deletes_seeded_link actually
# destroys via delete_file_link's successful-delete path -- which previously
# had no deterministic live coverage at all (see docker/test/README.md).
# find_or_create means re-running `up.sh` after a test consumed the deletable
# row seeds it again, so the test suite stays repeatable without requiring a
# full container recreate between runs.
if ENV["SEED_FILE_LINK"] == "1"
  if defined?(Storages::FileLink)
    project_storage = Storages::ProjectStorage.find_by(project: project)
    seed_wp = project.work_packages.first
    if project_storage.nil?
      log("no project_storage present -- run with SEED_NEXTCLOUD_STORAGE=1 first to seed a file link")
    elsif seed_wp.nil?
      log("no seed work package present -- skipping file link seed")
    else
      [
        ["1", "seed-file-link-persistent.txt"],
        ["2", "seed-file-link-deletable.txt"]
      ].each do |origin_id, origin_name|
        file_link = Storages::FileLink.find_by(container: seed_wp, storage: project_storage.storage, origin_name: origin_name)
        if file_link.nil?
          file_link = Storages::FileLink.new(
            storage: project_storage.storage,
            creator: admin,
            container: seed_wp,
            origin_id: origin_id,
            origin_name: origin_name
          )
          file_link.save(validate: false)
          log("created file_link id=#{file_link.id} name=#{origin_name} work_package=#{seed_wp.id}")
        else
          log("file_link '#{origin_name}' already present (id=#{file_link.id})")
        end
      end
    end
  else
    log("Storages::FileLink not defined on this version -- skipping file link seed")
  end
else
  log("file link seed not requested (SEED_FILE_LINK unset)")
end

log("done")
