# Release review checklist

This is the checklist run before tagging and publishing a release. Copy it into
a fresh review for the target version, fill in the bracketed placeholders, and
work through the sections in order. Each section ends in a pass/fail signal;
section 12 turns those into a single Go/No-Go decision.

The review only produces a decision. Writing the changelog, bumping the
version, committing, tagging, and pushing are separate follow-up steps that
happen only after an explicit go-ahead — see section 12.

Any concrete **code** defect the review turns up gets its own tracker work
package before it's fixed, same as any other change to this project — the
review records findings, it doesn't silently patch code. The one exception is
tracker metadata itself (a stale version/WP description) — that's
administrative housekeeping, not a code change, and can be corrected inline
as part of the review (see section 1).

---

## 0. Setup

- Target version: `[X.Y.Z]`. Previous release: `[X.Y.Z-1]`, tag `v[X.Y.Z-1]`.
- Commit range for this release: `git log v[X.Y.Z-1]..HEAD --oneline`.
- Restate the milestone's stated goals in one or two sentences (pull from the
  tracker version description, if one exists) — section 3 verifies against
  this, so get it right here.

## 1. Tracker completeness & scope

- Fetch every work package filed under the target version, all statuses —
  confirm all are Closed, none New/In Progress. **Exception:** exactly one
  work package may represent the release's own publish orchestration (e.g.
  "Prepare and publish vX.Y.Z"); that WP may legitimately be New or In
  Progress at review time, since it cannot close until the publish it
  describes has actually happened. It should be moved to In Progress once
  this review starts. Every other delivery/defect WP under the target
  version must still be Closed before Go — this exception does not extend to
  any actual feature or fix work.
- Diff WP subjects against the commit log: every ticket referenced in a
  commit should have a corresponding closed WP. The reverse is not a strict
  1:1 — a WP with no code change (a decision doc, a roadmap/classification
  ticket) can be legitimately commit-less if it has a traceable close-out
  (comment, relation, description update). Only flag a WP as orphaned if it
  has neither a commit nor a documented close-out.
- Spot-check for scope drift: anything that reads like it belongs in a later
  version, and confirm any such reclassification actually happened (moved WP,
  updated description) rather than being noted and forgotten.
- Confirm no other WP silently references release-relevant work without
  being filed under this version.
- **Version description accuracy** — version descriptions go stale. Re-read
  the target version's description against what actually shipped; this is
  the one place this review corrects something inline rather than just
  filing a finding (it's tracker metadata, not code — see the note above) —
  fix the text if a claim doesn't hold (promised-but-not-delivered, or
  delivered-but-unmentioned). Spot-check the previous 1–2 already-released
  versions'
  descriptions are still accurate in hindsight, and that any version the
  target release deferred work *into* reflects that in its own description
  text, not just in the WP's version field.

## 2. Documentation cleanliness

Apply the project's own documentation conventions against every file changed
since the previous release tag:
- English only. No AI-tool names used as attribution — naming a client being
  configured (in a per-client setup guide) is fine, claiming a tool "wrote"
  something is not.
