# GitHub security settings

`github-security-settings.sh` checks and enforces this repo's GitHub-level
security settings via the `gh` CLI: enables Dependabot alerts and Dependabot
security updates if not already on (tier-independent, actually-enforced),
best-effort enables private vulnerability reporting on public repos if not
already on (also tier-independent, but visibility-gated — skipped entirely
on private repos, never attempted-then-reported), and best-effort reports
on `.github/dependabot.yml` presence, secret scanning status, Rulesets/branch
protection, and Dependency Review product availability.

Copied from `sw_dev_handbook`'s
[`templates/scripts/github-security-settings.sh.example`](https://github.com/jtauschl/sw_dev_handbook/blob/v0.8.0/templates/scripts/github-security-settings.sh.example)
(the `.example` suffix dropped, per that template's own adoption convention),
pinned to the `SW_DEV_HANDBOOK_DOC_REF=v0.8.0` doc-link version this project
is on. See [`05-tooling/github.md#secret-scanning`](https://github.com/jtauschl/sw_dev_handbook/blob/v0.8.0/05-tooling/github.md#secret-scanning)
for the policy behind each check.

## Usage

```bash
tools/security-settings/github-security-settings.sh              # targets this repo's own GitHub remote
tools/security-settings/github-security-settings.sh owner/repo    # targets a specific repo explicitly
```

Requires `gh` (authenticated) and `jq`. Exits non-zero only if a
tier-independent, enforced setting (Dependabot alerts/security updates)
failed to apply or could not be determined — every other check, including
private vulnerability reporting (best-effort enabled on public repos, but a
failure there is reported to stderr without affecting the exit code), is
report-only in the sense that it never fails the run on its own.

## Maintenance

Bump `SW_DEV_HANDBOOK_DOC_REF` in the script whenever this project's pinned
`sw_dev_handbook` tag changes, so the doc links it prints stay pointed at the
policy version actually governing this project. Re-copy the script from
`sw_dev_handbook/templates/scripts/github-security-settings.sh.example`
if the template itself changes upstream (this is a plain copy, not a
symlink — there is no automatic sync).
