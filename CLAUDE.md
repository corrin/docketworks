# CLAUDE.md — Docketworks

The full rewrite of `../docketworks_v1` (v1) shipped: production has run this codebase since
2026-08-29, and [`docs/release-process.md`](docs/release-process.md) is how a change reaches
it. The approved plan lives at
`/home/corrin/.claude/plans/the-docketworks-project-docketworks-cozy-steele.md`.
**Work is tracked in two places and you check both.** A Jira ticket (KAN) is the authority
wherever one exists — it carries the reproduction, the evidence and the acceptance criteria.
Everything with no ticket — the tail of the port, cross-cutting debt, seams left inside
completed slices, and decisions waiting on the owner — lives in
**[`docs/rewrite-status.md`](docs/rewrite-status.md)**; read it before picking up work, and
update it at the end of every slice. **That file only shrinks:** it holds tasks and nothing
else, and finished work is deleted the moment it is finished. Anything worth recording that
is NOT a task — a ruling, a finding, a measurement — goes to
[`docs/rewrite-history.md`](docs/rewrite-history.md), never into the task list. Session
transcripts are not durable; those files, the parity ledger, the ADRs, the cutover record
and code-level seam comments are.
Architectural decisions live in [`docs/adr/`](docs/adr/README.md) (carried forward from v1, numbering
continuous) — read the index before non-trivial work; ADRs win over habit.

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

## Git discipline: commit completed slices immediately

Commit each coherent, verified slice as soon as it is complete. Do not leave
finished work uncommitted while starting another task or handing the workspace
back to the user: this repository is often shared by concurrent agents, and a
mixed worktree makes later ownership ambiguous. Stage explicit paths, never
silently include unrelated changes, and push when the user has requested
publication. A successful unit-test run is normally a commit boundary: commit
the milestone it verified before continuing, so one PR will usually contain
multiple incremental commits. If a required generated artifact contains
another workstream's changes, use partial staging or stop and report the overlap
before committing.

Tiers are split on membership, not on speed. **The commit tier is exactly what
CI runs**, so a green commit predicts a green CI run; a check CI performs and
this tier omits is a bug in the tier, never a saving. The push tier holds what
CI does not run — it is a registry, so one command rediscovers every custom
check that already exists instead of a session writing a second script that
does the same thing. Slowness argues for making a check faster, never for
filing it where it will not run.