- No secrets or machine-local private config *contents* (tokens, real
  hostnames, a developer's actual local paths). This does **not** ban
  mentioning gitignored config *filenames* that are a normal, expected part
  of setup (e.g. an example config, a client's config path) — public setup
  docs describing what file gets written and where is expected content, not
  a leak.
- **Local-cache-as-evidence rule**: a gitignored local mirror/cache used by
  internal tooling (e.g. a cloned-source cache for an API-drift checker) may
  be named when describing that tool's own mechanics ("this script clones
  sources into `<cache-dir>/<version>/`") — that's fine anywhere, including
  inside the tool's own docs. It must **not** be cited as an evidence/source
  reference for a claim in docs, code comments, or WP descriptions (e.g.
  "verified against `<cache-dir>/17.5/...`") — the reader has no access to
  that path. Any such verification claim should cite the canonical public
  upstream source location instead.
- Positive framing ("what shipped", not "what we chose not to do") applies to
  the changelog and other release-facing text only — it does not apply to a
  security doc or architecture doc's legitimate non-goals/exclusions section.
- Tool/API reference docs match the actual registered surface — compare
  against the real registration code, not an unrelated tool with a similar
  name. Anything added or removed this release is reflected; nothing stale
  remains.
- **Audience fit per doc** — each doc should read as written for its actual
  reader, not a generic dump: end-user quickstart docs for a new
  human evaluating/installing; per-client setup guides for a human
  configuring that one client; agent-facing tool/filter reference docs
  terse and reference-style (not prose); architecture doc for a
  contributor/maintainer; security doc for a security-conscious operator.
  Flag content pitched at the wrong reader or the wrong level of detail.
- Check any explicitly-known stale references (version numbers, historical
  examples) in context before "fixing" them — a historical example citing an
  older version is often legitimate, not automatically stale.
- **Comment/docstring hygiene.** Code comments, docstrings, test comments, and
  tooling comments must be publication-ready: concise, technically meaningful,
  and free of internal tracker IDs, work-package references, private review
  history, or machine-local evidence. A comment that explains a non-obvious
  technical reason ("why this AND-gate, not an independent toggle") stays; the
  ticket number, review round, or implementation-phase label that originally
  motivated it does not. This does not apply to a work-package identifier used
  purely as a public, illustrative example of the display-id format (e.g. a
  `PROJ-123`-style placeholder in a filter or parameter doc) — that is
  documentation content, not an internal tracker citation.

## 3. Main goal verification

Restate this release's headline goal(s) (from section 0) and verify what
actually shipped against what was claimed — this section is release-specific,
so its concrete checks vary. General shape: for each major feature/fix area,
confirm it's implemented, covered by any relevant opt-in/hiding mechanism
consistent with siblings, documented, and tested (a four-way check per area).
Run this project's API-drift/coverage tooling (see section 5) as part of this
verification, not just as a tooling health check.

## 4. Tests: health and coverage

- `ruff check .` and `ruff format --check .` both green.
- Default/unit suite green: `uv run pytest` (note what this actually covers —
  if the project excludes a marked subset, e.g. integration tests, by
  default, say so explicitly rather than calling this "the full suite").
  Run the excluded subset too if it's runnable locally (e.g. against a local
  test harness, never production), and note if it wasn't run and why.
- **Check actual CI status on the last push**, not just local green —
  `gh run list --branch main --limit 5` and `gh run view <run-id>` for
  anything red. Local-green and CI-green are not the same thing; CI runs a
  wider OS/Python matrix that can catch platform-specific bugs local runs
  miss entirely.
- Spot-check newly added tests for real assertions, not placeholder/
  tautological ones.
- Confirm any new live/smoke tests are wired to run against a local test
  harness, never a production instance.
- Note the project's coverage-tooling policy (if a coverage tool is
  installed but no threshold is enforced, that's an open question to raise,
  not an assumed gap).
- **Explicit skip decision** — if the excluded/integration subset was not
  run this release, record that as an explicit accept/skip decision in
  this review's findings (who decided, why — e.g. no local harness
  available) rather than leaving it as an implied gap inside a green run;
  carry it forward into section 12's "known/accepted skips" summary.

## 5. API-check / drift tooling itself

- Read the tooling that verifies API-surface drift — confirm it still checks
  what it claims to check, including anything newly added this release (not
  silently un-curated).
- Confirm the tool's source-fetch configuration (sparse paths, pinned
  versions, whatever the equivalent is) covers everything this release's
  work touched — a resource whose source lives outside the fetched paths
  will falsely report as "absent."
- Run the tool fresh and read the actual output, not just the exit code —
  confirm it asserts something meaningful and isn't silently skipping.
- If the tool has an optional live-probe mode gated by env vars, run its
  deterministic (env-vars-unset) mode as the primary gate; treat a live-
  probed run as a supplementary check against a test harness only, never
  production.
- **Deterministic generated reports** — for any release-gating report this
  tool regenerates (e.g. `COVERAGE.md` from the API-drift checker),
  regenerate it fresh in deterministic/no-live-probe mode as part of this
  review and diff against the committed version; a stale committed report
  is a finding, not a rubber stamp.

## 6. Info hygiene

