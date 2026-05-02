# 0008 — Frontend integrated as a git subtree (not submodule)

Pull the frontend repo into `frontend/` via `git subtree add` so backend + frontend share one history, one CI, one deploy script, and one PR for any cross-cutting change.

## Problem

Backend (`jobs_manager`) and frontend (`jobs_manager_front`) lived in separate GitHub repos. Any API-spanning change — add a field on the backend, consume it on the frontend — required two coordinated PRs, two CI runs, two deploys-in-lockstep. Dependabot ran twice. CI configuration drifted between the two repos. Reviewing a feature meant juggling two diffs.

## Decision

Use `git subtree add --prefix=frontend` to import the frontend into `frontend/`. Full history preserved, no submodule init step. Consolidate at the root: one `.gitignore`, one `ci.yml` running both stacks, one Dependabot config covering all three ecosystems (`pip`, `npm`, `github-actions`), one `deploy.sh` that builds both. Genuinely frontend-specific config (`.editorconfig`, `.prettierrc.json`, `.nvmrc`, `frontend/CLAUDE.md`, `frontend/.env.example`) stays in `frontend/`. Replace the old `simple-git-hooks` / husky setup with a `frontend-lint-staged` hook in the root `.pre-commit-config.yaml`.

## Why

A cross-cutting change (API field + frontend consumer) lands in one commit, runs through one CI, ships in one deploy. Reviewers see the full change in one diff. There's no "did the frontend land yet?" coordination problem. Subtree preserves history (unlike a fresh import) and works without contributor setup (unlike submodules — no `git submodule update --init`).

## Alternatives considered

- **Git submodule.** The default suggestion when integrating one repo into another. Rejected: requires every contributor (and every CI run) to remember `git submodule update --init`; a parent-repo commit pins a specific frontend SHA but cannot atomically include both halves of an API-spanning change.

## Consequences

One PR can change backend + frontend together; CI runs both on the same commit; `deploy.sh` ships everything. Cost: subtree history is flattened into the parent — contributors who only worked on the frontend lose the ability to clone just that repo; `git subtree pull/push` semantics are awkward if we ever want to split it back out.
