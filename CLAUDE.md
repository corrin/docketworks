# CLAUDE.md — Docketworks

This codebase is exhibited as an example of how the architecture should be done, and it
replaced a system that already worked, so "working but structurally compromised" delivers
nothing: scope bends, the standard does not. Colliding with a rule — an ADR, a
linter, a type error, a layer contract — means the approach is wrong, not that a rule is in
the way. Stop, name the belief the tool contradicted, and check it (query the data, read the
writers, read the ADR in full) before editing; never search for the smallest edit that gets
past it. A rule enters this file as one line naming its authority; the argument stays in the
ADR, and nothing here is said twice.

## Where things are

- [`docs/rewrite-status.md`](docs/rewrite-status.md) is the only to-do list: read it before
  picking up work and update it at the end of every slice. It only shrinks; anything that is
  not a task — a ruling, a finding, a measurement — goes to
  [`docs/rewrite-history.md`](docs/rewrite-history.md). A Jira ticket (KAN) is the authority
  wherever one exists.
- [`docs/adr/`](docs/adr/README.md): read the index before non-trivial work; ADRs win over habit.
- [`docs/design-language.md`](docs/design-language.md): read before designing or changing a screen.
- [`docs/release-process.md`](docs/release-process.md) is how a change reaches production;
  [`docs/README.md`](docs/README.md) indexes the rest.
- `../docketworks_v1` is the frozen v1; this repo carries no copy.
- Session transcripts are not durable; those files, the ADRs and seam comments are.

## Commands

| tier | command | cost | note |
|---|---|---|---|
| commit | automatic; `pre-commit run --all-files` | ~64s | `.pre-commit-config.yaml` is the list |
| push | automatic; `pre-commit run --all-files --hook-stage pre-push` | ~5s | what CI does not run, and the registry of custom checks: search it before writing one |
| unit | `uv run pytest` | ~152s | scope with `uv run pytest apps/job` or `--lf`; `-n auto --dist loadscope` is in `addopts`: never add it, never run serially |
| integration | `./scripts/ops/run_integration_tests.sh`, `scripts/ops/outbound_links_probe.py`, `scripts/checks/route_reachability.py` | ~1min | human-run merge gate for anything that touches an external system; CI has no credentials (ADR 0050) |
| e2e | `./scripts/ops/run_e2e.sh` | ~25min | bare `npm run test:e2e` only against an environment already running; `--use-fake-xero` is labelled everywhere and never the gate (ADR 0060) |

The frontend loop check is `npm run type-check`, not `npm run build`. `uv run mypy` is strict
at a zero baseline over `apps config manage.py scripts`. CI runs the commit tier plus the unit
suites, never integration or E2E; a CI check missing from the commit tier is a bug in the
tier, never a saving, and slowness argues for a faster check, never for moving it. Never
weaken a gate, never baseline one.

## Never

- `--no-verify`.
- `XERO_READONLY` on a test run: it is a production hotfix valve (ADR 0050).
- Start uvicorn, the Vite preview, ngrok, Celery or Beat by hand; `.vscode/tasks.json` owns them.
- `source .env`; `config/settings.py` calls `load_dotenv`.

## Done

- Done means the E2E spec passes. Report progress as specs green, never as endpoints or
  components written. Nothing releases without the suite green.
- Commit each verified slice as soon as it is complete, staging explicit paths; push only when
  asked. A green unit run is a commit boundary. A generated artifact carrying another
  workstream's changes is partial-staged, or the overlap is reported before committing.
- A screen that renders a collection is tested at production volume;
  `docs/prod-data-shape.yml` holds the counts (ADR 0054).
- An integration slice ships its admin UI, typed credential owner, consumer selection rules,
  new-instance seed, restore/scrub behaviour, live verification and its setup doc, through the
  existing configuration service (ADR 0053, 0027). Keys are write-only and a settings GET
  never probes a vendor. Setup is tested through the UI, including failed saves and key
  rotation; a terminal or database workaround proves nothing. An unverified acceptance step
  is recorded in the PR and in `docs/rewrite-status.md`.

## Layout

- Backend: the import-linter contract in `pyproject.toml` gates — `config` on top, `core`,
  `ai` and `platform` at the bottom. ADR 0055 is the target taxonomy and
  `config/architecture.py` the list of migrated contexts; never name one absent from it.
- Frontend: `routes/` (thin) → `features/<domain>/` → the generated client (ADR 0021, never
  hand-edited) and `lib/`. Server state lives in TanStack Query; no hand-written service layer.
- `docs/code-quality.md` is generated, never hand-edited; only `passthrough` is pinned at zero.

## Standards

- **Search before implement.** One implementation per concept; extend a near-match, never
  write a sibling (ADR 0039).
- A GET never writes: not a row, not a default, not a singleton. `CompanyDefaults.get_solo()`
  is overridden read-only in `apps/core/models.py`.
- Fail early. Malformed data is fixed by migration, never by a read-side fallback (ADR 0015).
  `x if y else None`, `or None`, `.get(k, default)`, `?? fallback` and `hasattr` each claim the
  model permits the bad case: check the claim, then delete the branch or raise and tighten the
  writer. Where code and contract disagree, the contract is presumed right (ADR 0028).
- Guard clauses: unhappy path first. `if ok: do_thing()` with no else is a bug; non-trivial
  branches get an explicit `else`. Errors are transparent after authentication (ADR 0038).
- A `try` needs a reason. Unexpected handlers call `persist_app_error` and re-raise; expected
  catches carry a `deliberate-swallow` reason; conversions `raise X from exc` (ADR 0019, 0001).
- Type annotations are contracts: no `Any`, no fake `| None`, no broad union or cast; complex
  shapes get a named type (ADR 0028). A `type: ignore` or `noqa` names its code and its reason.
- Code that looks simple runs simple. A refusal lives in one service function raising a typed
  error; `CHECK`, `UNIQUE`, `NOT NULL` and `on_delete` belong in the schema, a raising trigger
  never does (ADR 0058).
- One data model. A one-off migration is the only thing that knows the old shape (ADR 0059); a creation
  timestamp is never nullable (ADR 0057).
- Libraries over DIY (ADR 0032). One LLM gateway: every AI call goes through `apps/ai`, and no
  feature imports a vendor SDK (ADR 0041). Unset is NULL, via `NullableText` (ADR 0040).
  Numbers travel as JSON numbers (ADR 0046).
- Comments record the rejected alternative and the fact that rejected it (ADR 0043). AI-authored
  rationale carries its model prefix (`Opus:`, `GPT:`) until ratified (ADR 0051).

## Porting

- Every v1 feature exists in v2. Shape is free; capability is not. A drop is the owner's
  decision and `docs/accepted-api-differences.yml` records it; an unrecorded loss is a defect.
  Port a screen from the v1 component read in full, never from the endpoints it called; where
  v1 has divergent siblings, port one canonical behaviour (ADR 0039).
- Models keep v1 app labels and class names; models moved out of v1's `workflow` app pin
  `Meta.db_table = "workflow_<modelname>"`. No renames in v2.0.
- `delta_checksum` canonicalisation is bit-identical between Python and TypeScript (ADR 0004).
- Exact-URL parity only where an external party holds the URL: Xero OAuth redirect, Xero
  webhook, CRM phone ingestion, ServiceApiKey consumers (ADR 0017 defers to this list).
  Everywhere else the API is free; v1 is a reference, never an authority.
- Tests port only if they assert business behaviour (ADR 0039, 0052).