- Grep committed docs/source for anything that shouldn't be public:
  production hostnames, internal project/company names, tokens, and (per
  section 2's local-cache rule) any local-only path cited as evidence.
- Re-apply the positive-framing rule specifically to the drafted changelog
  entry for this release.
- Confirm any previously-corrected doc claim reads as a clean current-state
  description now, not a "this used to be wrong" narrative.

## 7. Setup/install clarity

- Walk the install/update quickstart top-to-bottom as a brand-new user
  would — confirm every command shown matches what's actually implemented.
- Confirm per-client setup guides are consistent with each other and with
  the current setup flow — no leftover language describing an older,
  since-simplified flow.
- Confirm the architecture doc still matches what's implemented.
- **Source-installer launchers** — confirm `get.sh`, `get.ps1`,
  `uninstall.sh`, `uninstall.ps1`, and `configure_mcp.py` are covered by
  their dedicated test suite (POSIX/PowerShell syntax checks, both
  dependency-install paths — `uv sync` and venv+pip fallback — launcher→
  interpreter handoff, and setup CLI argv dispatch) and that suite is
  green; this review does not re-derive that coverage inline. Spot-check
  README's documented destination paths and `DIR`/`$env:DIR` override
  against the scripts' current content.

## 8. Permission model consistency

- Re-verify (against source, not prior notes) that read/write enablement is
  what the security doc claims it is — scope list, defaults, any
  intersection invariant (e.g. "must be readable before writable").
- Confirm every new read/write surface added this release got the same
  scope/allowlist treatment as its siblings — no silently-more-permissive
  new code path.
- Confirm every new field-hiding / opt-in-gating flag added this release
  follows the same naming/defaults/wiring pattern as pre-existing ones.
- Cross-check any allowlist-related bug fixed this release has a regression
  test that specifically asserts the allowlist boundary, not just a general
  correctness assertion.
- Re-verify the security doc's permission-model section end-to-end against
  current source as a fresh check, not by trusting an earlier fix was
  complete.

## 9. Packaging & distribution

- `git status --short` clean, `git diff --check` clean.
- No secrets/local configs/backups in the diff since the last release.
- Remove any pre-existing build output before building (stale artifacts give
  a false-clean signal from the package-metadata checker), then build and
  check package metadata.
- **Install-from-built-artifact smoke** — the load-bearing packaging check.
  Source tests passing is not the same as "a user can install and run the
  built artifact." In a fresh temporary environment, install the built
  wheel and exercise every console-script entry point and subcommand's
  `--help` (not every entry point necessarily has its own `--version` — use
  it where the entry point actually supports it) from outside the repo
  checkout.
- **Import/metadata sanity** — in that same fresh environment, import the
  package and print its version; confirms the package manifest, the
  in-package version constant, and what's actually importable all agree.
- **Artifact content check** — inspect both distribution formats' file
  listings for anything that shouldn't ship (local configs, gitignored
  caches, backups, tokens, the build-output directory itself nested
  inside) **and** confirm everything that should be there for the package
  to actually work is included (source modules, package metadata, license,
  entry points). This is what will be uploaded to the package registry
  (PyPI for this project) — get the file list right here, before the tag
  push makes it irreversible. The broader-inclusion format gets the closer
  look.
- **Dependency/lock sanity** — confirm the lockfile matches the manifest,
  with no drift from this release's dependency changes.
- **Minimum-supported-version note** — confirm the manifest's stated minimum
  matches what the CI matrix actually tests; treat a passing CI matrix as
  the evidence rather than re-testing every version locally.
- **CI/publish workflow static review** (read the workflow files, don't
  trigger them) — confirm trigger conditions, permissions, environment,
  and build→check→publish step order are all still correct and unchanged
  since the last release. Note explicitly whether the publish workflow
  creates a release-notes object on the hosting platform, since that
  affects section 10.
- **Supply-chain / Trusted Publishing review** — confirm the publish
  workflow still uses PyPI Trusted Publishing (OIDC `id-token: write` plus
  a scoped `environment:`, no stored long-lived token/secret) and that the
  configured OIDC identity (repo + workflow filename) still matches.
  Record explicitly whether a build-provenance attestation (e.g.
  `actions/attest-build-provenance`) is produced — if not, that's a
  standing accepted gap to note here, not to silently skip.
- Confirm whether a changelog section for the target version already exists:
  if absent, it gets written fresh in section 12; if a draft already exists,
  don't blindly overwrite it — check whether it's an approved draft (then
  refine it in section 12) or a stale/unreviewed leftover (flag it as a
  finding rather than editing it silently).

