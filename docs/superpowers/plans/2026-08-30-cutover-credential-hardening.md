# Cutover credential hardening — Codex hand-off

Findings from Codex's cutover review, to be implemented on this branch
(`cutover-credential-hardening`). Owner-ruled scope, 2026-08-30. A Claude
session reviews the result before merge.

## To implement

1. **Preserve the live Google Maps key during legacy cutover** instead of
   relying on manual credential-file preparation.
2. **Make Maps mandatory for every server instance** and include the real
   Maps/phone probe in `verify-instance.sh`.
3. **Treat Xero reauthorization as an explicit post-cutover acceptance
   step** — OAuth tokens remain intentionally unmigrated. (The new
   `/admin/xero` page, merged in PR #110, is the operator's reconnect
   surface.)
4. **Record email delivery and session-replay capture as deferred
   post-deployment features** in `docs/rewrite-status.md` — not retired
   capabilities.
5. **Make no changes** for the benign AppError rows, Celery Beat startup,
   beat tables, or the intentional environment renames.

## Repo constraints that apply

- Commit-tier hooks mirror CI and run on every commit; never `--no-verify`.
- `docs/rewrite-status.md` only shrinks or gains tasks; rulings go to
  `docs/rewrite-history.md`.
- Server-script changes get coverage in
  `scripts/server/test_server_templates.sh` (static suite: shellcheck +
  rendering + pure-function tests; no root, no services).
- Comments record the rejected alternative (ADR 0043); model-originated
  rationale carries the model prefix until ratified (ADR 0051).
- `cutover-instance.sh`'s preflight should surface anything reconfigure
  would refuse mid-flow (see `instance.sh validate-config`).
