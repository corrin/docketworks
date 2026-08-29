# UAT side-by-side v1/v2 runbook — 2026-08-29

> **For the executing agent on the UAT box (`dockertworks-demo`):** execute
> phases 2–4 top to bottom with full authority for every step written here,
> including the destructive ones. Corrin has ruled per-step check-ins too
> slow; report when finished or when genuinely blocked. Outside this list:
> do not touch the `docketworks-demo` instance or its database, never
> contact the production host (`msm` / `office.morrissheetmetal.co.nz`),
> and never set `XERO_READONLY`. Capture failures verbatim; continue past a
> failure only if later steps do not depend on it.

**Goal:** v1 at `https://msm-uat.docketworks.site` and v2 at
`https://msm-uat2.docketworks.site`, both loaded from the same scrubbed
production dump (`/tmp/scrubbed_dw_msm_prod_20260829_135924.dump`, SHA-256
`5b113ebb79b741deeea5b729e170c162750badb104db003454d5668987289674`, taken
2026-08-29 13:59 NZT), so Corrin can compare the two apps screen by screen
on identical data. Rollback machinery is out of scope — v1 stays running
throughout; the v2 instance is additive.

## Phase 1 — v1 on fresh data — DONE 2026-08-29

Completed by the box agent: dump restored into `dw_msm_uat` (exit 0, clean;
`job_job` 2,429 rows, `job_jobevent` 80,532, `job_costline` 27,057,
`accounts_staff` 24, 83 tables), `gunicorn-msm-uat` +
`celery-beat-msm-uat` + `celery-worker-msm-uat` running, HTTP 200
confirmed from inside and outside. Dump retained for phase 3.
Known pre-existing: `backup-db-msm-uat` / `backup-files-msm-uat` units are
in failed state; the archive holds usable v1-era password hashes (why
step 16 deletes it).

## Phase 2 — host to v2 shape

v1 keeps running through all of this: releases are immutable directories
and the repo swap keeps v1's git objects (`scripts/server/cutover/README.md`).

- [ ] 5. Verify GitHub auth:
  `git ls-remote https://github.com/corrin/docketworks_v2.git HEAD`.
  If auth fails, check the credential helper `/opt/docketworks/repo` fetches
  with; if unresolvable, stop and report.
- [ ] 6. `git clone https://github.com/corrin/docketworks_v2.git ~/docketworks_v2`
  (if this runbook was fetched from a branch, the clone still tracks `main`;
  the cutover scripts are identical there).
- [ ] 7. `cd ~/docketworks_v2/scripts/server/cutover && sudo ./cutover-host.sh`
  Records firewall/listener state, swaps `/opt/docketworks/repo` to the v2
  remote, converges UFW/fail2ban. If it aborts on an unexpected public
  listener, report the listener — do NOT pass `--allow-port` on your own
  judgment.

## Phase 3 — v2 instance beside v1

- [ ] 8. `sudo /opt/docketworks/repo/scripts/server/instance.sh prepare-config msm uat2`
  Fill required values by copying from
  `/opt/docketworks/config/msm-uat.credentials.env` where key names match;
  `instance.sh` errors name anything missing. GCP key file
  `/opt/docketworks/config/msm-uat-gcp-key.json` exists — point the uat2
  config at it if the contract wants a path. Report any value you cannot
  source rather than inventing one.
- [ ] 9. `sudo /opt/docketworks/repo/scripts/server/instance.sh create msm uat2 --ref origin/main --fqdn msm-uat2.docketworks.site`
- [ ] 10. Load the data:
  - stop the uat2 gunicorn/celery units
  - `sudo -u postgres createdb -O dw_msm_uat2 dw_msm_uat2_scratch`
  - `sudo -u postgres pg_restore -d dw_msm_uat2_scratch --no-owner --role=dw_msm_uat2 /tmp/scrubbed_dw_msm_prod_20260829_135924.dump`
  - `sudo -u postgres /opt/docketworks/repo/scripts/ops/migrate_v1_data.sh dw_msm_uat2_scratch dw_msm_uat2`
  - capture the script's row-count parity output for the final report.
- [ ] 11. **Xero posture BEFORE starting uat2 services** — on `dw_msm_uat2`:
  `SELECT id, name, (access_token IS NOT NULL), (refresh_token IS NOT NULL) FROM workflow_xeroapp;`
  and `SELECT xero_tenant_id FROM workflow_companydefaults;`
  A live-looking production token/tenant = leave services stopped and
  report immediately (scrubber-completeness finding, KAN-341 territory).
- [ ] 12. Start uat2 services;
  `curl -sk https://msm-uat2.docketworks.site/` returns 200.

## Phase 4 — verification battery (before dropping scratch)

- [ ] 13. `/opt/docketworks/repo/scripts/ops/db_schema_diff.sh dw_msm_uat2_scratch dw_msm_uat2`
  — expect exit 0 modulo `schema-known-deltas.txt`. Never edit the deltas
  file to make it pass; a real diff is a finding.
- [ ] 14. In the uat2 release dir as its instance user:
  `uv run python -m scripts.ops.validate_restored_data` — expect exit 0;
  nonzero output verbatim (violations are data fixes, never read-side
  fallbacks — ADR 0015).
- [ ] 15. `sudo /opt/docketworks/repo/scripts/server/verify-instance.sh msm uat2`
- [ ] 16. Cleanup: `sudo -u postgres dropdb dw_msm_uat2_scratch`;
  `rm /tmp/scrubbed_dw_msm_prod_20260829_135924.dump` (usable password
  hashes — deletion deliberate).

## Final report

Per-phase results, row-count parity summary, every check's exit status,
findings verbatim, both URLs' HTTP codes. The laptop side
(docketworks-v2-4f) then runs `smoke_api.sh` against msm-uat2, the
two-browser kanban smoke happens with Corrin, and the human screen-by-screen
comparison starts at the two URLs.
