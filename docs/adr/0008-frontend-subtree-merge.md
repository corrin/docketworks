# 0008 — Frontend integrated as a git subtree (not submodule)

The frontend lives at `frontend/` via `git subtree` (imported with `--prefix=frontend`, the prefix any future `git subtree pull/push` must repeat); backend and frontend share one history, one CI, one deploy, one PR.

## Rules

- A cross-cutting change — a backend field plus its frontend consumer — lands in one commit, one PR, one CI run, one deploy. There is no cross-repo coordination step.
- Shared config lives at the root: one `.gitignore`, one `ci.yml` running both stacks, one Dependabot config (`pip`, `npm`, `github-actions`), one `deploy.sh`. Only genuinely frontend-specific config (`.editorconfig`, `.prettierrc.json`, `.nvmrc`, `frontend/CLAUDE.md`, `frontend/.env.example`) stays in `frontend/`.
- Frontend tooling reads the backend `.env` at `../.env` and derives its URL and allowed hosts from `APP_DOMAIN` at build time — there are no separate `VITE_FRONTEND_BASE_URL`/`VITE_ALLOWED_HOSTS` values to drift.
- Frontend hooks run from the root `.pre-commit-config.yaml` (`frontend-lint-staged`), not a separate husky setup.

## Do not

- **Submodules or a second repo** — submodules need `git submodule update --init` on every clone and CI run, and a parent commit pinning a SHA cannot land both halves of an API-spanning change atomically.