## 10. Release notes & version-description consistency

- The changelog, the tracker's version description, and any separately-
  published release notes (if the publish workflow creates one — see
  section 9) should tell the same story at appropriate detail depth per
  audience. They don't need identical wording, just no contradictions. At
  review time (before the changelog is drafted), this section just confirms
  which of these text sources actually exist for this project and records
  that fact — it can't yet diff content that doesn't exist.
- Once Go/No-Go is reached and the changelog is drafted (section 12, step
  1), diff its bullet list against the version description's claims
  (already cross-checked in section 1) as part of that same follow-up step —
  not as a separate review action, since the changelog doesn't exist until
  then.

## 11. Client/consumer config & environment-variable compatibility

- Confirm any config file this project's setup tooling writes for external
  consumers (IDE/client configs, generated config files, etc.) is still
  read/write-compatible with what the *previous* release wrote — no schema
  change that would silently break an existing user's setup, unless the
  reading code explicitly handles the old shape too.
- Confirm setup/diagnostic commands don't create unnecessary secrets or
  backup files on a normal, no-conflict run.
- **Env-var migration mapping** — for any renamed/removed/consolidated
  environment variable this release (cross-check against `CHANGELOG.md`'s
  `### Changed` entries by name), confirm: the old name has no silent
  alias, the new name and its exact replacement are spelled out in the
  changelog, and an unset/removed scope fails closed rather than defaulting
  to the old "allow everything" behavior. Confirm the startup/`doctor`
  warning names the exact replacement variable, not just "deprecated."

## 12. Go/No-Go decision

- Summarize findings per section as a short table: concrete blockers vs.
  non-blocking notes.
- Call out known/accepted skips explicitly in the summary (e.g. a test that
  skips under specific, expected conditions) — don't let them hide inside a
  green run.
- State the post-release rollback policy in one or two lines before Go, not
  after something breaks (e.g.: this package's registry can't un-publish a
  version, so recovery is a forward-fix patch release, not a yank-and-retry
  — confirm this is still the intended policy, or state the actual one).
- **If No-Go:** list concrete blockers as new/updated tracker WPs; the
  review stops here. A short second pass follows once blockers are closed.
- **If Go:** get explicit confirmation before doing anything further. Only
  then, as a distinct follow-up (not part of the review itself):
  1. Write the changelog section for this release from the closed WPs /
     commit log — positive framing only. Then do section 10's diff against
     the version description's claims before moving on.
  2. Bump the version everywhere it's declared (package manifest, any
     in-package version constant, anything else that mirrors it).
  3. Commit locally — no push without a separate explicit go-ahead.
  4. **Tag exactness** — before tagging, confirm the current commit hash is
     exactly the one that passed this review, not any later local change.
  5. Report back. Tagging/pushing remains a further step requiring its own
     explicit confirmation, after the release commit is reviewed — for this
     project, pushing a `vX.Y.Z` tag triggers `.github/workflows/publish.yml`,
     which publishes to PyPI via trusted publishing. A PyPI release cannot be
     un-published once uploaded (see the rollback note above), so this is the
     one genuinely irreversible step in the whole process — confirm the
     artifact content check (section 9) and the tag-exactness check (step 4)
     both passed before giving that go-ahead. Closing the tracker version is
     a separate step after the publish succeeds.
  6. **Verify the publish** — before creating the GitHub Release: confirm
     the `publish.yml` run for this tag succeeded (`gh run list`/
     `gh run view`), confirm the new version's files are visible on PyPI,
     and in a fresh temporary environment `pip install <package>==<X.Y.Z>`
     from the real PyPI index (not a local artifact — section 9 already
     covers that) and re-run the same console-script `--help`/`--version`
     smoke as section 9. This is the only check that exercises the artifact
     users actually receive.
  7. **Create a GitHub Release** for the new tag, after the PyPI publish
     succeeds. `publish.yml` only builds and publishes to PyPI — it does not
     create a GitHub Release object — but every prior tagged version has one,
     created manually out-of-band. Keep doing this for consistent release
     history; if that policy ever changes, update this step instead of
     letting a future release silently skip it.
