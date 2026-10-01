# 0064 — A deployed instance is verified by the E2E suite on a copy of its database, against the fake Xero, with users fenced out

`verify-instance.sh --e2e` points an instance's units at a copy of its live database held in its scrub database, runs the unmodified suite at the instance's own domain through nginx with the fake Xero, and empties the copy afterwards; the live database is only ever read, the real organisation is never reached, and the run verifies a deployment, never a merge. How it runs is `docs/server_setup.md`.

## Rules

- **The suite never runs on a live instance database.** The copy is `dw_<client>_<env>_scrub`, the units run under a window env whose `DB_NAME` is the copy, and the copy is dropped when the run ends whatever the run did. A production database is therefore never written and never wiped; UAT verification and production PVT are the same command, `--production` being the one explicit assertion a prod instance requires because the run takes it offline.
- **Xero on a server is always the fake (ADR 0060), seeded from the copy.** Real Xero was rejected because a refresh during the run rotates the single-use refresh token inside the copy and disconnects the live instance when the copy is dropped. A server run proves the deployed release on its box with its data; the vendor is proven at merge, on a workstation, against the real thing (ADR 0050).
- **Queues and channels are named by the database.** The copy and the live database share the instance's Redis, so `CELERY_TASK_DEFAULT_QUEUE` and `DATA_VERSIONS_CHANNEL` carry the database name: work the live instance queued before the fence waits in its own queue and runs when the units return, and the teardown purges only the copy's.
- **The harness is one implementation on every host.** It reaches the app at its public origin like the browser does, reads the env file `DOCKETWORKS_ENV_FILE` names, writes every artifact under `E2E_STATE_DIR`, and spawns management commands through the release's own interpreter — all defaulting to the workstation layout, so `run_e2e.sh` is unchanged. Rows a production dump never held come from `manage.py e2e_ensure_fixtures`.
- **A server run says so.** Its last line names the fake and the copy and says it is not a merge gate; merge readiness is still `./scripts/ops/run_e2e.sh` with no switch plus the integration tier.

## Do not

- **Run the suite against a live instance database with the harness's own dump and restore** — a second wipe path on production and a restore that races every user, when the scrub database already exists to hold a disposable copy.
- **Read a green server run as evidence for merge** — it proves the deployment against what the vendor said last time it was asked (ADR 0060).
