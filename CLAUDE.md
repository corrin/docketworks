# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. `AGENTS.md` is a symlink to this file so Codex, Cursor, and other agents that follow the cross-tool convention see the same instructions — edit this file, not the symlink.

## Architectural decisions

Major architectural decisions are recorded in [`docs/adr/`](docs/adr/README.md). Read the ADR index before non-trivial work — the codebase deviates from typical Django/Vue defaults in deliberate ways that aren't reconstructable from the code alone. The most operationally consequential ADRs:

- **0017** — Zero backwards compatibility: when a name, URL, or shape changes, every caller changes in the same PR. No deprecation aliases, no `getattr` shims, no "for safety" columns.
- **0019 + 0001** — Every exception is persisted to `AppError` (0019); nested handlers re-raise via the `AlreadyLoggedException` two-arm dedup pattern (0001).
- **0015** — When a consumer finds malformed data, fix the data (migration). Consumers stay strict; never add a read-side fallback.
- **0020** — Backend owns data, calculations, and external systems; frontend owns presentation. The boundary is the kind of value, not the layer of code.
- **0021** — Frontend reads/writes the API only via the generated client; raw `fetch`/`axios` is forbidden.

CLAUDE.md is the operational layer (session behaviour, code-style gotchas, architecture facts). ADRs explain *why*.

## Purpose-first responses

Understand the purpose behind the user's request and answer with that purpose in mind, not just the literal wording. A response that is technically true but does not help with the underlying goal is incomplete.

If the intended outcome cannot be achieved because of missing access, missing context, an environment issue, or another technicality, do not stop at the technicality. State the blocker briefly, explain its impact on the goal, and take the nearest useful next step or ask for the specific missing detail needed to proceed.

Examples:
- If asked for a screenshot of an authenticated page and the browser lands on login, the useful answer is that authenticated access is needed and what can be done next, not merely that a login screenshot was captured.
- If asked whether a bug is fixed, verify the behavior that matters to the user, not only that a unit test passed.
- If asked to review a proposal, assess whether it solves the problem and what risks remain, not only whether the text is internally consistent.

## Tokens are precious

Every single line in CLAUDE.md will make agents worse at unrelated tasks.  Every single word must have significant lasting benefit or it must not be added.  Do not repeat yourself, do not add lines even if you screw up, if it is unlikely a similar screw up will happen again.  Always give the most general fix, to increase the likelihood the guidence is future-directed.


## Frontend

The frontend is a Vue 3 + TypeScript app in `frontend/`. It lives in the same repo but has its own `CLAUDE.md` at `frontend/CLAUDE.md` with its own rules and conventions.

**When working on frontend code**, spawn a subagent scoped to the `frontend/` directory. The frontend has different tooling (npm, Vue, TailwindCSS, shadcn-vue) and conventions from the Django backend — a subagent keeps context focused and avoids cross-contamination.

**Backend ↔ Frontend boundary:** API contracts are defined in the OpenAPI schema. If the frontend needs a new endpoint or data shape, write requirements as spec documents (in `docs/plans/`) and present them to the user.

---

## Architecture Overview

### Core Application Purpose

Django-based job/project management system for jobbing shops and custom work businesses. Originally built for Morris Sheetmetal, now sold to multiple clients — one installation per client. Each instance has its own CompanyDefaults, branding, and integrations. Digitizes paper-based workflows from quote generation to job completion and invoicing.

### Django Apps Architecture

- **`workflow`** - Central hub, Xero integration, auth middleware
- **`job`** - Job lifecycle, Kanban status tracking (Quoting → In Progress → Completed → Archived), audit trails
- **`accounts`** - Custom Staff model extending AbstractBaseUser, authentication
- **`client`** - Customer management, bidirectional Xero contact sync
- **`timesheet`** - Time tracking, billable/non-billable, wage rates
- **`purchasing`** - POs, stock management, Xero integration, links to CostLine via ext_refs
- **`accounting`** - KPIs, financial reporting, invoice generation
- **`quoting`** - Quote generation, supplier pricing, AI price extraction (Gemini)

