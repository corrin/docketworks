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

## Verified facts (Claude fact-check, 2026-08-30 — implement against THESE)

- **Item 3 as stated is wrong for a real cutover.** v1 stores Xero tokens
  PLAINTEXT on `workflow_xeroapp` (v1 xero_app.py:33-37); migrate_v1_data.sh
  does not exclude the table; instance.sh loads the xero_apps fixture only
  when no XeroApp row exists. So after cutover-instance.sh the connection is
  LIVE — no re-consent (subject to the 60-day refresh window). Re-consent
  was needed on UAT only because its source was the SCRUBBED dump, which
  strips the table. Correct scope: document the distinction (checklist +
  runbooks), and name /admin/xero as the reconnect surface for the scrubbed
  and token-expired cases — do not add a mandatory reauth step.
- **Item 1 as stated mis-models v1.** The Maps key was never in v1's
  database — env var only (v1 geocoding_service.py:42). There is no live DB
  value to preserve; the key's one source at cutover is the credentials
  file. Correct scope = item 2: add GOOGLE_MAPS_API_KEY to
  require_instance_credentials (instance.sh:194-202 — it is currently
  optional at :380 and silently renders null), and have verify-instance.sh
  run check_integration_settings via dw-run.sh (precedent:
  docs/instance-setup-production.md:55). Note its phone branch prints
  "disabled" and exits early when phone_provider_enabled is false, and the
  Maps call is live/billable per verification run.
- **Real defect found: migrated phone ciphertext blocks the loader.**
  load_integration_settings skips a group when ANY of its columns is
  non-NULL (load_integration_settings.py:96-98), and the migration carries
  v1's Fernet ciphertext into phone_provider_username/password — so the
  credentials-file phone values can never apply until the ciphertext is
  nulled. Fix in the cutover path (null the two columns during
  migrate_v1_data.sh's post-steps, with the checklist row updated), not in
  the loader.
- **Real defect found: dead prose.** migrate_v1_data.sh:179 tells the
  operator to run a decrypt helper that does not exist anywhere in the
  repo. Re-entry is the only real path; fix the prose (and checklist :98).
- **Item 4 specifics.** Email: rewrite-status mentions
  blocked-by:email-feature only inside the weak-password bullet; give it a
  standalone DEFERRED entry scoping SMTP/backend/credentials home (note
  test_load_integration_settings.py:98 already rejects an smtp_password
  column as unknown). Session replays: rewrite-status.md:320 already defers
  it, but v2 SCHEDULES purge_old_session_replays_daily (v1-disposition:235,
  config/celery.py) while nothing creates replays, and server_setup.md:289
  still describes syncing a session-replays directory — retire the beat
  entry until ingestion lands, and fix the doc.
- **The five formerly-encrypted columns** (checklist :98):
  crm_phoneprovidersettings.username/.password and
  quoting_suppliercredential.username/.password/.api_key. Xero tokens are
  NOT among them.
