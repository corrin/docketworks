# 0009 — Frontend resolves backend `.env` by convention; single `APP_DOMAIN` source

Frontend build and test tooling reads `APP_DOMAIN` from the backend `.env` (resolved by convention at `../.env`) and derives URLs and allowed hosts from it.

## Problem

Backend and frontend each had a `.env`. Three values were duplicated across them: `VITE_FRONTEND_BASE_URL` (just `https://${APP_DOMAIN}`), `VITE_ALLOWED_HOSTS` (just `APP_DOMAIN`), and `BACKEND_ENV_PATH` (the frontend's pointer to the backend `.env`). Every UAT instance had four values to keep in sync across two files. They drifted. An incident traced back to `VITE_ALLOWED_HOSTS` being stale after `APP_DOMAIN` was changed in the backend `.env`.

## Decision

Frontend tooling resolves the backend `.env` at `../.env` by convention. Read `APP_DOMAIN` from there, derive frontend URL and allowed hosts at build/run time. Remove the three duplicated vars from `frontend/.env`, `frontend/.env.example`, the server instance template, and `env.d.ts`. `frontend/.env` keeps only genuinely-frontend-only values (feature flags, E2E credentials, OAuth test creds). `vite.config.ts` reads `APP_DOMAIN` inline so build tooling has no dependency on test tooling.

## Why

Single source of truth for `APP_DOMAIN`. Renaming an instance's domain in the backend `.env` reaches the frontend automatically. The UAT instance template gets shorter. A stale reference becomes a structural impossibility because the variable doesn't exist on the frontend side anymore.

## Alternatives considered

- **Single root `.env`, both sides read from it.** The default monorepo answer. Rejected: Vite expects `VITE_*` vars in `frontend/.env`; changing that means either renaming all frontend vars or maintaining a loader shim that fights Vite's convention.
- **Generate `frontend/.env` from backend `.env` at deploy time.** Defendable — keeps Vite's convention untouched. Rejected: dev machines then have two files that drift if the generator isn't re-run after a manual edit, and any deploy that skips the generation step ships stale values.

## Consequences

One source for `APP_DOMAIN`. Frontend tooling now assumes repo layout (`../` from `frontend/`); any future repo reorg that breaks that path breaks the build.