### Database Design Patterns

**Core Relationships:**

```
Job → CostSet (1:many) → CostLine (1:many)
PurchaseOrder → PurchaseOrderLine → Stock → CostLine
Staff → CostLine (time entries)
Client → Job (1:many)
```

**Key Design Patterns:**

- UUID primary keys throughout for security
- SimpleHistory for audit trails on critical models
- Soft deletes where appropriate
- JSON ext_refs for flexible external references (stock, purchase orders)
- JSON meta for entry-specific data (structure varies by CostLine kind - see below)
- Bidirectional Xero synchronization with conflict resolution
- `accounting_date` field on CostLine for proper KPI reporting

**CostLine Meta Field Structure:**

TIME entries (kind='time'):
- staff_id (str, UUID): Reference to Staff member
- date (str, ISO): Date work performed (legacy - use accounting_date field instead)
- is_billable (bool): Whether billable to client
- wage_rate_multiplier/rate_multiplier (float): Rate multiplier (e.g., 1.5 for overtime)
- note (str): Optional notes
- created_from_timesheet (bool): True if from modern timesheet UI
- wage_rate, charge_out_rate (float): Rates at time of entry

MATERIAL entries (kind='material'):
- item_code (str): Stock item code reference
- comments (str): Notes about material usage
- source (str): Origin ('delivery_receipt' for PO deliveries)
- retail_rate (float): Retail markup rate (e.g., 0.2 for 20%)
- po_number (str): Purchase order reference
- consumed_by (str): What consumed this material

ADJUSTMENT entries (kind='adjust'):
- comments (str): Explanation of adjustment
- source (str): Origin ('manual_adjustment' for user-created)

## Development Workflow

### Git and PR policy

- **Never commit directly to `main`.** Every change, including urgent hotfixes,
  documentation edits, and operational fixes, must be committed on a branch and
  merged via PR.
- Relatively large PRs are acceptable, and a PR may include a few unrelated
  fixes when that is the pragmatic path, but direct-to-main commits are banned.
- Before committing, check the current branch. If it is `main`, create or switch
  to a branch first.
- Do not leave uncommitted changes behind at the end of a task. If the change is
  complete and scoped, commit it on the current branch. If the scope is unclear,
  mixed with unrelated work, or the user may not want it committed, ask before
  committing.

### Code Style and Quality

- **Black** (line length 88) and **isort** for Python formatting
- **MyPy** with strict configuration for type safety (see "Backend type-check gate" below)
- **Flake8** and **Pylint** for linting with Django-specific rules
- **NEVER run `tox -e format`** — use pre-commit instead (different settings, different results)
- **NEVER edit `__init__.py` directly** — autogenerated. Run `python scripts/update_init.py` after adding/removing Python files
- **Codesight files** in `.codesight/` and `docs/.codesight/` are regenerated by pre-commit and ride with the commit — don't hand-edit

### Backend type-check gate

`bash scripts/check_mypy.sh` is the **authoritative** backend type check — the only supported way to run mypy. It runs full-strict mypy (config in `pyproject.toml` `[tool.mypy]`) and filters through `mypy-baseline.txt`, which records the historical type debt being burned down ticket by ticket. CI (`backend-type-check` job) and the pre-push hook both run it.

Ratchet rules:

- CI blocks any mypy error not in `mypy-baseline.txt` — new code must be fully type-clean under strict mode.
- **Never hand-add entries to `mypy-baseline.txt`.** The baseline only shrinks.
- After fixing baselined errors, run `poetry run mypy apps/ docketworks/ | poetry run mypy-baseline sync` and commit the shrunken baseline in the same PR.
- `# type: ignore[code]` requires the specific error code and a justification comment on the same line.

### Defensive programming

ADR 0015 (fix data, not fallback) and ADR 0017 (zero backwards compatibility) are the architectural posture. Day-to-day style:

- Check the bad case first (`if <bad>: handle_error()`); validate required inputs upfront and crash if missing; no defaults that mask configuration or data problems.
- Prefer an explicit `else` on non-trivial `if`s — even a commented no-op (`else: pass  # handled by guard above`) is clearer than silent fallthrough. Trivial early-return guards are exempt.
- Trust the data model. When you find malformed data, fix the data (migration); don't soften the consumer (ADR 0015).

