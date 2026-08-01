# CLAUDE.md — Docketworks v2

Full rewrite of `../docketworks` (v1) with no functional changes. The approved plan lives at
`/home/corrin/.claude/plans/the-docketworks-project-docketworks-cozy-steele.md`; read it before non-trivial work.

## The prime rule: search before implement

v1 rotted because AI sessions wrote "remarkably similar" parallel implementations instead of
finding the existing one. In v2, **before writing any new function, component, service, or
endpoint, search for an existing implementation of the concept** (`grep`/Glob across `apps/` or
`frontend/src/`). One implementation per concept — if you find a near-match, extend or generalise
it; never write a sibling. When porting from v1, first check whether the v1 code has divergent
siblings and port exactly one canonical behaviour (ask the user to arbitrate if the divergence is
user-visible).

## Layout (one obvious home per concept)

- Backend: `config/` (settings, celery beat-in-code, the single NinjaAPI) and `apps/` —
  `core` (errors, etag, envelope, auth, middleware) ← domain apps (job, accounts, company, crm,
  purchasing, quoting, accounting, timesheet, operations, process) ← integrations
  (xero, ai, search, diagnostics). Enforced by import-linter.
- Frontend: `frontend/src/routes/` (thin) → `features/<domain>/` → generated API layer + `lib/`.
  Server state lives in TanStack Query only; no hand-written service layer.

## Gates (all on from day 1 — never weaken, never baseline)

- `uv run ruff check .` && `uv run ruff format .`
- `uv run mypy` — strict, ZERO baseline. New code must be fully type-clean; no `Any`, no
  shotgun `# type: ignore` (specific error code + justification only).
- `uv run lint-imports` — layer contract in pyproject.toml.
- `uv run pytest`
- Pre-commit runs all of the above; do not bypass with `--no-verify`.

## Porting rules

- Models keep v1 app labels and class names; models moved out of v1's `workflow` app pin
  `Meta.db_table = "workflow_<modelname>"`. No renames in v2.0 — data migrates by pg_dump/restore.
- `delta_checksum` canonicalisation is bit-identical between Python and TypeScript (golden vectors).
- Exact-URL parity only where an external party holds the URL: Xero OAuth redirect, Xero webhook,
  CRM phone ingestion, ServiceApiKey consumers. Everything else may drift; the parity ledger
  records intentional differences.
- Tests port only if they assert real business behaviour; drop tests that mirror implementation
  text or enshrine a v1 divergence.
