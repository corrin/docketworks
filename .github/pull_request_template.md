## 📝 Description

_What this changes and why._

## 🔗 Related issue

_Link the issue/ticket this addresses (if any)._

## 🚀 Changes

- Bullet list of the user-visible or structural changes.
- …

## ✅ Checklist

**Backend (Python / Django)**

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy` passes — strict, zero baseline (no new `Any`, no shotgun `# type: ignore`)
- [ ] `uv run lint-imports` passes (layer contract)
- [ ] `uv run deptry .` passes
- [ ] `uv run pytest` passes; coverage ratchet not lowered
- [ ] Searched for an existing implementation before adding a new one (one impl per concept)
- [ ] Guard-clause shape: unhappy path first; non-trivial branches have an explicit `else`
- [ ] Every `try` has a reason: handlers persist via `persist_app_error(...)` and re-raise

**Frontend (React / Vite)**

- [ ] `npm run lint` (oxlint) and `npm run format:check` (prettier) pass
- [ ] `npm run type-check` passes
- [ ] `npm run test:unit` passes
- [ ] `npm run gen:api` produces no diff (generated client is current)
- [ ] `npm run check:boundary` passes (server state stays in TanStack Query)
- [ ] `npm run build` succeeds

**Definition of done**

- [ ] Browser console checked for relevant warnings/errors
- [ ] Django/Celery logs checked for relevant warnings/errors
- [ ] Affected business workflow regression-tested (E2E where applicable)
- [ ] Intentional v1→v2 API/URL differences recorded in `docs/accepted-api-differences.yml`

See [`CLAUDE.md`](../CLAUDE.md) for the standards these gates enforce.
