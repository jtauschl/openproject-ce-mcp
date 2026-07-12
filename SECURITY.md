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

- **Read is enabled by default per resource scope** (`project`, `work_package`,
  `membership`, `version`, `board`); each scope's `OPENPROJECT_ENABLE_*_READ`
  flag can disable it individually. **Write is disabled by default** for every
  scope and requires its own `OPENPROJECT_ENABLE_*_WRITE` opt-in; write scopes
  are always intersected with read scope, so a project must be readable before
  it can be written.
- **Project allowlists** (`OPENPROJECT_READ_PROJECTS` / `OPENPROJECT_WRITE_PROJECTS`)
  restrict every project-scoped operation to the named projects. Both are
  **fail-closed**: empty or unset denies all project-scoped access on that
  side, not "everything visible" — `*` is required to explicitly allow all
  projects. `mark_notification_read`/`mark_all_notifications_read` are the one
  exception: they are personal, self-scoped mutations of the caller's own
  notification state (not a projected-scoped write) and are governed only by
  the `work_package` write flag, independent of `OPENPROJECT_WRITE_PROJECTS`.
  The notification list itself is still filtered by `OPENPROJECT_READ_PROJECTS`.
- **Admin writes** (user/group/membership management) require the separate
  `OPENPROJECT_ENABLE_ADMIN_WRITE` opt-in.
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
3. **Read-only by default**: Write operations require explicit opt-in and use a
   preview/confirm flow.

### Limitations

These mitigations reduce risk but **cannot eliminate it**. A sufficiently
sophisticated prompt injection could still influence an agent's behavior. Deploy
this server only if you trust:

- The OpenProject instance administrators to moderate malicious content
- The connecting agent to handle untrusted input responsibly
- Your MCP client to enforce permission boundaries

If your threat model cannot accept this risk, disable the relevant read scopes
(`OPENPROJECT_ENABLE_WORK_PACKAGE_READ=false` etc.).
