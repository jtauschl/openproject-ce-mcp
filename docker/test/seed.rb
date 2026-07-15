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
