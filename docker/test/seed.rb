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
project = Project.find_by(identifier: "TST")
if project.nil?
  project = Project.create!(name: "TST Test", identifier: "TST", public: false)
  log("created project TST (id=#{project.id})")
else
  log("project TST already present (id=#{project.id})")
end

if project.work_packages.empty?
  type = project.types.first || Type.first
  status = Status.respond_to?(:default) && Status.default ? Status.default : Status.first
  wp = WorkPackage.create!(
    project: project,
    type: type,
    status: status,
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
    # Re-save existing work packages so semantic ids get allocated where supported.
    if WorkPackage.first.respond_to?(:display_id)
      WorkPackage.find_each { |w| w.save }
      sample = WorkPackage.where(project_id: project.id).first
      log("sample display_id=#{sample && sample.display_id}")
    end
  else
    log("semantic identifiers not supported on this version — left as classic")
  end
else
  log("semantic mode not requested (classic identifiers)")
end

log("done")
