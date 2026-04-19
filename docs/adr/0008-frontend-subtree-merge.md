# 0008 — Frontend integrated as a git subtree (not submodule)

Pull the frontend repo into `frontend/` via `git subtree add` so backend + frontend share one history, one CI, one deploy script, and one PR for any cross-cutting change.

- **Status:** Accepted
- **Date:** 2026-03-15
- **PR(s):** Commit `26964bfc` — "Migrate frontend config into root and clean up duplicates" (the subtree-add commit itself predates this; part of the broader repo-rename to `docketworks`)

## Context

Backend (`jobs_manager`) and frontend (`jobs_manager_front`) lived in separate GitHub repos. Deploys had to keep the two in lockstep, CI jobs were duplicated across repos, dependabot PRs came from two places, and a change that spanned the API boundary (add a field, consume it) needed two coordinated PRs. We wanted one repo, one history, one CI, one deploy script.

## Decision

Use `git subtree add --prefix=frontend` to import the frontend repo into `frontend/`. Full history is preserved, no submodule gymnastics, no special clone step for contributors. Consolidate config at the root: merge `.gitignore`, fold frontend CI jobs into the root `ci.yml`, combine dependabot ecosystems (`pip` at root, `npm` under `/frontend`, `github-actions` at root), delete the frontend's separate `cd.yml` (root `deploy.sh` builds both), keep genuinely frontend-specific config (`.editorconfig`, `.prettierrc.json`, `.nvmrc`, `frontend/CLAUDE.md`, `frontend/.env.example`) in `frontend/`. Replace the old `simple-git-hooks` + husky setup with a `frontend-lint-staged` hook inside the root `.pre-commit-config.yaml` so there's one pre-commit toolchain.

## Alternatives considered

- **Git submodule:** requires `git submodule update --init` for every contributor; commits in the parent repo point to specific frontend SHAs and cannot atomically include both halves of an API-spanning change.
- **Side-by-side repos with a meta-repo for tooling:** three repos instead of one; still need two PRs for cross-cutting changes.
- **Subtree split with separate deploy cadence:** we explicitly want lockstep — the whole point is to make cross-cutting changes atomic.

## Consequences

- **Positive:** one PR can change backend + frontend together; CI runs both on the same commit; dependabot covers both ecosystems in one workflow; `deploy.sh` at root builds frontend from `frontend/` and ships everything together.
- **Negative / costs:** subtree history is flattened into the parent repo — contributors who worked on only the frontend lose the ability to clone just that repo; `git subtree pull` / `push` semantics are awkward if we ever want to split it back out.
- **Follow-ups:** archive the old `jobs_manager_front` repo with a README pointing at this one; GitHub secrets and branch protection had to be configured on `docketworks` (done manually).
