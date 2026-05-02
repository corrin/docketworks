# 0011 — Codesight runs via pre-commit in wiki mode; output committed

Commit `.codesight/` and `docs/.codesight/` to git. Regenerate both on pre-commit via `npx codesight --wiki` and `npx codesight --mode knowledge`.

## Problem

CLAUDE.md and the agent workflow read targeted ~200–300-token codesight wiki articles to orient before making changes. If those articles are untracked or stale, every assistant ingestion uses outdated context — old module names, old function signatures, old relationships. Manual regen drifts the moment someone forgets. AI guidance has to match the code, every commit, or the guidance is misinformation.

## Decision

Two pre-commit hooks in `.pre-commit-config.yaml`: one runs `npx codesight --wiki` and stages `.codesight/`; the other runs `npx codesight --mode knowledge -o docs/.codesight` and stages `docs/.codesight/`. Wiki mode is the default via `codesight.config.json`. `.codesightignore` excludes generated files (`frontend/schema.yml`, `frontend/src/api/generated/`), build artefacts, and `docs/.codesight/` (which has its own scan). Drop the separate `frontend/.codesight/` scan — the root scan already covers frontend; gitignore that path to prevent accidental commit.

## Why

Pre-commit is the one place where "code state" and "context derived from code state" are guaranteed to ship together. Committing the output means every developer and every CI run gets identical context with zero setup; `git diff` reveals structural changes between commits. Wiki mode produces small, selectively-loadable articles instead of a monolithic dump — a key fit for context-window-bounded assistants.

## Alternatives considered

- **`codesight --watch` in dev.** Defendable — keeps context fresh without commit-time overhead. Rejected: most file saves don't change structural relationships, so it burns CPU continuously; it also doesn't help CI or other contributors who don't run watch.
- **Keep `.codesight/` untracked, regenerate per developer.** What we had. Rejected: drifted in practice; assistants hit stale articles; no way to detect the drift without regenerating.

## Consequences

Every commit ships matching context. Cost: pre-commit is slower (adds the codesight run on every commit); the output is effectively generated content that lands in git, so reviewers see noise in diffs when module structure changes.
