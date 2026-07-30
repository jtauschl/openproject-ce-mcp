# Idempotent test seed for a local OpenProject container.
#
# Run via:  docker compose exec -T <service> bundle exec rails runner - < seed.rb
# (up.sh does this for you.)
#
# Creates, if missing:
#   - an API token for the admin user, printing its plaintext to stdout so the
#     test harness can capture it (the plaintext is only available at creation;
#     OpenProject stores a hash)
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

log("done")
