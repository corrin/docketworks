# 0064 — A deployed instance is verified by the E2E suite on a copy of its database, against the fake Xero, with users fenced out

`verify-instance.sh --e2e` points an instance's units at a copy of its live database held in its scrub database, runs the unmodified suite at the instance's own domain through nginx with the fake Xero, and empties the copy afterwards; the live database is only ever read, the real organisation is never reached, and the run verifies a deployment, never a merge.

## Rules

- **The suite never runs on a live instance database.** `manage.py scrub_copy load` pipes
  `pg_dump` of the live database into `pg_restore` on the instance's `dw_<client>_<env>_scrub`
  database (the plumbing `backport_data_backup` already had), the units are restarted under a
  window env whose `DB_NAME` is the copy, and `scrub_copy empty` drops it when the run ends,
  whatever the run did. A production database is therefore never written and never wiped
  (ADR 0048's sanctioned wipe is not needed); UAT verification and production PVT are the
  same command, `--production` being the one explicit assertion a prod instance requires
  because the run takes it offline.
- **Xero on a server is always the fake (ADR 0060), seeded from the copy.** The copy is not a
  production database by name, which is the one signal ADR 0048 trusts, so the fake's
  refusal needs no new assertion. Real Xero on a server was rejected because a refresh during
  the run rotates the single-use refresh token inside the copy and disconnects the live
  instance when the copy is dropped; the fake's refresh route hands the stored token back.
  What a server run proves is the deployed release on its box with its data — nginx, TLS,
  gunicorn, Celery, migrations, the SDK layer against the simulation. The vendor is proven at
  merge, on a workstation, against the real thing (ADR 0050).
- **Users are fenced out for the window.** nginx answers 503 to every client but the box
  itself while `<instance>/e2e/fence.conf` exists, because anything a user did during the run
  would land in the copy. The fence stays up until the solo cache has expired after the units
  return to the live database, so no `CompanyDefaults` edit a spec made is ever served to a
  real user. A production run is a declared window; `docs/release-process.md` says so.
- **The harness is one implementation on every host.** It reaches the app at its public
  origin like the browser does, reads the env file `DOCKETWORKS_ENV_FILE` names, writes every
  artifact under `E2E_STATE_DIR`, and spawns management commands through the release's own
  interpreter — all defaulting to the workstation layout, so `run_e2e.sh` is unchanged. Rows
  a production dump never held come from `manage.py e2e_ensure_fixtures`, which the restore
  runbook and the server run both call.
- **A server run says so.** Its last line names the fake and the copy and says it is not a
  merge gate; ADR 0060's labelling (`xero=fake` history rows, the `(FAKE XERO)` organisation
  name) applies unchanged. Merge readiness is still `./scripts/ops/run_e2e.sh` with no switch
  plus the integration tier.

## Do not

- **Run the suite against a live instance database with the harness's own dump and restore** —
  that is a second wipe path on production and a restore that races every user, when the
  scrub database already exists to hold a disposable copy.
- **Reach for `XERO_READONLY` for a server run** — it suppresses the writes the specs exist
  to prove, refuses the cleanup, and is the production hotfix valve (ADR 0050).
- **Read a green server run as evidence for merge** — it proves the deployment against what
  the vendor said last time it was asked (ADR 0060).
