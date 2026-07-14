# Security Policy

## Supported versions

This project follows semantic versioning. Security fixes are released against the
latest published version on PyPI. Only the most recent release line is supported;
please upgrade before reporting an issue you cannot reproduce on the latest
version.

| Version         | Supported |
| --------------- | --------- |
| Latest release  | ✅        |
| Older releases  | ❌        |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security-sensitive reports.

Instead, report privately via GitHub's
[**Report a vulnerability**](https://github.com/jtauschl/openproject-ce-mcp/security/advisories/new)
form (Security → Advisories). If you cannot use that form, email the maintainer
at the address on the [GitHub profile](https://github.com/jtauschl).

When reporting, please include:

- the affected version (`openproject-ce-mcp --version`),
- a description of the issue and its impact,
- steps to reproduce or a proof of concept, and
- any relevant configuration (with **secrets redacted** — never send real API
  tokens).

You can expect an initial acknowledgement within a few days. Once a fix is
available it will be released to PyPI and noted in the
[CHANGELOG](CHANGELOG.md) under a **Security** heading, as with the fixes in
0.2.2.

## Security model

This server is a guarded bridge to the OpenProject REST API. Its security posture
depends on configuration; the most relevant controls are:

- **Read tools are exposed per group via 8 individual booleans**:
  `OPENPROJECT_ENABLE_PROJECT_READ`, `_WORK_PACKAGE_READ`, `_MEMBERSHIP_READ`,
  `_VERSION_READ`, `_BOARD_READ` (default `true`), plus the opt-in
  `_PERSONAL_READ`, `_EXTENDED_READ`, and `_ADMIN_READ` (default `false` —
  `_ADMIN_READ` gates the instance-wide user/group listing, which is PII with
  no project-scope boundary). Setting any leftover `OPENPROJECT_TOOLS` or
  `OPENPROJECT_ENABLE_METADATA_TOOLS` var in your config is now ignored (a
  startup/`doctor` warning names the exact replacement). **The 5 core write
  flags default `true`**, since the real gate is the project allowlists below,
  not the category flag — a write flag alone does nothing without a project in
  `OPENPROJECT_WRITE_PROJECTS`, and the corresponding write tools aren't even
  registered unless both `OPENPROJECT_READ_PROJECTS` and
  `OPENPROJECT_WRITE_PROJECTS` are non-empty. `OPENPROJECT_ENABLE_PERSONAL_WRITE` and
  `OPENPROJECT_ENABLE_ADMIN_WRITE` default `false`, since neither has that
  project-scope safety net. Every write flag requires its own matching read
  boolean to be `true` (enforced at startup); write scopes are always
  additionally intersected with the project read scope, so a project must be
  readable before it can be written.
- **Project allowlists** (`OPENPROJECT_READ_PROJECTS` / `OPENPROJECT_WRITE_PROJECTS`)
  restrict every project-scoped operation to the named projects. Both are
  **fail-closed**: empty or unset denies all project-scoped access on that
  side, not "everything visible" — `*` is required to explicitly allow all
  projects. `mark_notification_read`/`mark_all_notifications_read` are the one
  exception: they are personal, self-scoped mutations of the caller's own
  notification state (not a project-scoped write) and are governed only by
  `OPENPROJECT_ENABLE_PERSONAL_READ` plus `OPENPROJECT_ENABLE_PERSONAL_WRITE`,
  independent of `OPENPROJECT_WRITE_PROJECTS`. The notification list itself is
  still filtered by `OPENPROJECT_READ_PROJECTS`.
- **Admin reads and writes** (listing users/groups, and user/group management)
  require the separate `OPENPROJECT_ENABLE_ADMIN_READ`/`OPENPROJECT_ENABLE_ADMIN_WRITE`
  opt-ins — an ordinary read/write pair, but neither is activated by any
  project-scoped flag or allowlist. **Membership writes** are a project-scoped
  write like any other and use `OPENPROJECT_ENABLE_MEMBERSHIP_WRITE` (plus the
  usual project write allowlist) — they are not part of admin-write.

### Exposure controls vs. real security boundaries

It's worth being precise about what each control actually protects against,
rather than lumping them all into one "security" bucket:

1. **Real security boundaries** when the agent talks to OpenProject
   exclusively through this MCP's tools: the write flags, the project
   allowlists, field hiding, and the preview/confirm flow. They stop an
   agent's own mistakes and prompt-injection attempts from turning into
   writes or reads the operator didn't intend.
2. **`OPENPROJECT_ENABLE_PERSONAL_READ`/`_EXTENDED_READ`/`_ADMIN_READ`** are
   also runtime-enforced, not cosmetic — they genuinely control what data
   reaches the agent's context, `_ADMIN_READ` in particular keeping the
   instance-wide user/group list (PII) out of context by default. They are
   not, however, an independent authorization boundary against someone who
   already holds the API token and network access.
3. **Nothing here stops direct API access.** None of these MCP-level controls
   can stop an actor who independently holds the API token and network
   reachability to OpenProject — they can call the REST API directly,
   bypassing this MCP entirely. That is the OpenProject role/permission
   system's job, not this server's — combine both layers for real defense in
   depth.
- **Write operations use a preview/confirm flow**: call a tool once to get a
  preview, then again with `confirm=true` to execute. Previews are
  server-validated where OpenProject provides an appropriate form or
  validation endpoint; otherwise they are explicit client-side action
  previews. In every case, the actual mutation requires `confirm=true` — there
  is no way to skip it. Project write allowlist checks are independent of this
  and apply regardless of confirmation state — an emoji reaction, for
  example, is resolved to its activity's linked work package and checked
  against that project's write scope, rejected if the link can't be resolved.
- **Attachment uploads require `OPENPROJECT_ATTACHMENT_ROOT`** to be set to an
  absolute directory — there is no current-working-directory fallback, and
  `create_work_package_attachment` is not even registered when it's unset.
  Once set, files outside the configured root are refused, and
  credential/config files (`.mcp.json`, `.env`, `*.pem`, keys) are refused
  even inside it, so an attachment tool call cannot exfiltrate local secrets.
- **The API token is a secret.** Store it only in a local, git-ignored config
  (e.g. `.mcp.json`, mode `600`) — never commit it. A remote plain-`http://`
  base URL emits a startup warning because the token would be sent unencrypted.

See the README's configuration and security sections for the full flag reference.

## Prompt injection risk

This server returns user-authored text (work-package descriptions, comments, news,
wiki content) from the OpenProject instance. **Malicious users could embed prompt
injection payloads** in this content to manipulate an agent connected via MCP.

### Mitigations

1. **Server instructions** explicitly warn connecting agents that returned content
   is untrusted and should be treated as data, not instructions.
2. **Content delimiting**: Long-form user-provided text (descriptions, comments,
   news, wiki content) is wrapped in `<user-content>` tags to mark clear boundaries.
   Short fields (subject lines, titles, names) are NOT delimited as they are
   typically visible in listings and easier to inspect manually.
3. **Fail-closed project scope by default**: a fresh, unconfigured install has
   no readable or writable projects until you list them in
   `OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS` — that allowlist,
   not the write-category flags, is what actually gates access — and every
   write additionally uses a preview/confirm flow.

### Limitations

These mitigations reduce risk but **cannot eliminate it**. A sufficiently
sophisticated prompt injection could still influence an agent's behavior. Deploy
this server only if you trust:

- The OpenProject instance administrators to moderate malicious content
- The connecting agent to handle untrusted input responsibly
- Your MCP client to enforce permission boundaries

If your threat model cannot accept this risk, set the relevant
`OPENPROJECT_ENABLE_<GROUP>_READ` flag(s) to `false` (e.g.
`OPENPROJECT_ENABLE_WORK_PACKAGE_READ=false`) to stop exposing that content.
