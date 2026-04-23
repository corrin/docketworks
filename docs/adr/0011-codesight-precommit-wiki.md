# 0011 — Codesight runs via pre-commit in wiki mode; output committed

Commit `.codesight/` and `docs/.codesight/` to git and regenerate both on pre-commit via `--wiki` and `--mode knowledge` so AI-assistant context never drifts from the code it describes.

- **Status:** Accepted
- **Date:** 2026-04-10
- **PR(s):** [#134](https://github.com/corrin/docketworks/pull/134) — fix: WIP historical state, codesight setup, env variable rename

## Context

Codesight (`npx codesight`, v1.10.0) had been installed and run manually. Three `.codesight/` directories existed — root (full scan), `frontend/.codesight/` (frontend-only), and `docs/.codesight/` (knowledge mode over markdown docs) — all untracked, no config file, no `.codesightignore`. CLAUDE.md already referenced codesight wiki articles for the orient/verify workflow, so the AI-assistant context was actively depending on output that drifted whenever code changed without a manual re-run.

## Decision

Commit codesight output to git and regenerate it via pre-commit. Two hooks in `.pre-commit-config.yaml`: one runs `npx codesight --wiki` and stages `.codesight/`; the other runs `npx codesight --mode knowledge -o docs/.codesight` and stages `docs/.codesight/`. Always use `--wiki` (makes it the default via `codesight.config.json`) because the CLAUDE.md flow reads targeted ~200–300-token articles, not the monolithic `CODESIGHT.md`. Drop the separate `frontend/.codesight/` scan — the root scan already picks up 181 frontend components, so a second scan duplicates work and creates two sources of truth; gitignore `frontend/.codesight/` to prevent accidental commit. `.codesightignore` excludes generated files (`frontend/schema.yml`, `frontend/src/api/generated/`), build artifacts, and `docs/.codesight/` (which has its own scan).

## Alternatives considered

- **Pre-push hook instead of pre-commit:** too late — during development the committed `.codesight/` already diverged from the working tree, and AI assistants reading it would use stale context.
- **`codesight --watch`:** wasteful — runs on every file save; most saves don't change structural relationships.
- **Keep `.codesight/` untracked and rely on each developer running it:** what we had. It drifted. Assistants hit stale wiki articles.
- **Keep all three scans (root + frontend + docs):** the root scan already covers frontend; a second frontend scan is strictly redundant except for the knowledge/markdown scan, which genuinely uses a different mode flag.

## Consequences

- **Positive:** committed output means every developer and CI run gets the same context with zero setup; git diff reveals structural changes between commits; wiki mode makes articles small enough for selective loading by assistants.
- **Negative / costs:** pre-commit is slower (adds the codesight run on every commit); the output is effectively generated code that lands in the repo — reviewers see noise in diffs when module structure changes.
- **Follow-ups:** if the frontend ever diverges enough to warrant its own scan, reinstate `frontend/.codesight/` and remove it from gitignore; the `.codesight/` wiki is the AI-assistant context surface, so breaking changes to codesight output format affect how CLAUDE.md articles render.