| tier | what runs | cost | command |
|---|---|---|---|
| **commit** | everything CI runs: ruff, ruff-format, mypy, import-linter, find-duplicates, deptry, exported schema, status table, code-quality metrics, delta goldens, frontend lint/format/boundary/type-check/audit, generated-client-current, server suites | ~64s | automatic on commit |
| **push** | what CI does not run — today just makemigrations | ~5s | automatic on push |
| **unit** | the Python suite | ~152s | `uv run pytest` |
| **integration** | the real Xero/LLM/Maps/Drive/phone calls, the outbound-link probe (`scripts/ops/outbound_links_probe.py`: every URL and vendor id the app emits, asked with the instance's credentials) and its inverse, route reachability (`scripts/checks/route_reachability.py`: every route the app serves is a navigation target somewhere inside it) | ~1min | `./scripts/ops/run_integration_tests.sh` |
| **e2e** | Playwright | ~25min | `npm run test:e2e` |

**Nothing that touches an external system merges without an integration test
(ADR 0050).** A fake provider is our belief about a vendor encoded as a test —
it can only confirm what we already assumed, which is how a payroll path that
could not post at all passed the unit suite, strict mypy and a green E2E spec.
The `integration` marker is deselected from `uv run pytest` and never runs in
CI, because CI has no sandbox credentials and must stay hermetic; the command
above is how it gets run, and it is a merge gate rather than an optional extra.
`XERO_READONLY` is a **production hotfix valve** and must never be set for a
test run — it suppresses exactly the writes these tests exist to prove.

For an unattended full E2E gate, especially after an agent coding session, run
`./scripts/ops/run_e2e.sh` from the repository root. It refuses an existing environment, resets
recognised E2E data, owns the full five-service stack, restores the database, and stops only the
processes it started. Use bare `npm run test:e2e` only when intentionally targeting an environment
that is already running.

Keep the loop short: `-n auto --dist loadscope` is the pytest default (in
`addopts`), so never add it by hand and never run the suite serially. Scope
harder while iterating — `uv run pytest apps/job` beats the full run, and
`--lf` reruns only last failures. On the frontend the loop check is
`npm run type-check`, **not** `npm run build`: the build adds a full Vite bundle
that tells you nothing a type error would not.

```shell
pre-commit run --all-files                        # the CI set
pre-commit run --all-files --hook-stage pre-push  # the CI set plus what CI omits
```

**Done means the E2E spec passes.** A slice with green unit tests and no spec is
not ported — report progress as specs green, never as endpoints or components
written. Nothing releases without the suite green. The tiers above catch
*structure* (duplication, layering, types) and the unit suite catches
behaviour within a layer; only E2E catches behaviour ACROSS layers — the
user-visible path through frontend, wire contract and backend — and that is
where this port's bugs have been. During 2–4 Aug ruff, mypy and
import-linter were all running while the debt that cost three days to clear
accumulated anyway — so speed is made safe by the spec shipping with the slice,
not by adding another linter.

- `uv run mypy` — strict, ZERO baseline, covers `apps config manage.py scripts`.
  New code must be fully type-clean; no `Any`, no shotgun `# type: ignore`
  (specific error code + justification only).
- A local hook is **not** the gate — it can be skipped with `--no-verify` or
  never installed. **CI runs every check in every tier except integration**,
  and that is what gates. The tiers exist so the commit loop mirrors CI and no custom check goes
  unfound; moving a hook between them is a one-word `stages:` edit. Integration is the
  one exception, and it is a deliberate one: CI has no sandbox credentials and
  must stay hermetic, so that tier is a **human-run merge gate** — the command
  above, run before merge, not an optional extra. It is the only gate this repo
  cannot automate, which is exactly why it is written down twice.
- Do not bypass with `--no-verify`.
- `docs/code-quality.md` is generated and committed: suppression counts,
  try/except shapes, optional returns. Not all are meant to be zero — the point
  is that a change which moves one shows that movement in its own diff. Only
  `passthrough` (a `try` whose handler just re-raises) is pinned at zero.

## Coding standards (ADRs 0015, 0017, 0028, 0032, 0038, 0039, 0043, 0046 are the authority)

- **A GET never writes.** Safe methods read; they do not create, update or
  delete — not a row, not a default, not "just" a singleton. This is not about
  idempotence (ADR 0001 and 0024 mean something else): a GET that writes makes
  reading a report change the database, and makes a monitoring probe a mutation.
  `CompanyDefaults.get_solo()` is the live example — django-solo ships it as
  `get_or_create`, ~12 services call it, and several are reached from GET report
  endpoints, so it is overridden in `apps/core/models.py` to read only.
- **Fail early.** Check the bad case first (`if <bad>: raise`); validate
  required inputs upfront and crash if missing; no defaults that mask
  configuration or data problems. When a consumer meets malformed data, fix
  the data (migration) — never add a read-side fallback (ADR 0015).
- **Guard-clause shape.** Unhappy path first, early return/raise. Never wrap
  the happy path in `if` and let the unhappy path fall through silently —
  `if ok: do_thing()` with no else-branch is a bug, not a style choice.
  Non-trivial branches get an explicit `else`. Errors are transparent after
  authentication (ADR 0038); anonymous responses use the fixed public contract.
- **Every unexpected handler persists.** A `try` needs a reason: convert an
  expected refusal into a typed outcome, reshape the error, or persist it with
  business context. Unexpected handlers call `persist_app_error(exc,
  AppErrorContext(...))` (apps/core/errors.py) and re-raise; expected catches
  carry a site-specific `deliberate-swallow` reason; converted exceptions chain
  the cause (`raise X from exc`).
- **Type annotations are data contracts (ADR 0028).** No `Any` as an escape
  hatch, no fake `| None`, no broad unions or casts to silence the checker.
  Complex inline types get a named type (dataclass, TypedDict, Protocol).
  `dict.get()` fallbacks and `hasattr` probes are smells — validate, then
  access directly.
- **DRY is structural (ADR 0039).** One implementation per concept; search
  before implement; extending a near-match beats writing a sibling.
- **Prefer libraries to DIY (ADR 0032).** Writing your own for something a
  maintained library provides needs an explicit, recorded reason it is not a
  library.
- **One LLM gateway (ADR 0041).** Every AI call — extraction, chat, MCP,
  supplier enrichment, quote-to-PO — goes through `apps/ai`'s LiteLLM-backed
  client. Never import a vendor SDK (`genai`, `mistralai`, `anthropic`) from a
  feature; v1 grew four parallel clients that way.
- **Unset is NULL (ADR 0040).** Nullable text columns never store `""`. The
  request schema declares such fields nullable-and-nonblank via the shared
  `NullableText` type, so a blank string is a 422 before the database and
  `null` is how a client clears a value; services never coerce with
  `value or None`.
- **Comments record the rejected alternative (ADR 0043).** A comment tells the
  reader what the code cannot: which obvious alternative was rejected and what
  fact rejected it. Delete code-to-English narration and review-feedback
  echoes — record the constraint, not the conversation. Every rationale an AI
  originates starts with its short model family (`GPT:`, `Opus:`, `Gemini:`)
  until explicit owner ratification replaces it with a durable authority
  citation (ADR 0051); attribution is provenance, never a waiver.

## Porting rules

- Models keep v1 app labels and class names; models moved out of v1's `workflow` app pin
  `Meta.db_table = "workflow_<modelname>"`. No renames in v2.0 — data migrates by pg_dump/restore.
- `delta_checksum` canonicalisation is bit-identical between Python and TypeScript (golden vectors).
- Exact-URL parity only where an external party holds the URL: Xero OAuth redirect, Xero webhook,
  CRM phone ingestion, ServiceApiKey consumers. **Everywhere else the API is free** — v1's schema
  is a reference while porting, never an authority, and nothing gates on it. v1 is being replaced
  because its architecture was wrong, so preserving its contract preserves the mistake. Read
  `../docketworks_v1` (the frozen v1 repo) when you need to know what v1 did; this repo no longer
  carries a copy. `docs/accepted-api-differences.yml` now records **behaviour** changes worth
  remembering, not schema deviations needing permission.
- Tests port only if they assert real business behaviour; drop tests that mirror implementation
  text or enshrine a v1 divergence.
