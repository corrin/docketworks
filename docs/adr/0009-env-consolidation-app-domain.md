# 0009 — Frontend resolves backend `.env` by convention; single `APP_DOMAIN` source

Frontend build and test tooling reads `APP_DOMAIN` from the backend `.env` (resolved by convention at `../.env`) and derives URLs + allowed hosts from it — eliminating three cross-file duplicated vars.

- **Status:** Accepted
- **Date:** 2026-03-31
- **PR(s):** [#111](https://github.com/corrin/docketworks/pull/111), [#112](https://github.com/corrin/docketworks/pull/112) — UAT backports round 3 (env consolidation); [#131](https://github.com/corrin/docketworks/pull/131) — E2E stability, WIP report, timesheet permissions, env consolidation

## Context

Backend and frontend each had a `.env`, and three values were duplicated: `VITE_FRONTEND_BASE_URL` (just `https://${APP_DOMAIN}`), `VITE_ALLOWED_HOSTS` (just `APP_DOMAIN`), and `BACKEND_ENV_PATH` (which the frontend used to find the backend's `.env`). Every UAT instance then needed four values kept in sync across two files. It drifted. An incident traced back to `VITE_ALLOWED_HOSTS` being stale after `APP_DOMAIN` changed.

## Decision

Frontend tooling resolves the backend `.env` by convention: it's always `../.env` relative to the frontend directory. Read `APP_DOMAIN` from there and derive the frontend URL (`https://${APP_DOMAIN}`) and allowed hosts at build/run time. Remove the three duplicated vars from `frontend/.env`, `frontend/.env.example`, the server instance template, and `env.d.ts`. Frontend `.env` keeps only the genuinely-frontend-only values: `VITE_UAT_URL` (admin-menu link), `VITE_WEEKEND_TIMESHEETS_ENABLED` (feature flag), E2E test credentials, Xero OAuth test credentials. `vite.config.ts` reads `APP_DOMAIN` inline (not via `db-backup-utils.ts`) to avoid a dependency from build tooling to test tooling.

## Alternatives considered

- **Keep duplication, add a validation script:** still two sources of truth, still drifts, script-forgotten-in-deployment is a new failure mode.
- **Single root `.env`, both sides read from it:** Vite expects `frontend/.env` for `VITE_*` vars; changing that means either renaming all frontend vars or a loader shim that fights Vite's convention.
- **Generate `frontend/.env` from backend `.env` at deploy time:** works but adds a deploy-time step, and dev machines then have two files that drift if the generator isn't re-run after a manual edit.

## Consequences

- **Positive:** one source for `APP_DOMAIN`; the UAT instance template is shorter; renaming an instance's domain in backend `.env` reaches everything automatically.
- **Negative / costs:** frontend tooling now assumes repo layout (`../` from `frontend/`) — any future repo reorg that breaks that path breaks the build. A stale reference to `VITE_FRONTEND_BASE_URL` somewhere in the codebase becomes a silent `undefined` rather than a duplicated value.
- **Follow-ups:** Task 8 of the source plan was a codebase-wide grep for stale references; repeat that if any new scripts get added.