### Mandatory error persistence

Every exception handler persists once via `persist_app_error(exc)` (ADR 0019) and re-raises through the two-arm dedup pattern (ADR 0001).

```python
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

try:
    operation()
except AlreadyLoggedException:
    raise  # already persisted upstream — pass through unchanged
except Exception as exc:
    err = persist_app_error(exc)  # MANDATORY
    raise AlreadyLoggedException(exc, err.id) from exc
```

## Environment Configuration

See `.env.example` for required environment variables. Key integrations: Xero API, Dropbox, PostgreSQL. Frontend tooling reads `APP_DOMAIN` from the backend `.env` at `../.env` and derives URLs from it (see ADR 0008's Consequences). Deploy uses `scripts/server/deploy.sh` (per-instance `<client>-<env>`); it also runs on boot via systemd so a cold machine catches up to `main`.

## Migration Management

- Keep migrations small and reviewable; include forward and (where feasible) reverse logic.
- Prefer schema changes over code workarounds that mask data shape issues.

## Critical Architecture Guidelines

### Frontend/Backend separation

See ADR 0020. Backend owns data, calculations, and external systems; frontend owns presentation. The boundary is the kind of value: anything involving the DB, business rules, or external systems → backend; static UI constants, layout, and ergonomics → frontend.

### Service Layer Patterns

- Keep business logic in explicit service classes; keep views thin.

## E2E Test Runs

`npm run test:e2e` (from `frontend/`) runs Playwright tests against live HTTP endpoints. The suite takes ~20–25 min.

**CRITICAL: The global teardown (`global-teardown.ts`) MUST always run to completion.** It restores the database from backup, saves/reinjects Xero tokens, removes the lock file, and runs integrity checks. If the bash process is killed (timeout, SIGTERM, etc.) the teardown never executes and the database is left polluted with `[TEST]` data.

- **Never set a bash timeout on the E2E command.** A timeout (or SIGTERM) kills the node process before Playwright calls `globalTeardown`, leaving the DB polluted with `[TEST]` data and a stale lock file. The teardown is NOT a signal handler — it only fires on normal exit.
- Run E2E in the foreground by default from `frontend/`: `PATH=/home/corrin/src/docketworks/.venv/bin:$PATH npm run test:e2e`. The output is manageable, and foreground execution avoids detached-process wrapper issues while still letting Playwright call `globalTeardown` on normal completion. The backend venv must be on PATH because setup/reset scripts invoke `python`.
- If an agent must deliberately detach the run, get explicit approval/confirmation for the unsandboxed launch (for example the `--confirm`/approval path) and use a new session: `setsid -f sh -c 'cd /home/corrin/src/docketworks/frontend && npm run test:e2e > /tmp/e2e-output.log 2>&1'`. Plain `nohup npm run test:e2e > /tmp/e2e-output.log 2>&1 &` can be killed when the wrapper exits, even though it looks detached.
- The E2E lock file is a safety mechanism, not housekeeping. It prevents unsafe concurrent runs and records the backup path needed by teardown. Do not delete it casually; if it is stale, follow the recovery/reset flow below or `global-teardown.ts` step for step.
- If pre-flight reports leftover `[TEST]` data, run the reset script with confirmation: `npm run test:e2e:reset -- --confirm`. If the shell has not activated the backend venv, prepend it to PATH because the reset script invokes `python`: `PATH=/home/corrin/src/docketworks/.venv/bin:$PATH npm run test:e2e:reset -- --confirm`.
- To review E2E timing history after runs, use `npm run test:e2e:trends` from `frontend/`; it reads `frontend/test-history/test-runs.csv` and writes `frontend/test-history/e2e-per-test-plots.html`.
- If the teardown does get skipped: save the current Xero token, restore from `restore/e2e/backup_*.sql`, reinject the token, sync sequences, then delete the lock and backup. Match `global-teardown.ts` step for step.
