# Consistent transient ref control for deploys

**Date:** 2026-07-21
**Status:** Design approved, pending implementation plan

## Context

UAT feedback: there is no clean, consistent way to say *what to deploy* to an
instance. The capability is split and half-hidden:

- `deploy.sh` accepts `--ref <branch|tag|sha>` (default `origin/production`) and
  logs the resolved ref→SHA — this is the sanctioned way to put a candidate on
  UAT (ADR 0029: "no server is ever pointed at any other ref except transiently
  via `deploy.sh --ref` for candidate verification on UAT").
- `instance.sh create` **hardcodes** `origin/production` (no `--ref`), so a new
  UAT box cannot be born on a candidate — you must create-on-production then
  redeploy.
- Nothing reports what ref an instance is currently running.
- The docs actively mislead: `CLAUDE.md` says "`main` … is never deployed",
  which is false — `main` is deployed to UAT for candidate verification; it is
  never deployed *to production*. ADR 0029's own body already says this; only its
  summary line and the `CLAUDE.md` paraphrase overstate it.

Chosen direction (over durable per-instance pinning): keep ADR 0029's model —
prod = `production`, UAT candidates are transient, reboot catch-up still deploys
`production` — and make the *transient* story clean and consistent across the
create/deploy/status surfaces.

## Non-goals

- **No persisted per-instance ref.** ADR 0029 explicitly rejected per-instance
  pinning as institutionalising fleet drift. `status` derives the ref by
  comparing SHAs; nothing is stored. A UAT box on a candidate still reverts to
  `production` on reboot — accepted.
- No change to the promotion (`main`→`production`) or hotfix workflow.

## Design

### 1. `instance.sh create --ref <ref>`
- Add `--ref <ref>` (default `origin/production`) to `do_configure`'s flag parser
  (alongside `--seed`/`--fqdn`/`--no-start`, ~line 410), tracking an explicit
  `REF_SET` flag to distinguish "passed" from "defaulted".
- At the create-only release block (`if [[ ! -L "$INSTANCE_DIR/app" ]]`, ~line
  597) resolve `$REF` instead of the hardcoded `origin/production`, and log
  `Resolved <ref> to <sha>` in the same words `deploy.sh` uses (line 274).
- **`reconfigure` rejects `--ref`.** `do_configure` backs both commands, but the
  release block is skipped on reconfigure (app symlink already exists), so `--ref`
  there would silently no-op. If `REF_SET` and command is `reconfigure`, error:
  `reconfigure does not accept --ref; use deploy.sh --ref to re-point an existing instance.`

### 2. `instance.sh status <inst>`
- New subcommand in the dispatch `case` and usage.
- `fetch_local_repo`, read the running SHA from `$INSTANCE_DIR/app/.release-sha`
  (and `deploy-state.env` for context), then report the SHA and **which ref it
  matches**, derived by comparison:
  - `== origin/production` (plus ahead/behind if not exactly at the tip),
  - `== origin/main` → "main candidate",
  - otherwise `candidate <sha> (matches no tracked ref)`.
- Read-only; persists nothing.

### 3. Prod `--ref` guard (confirm + override)
- Factor a shared predicate into `common.sh`, e.g.
  `require_production_ref_or_ack <instance> <ref> <allow_flag>`, so `deploy.sh`
  and `instance.sh create` enforce it identically (and it is unit-testable).
- Fires only when the target instance is prod (`<client>-prod`) **and** the ref
  is not `origin/production`:
  - interactive TTY → prompt `refusing: non-production ref on a PROD instance. confirm? [y/N]`, proceed only on `y`;
  - non-interactive, or to skip the prompt → require an explicit `--allow-prod-ref` flag; otherwise error.
- A merged hotfix deploys from the default `origin/production` and never trips
  this. UAT/demo instances are never affected.
- Add `--allow-prod-ref` to both `deploy.sh` and `instance.sh create`.

### 4. Docs
- `CLAUDE.md` (Environment Configuration): "`main` is never deployed" →
  "`main` is never deployed *to production*; UAT verifies release candidates
  (including `origin/main`) transiently via `deploy.sh --ref` / `create --ref`."
- `docs/adr/0029-servers-run-the-production-branch.md`: tighten the summary line
  to match the body; add the prod `--ref` guard to Consequences.
- Usage/help: `instance.sh` header + main usage, and `scripts/server/README.md`
  ("Creating an Instance", "Deploying Updates") document `create --ref`,
  `status`, and `--allow-prod-ref`.

## Testing

Extend `apps/workflow/tests/test_xero_instance_templates.py` (the existing
grep-based script-contract suite):

- `create` parses `--ref` and feeds `$REF` (not a literal `origin/production`) to
  `resolve_release_ref`.
- `reconfigure` rejects `--ref` with the pointed-at-`deploy.sh` error.
- Both `deploy.sh` and `instance.sh` call the shared guard and expose
  `--allow-prod-ref`.
- `status` is wired into dispatch and usage.

Plus one **executable** test (like the existing `node_major_from_nvmrc` test that
sources the script): call `require_production_ref_or_ack` from `common.sh` with
stub inputs and assert it passes for `msm-uat`/any ref, passes for
`msm-prod`/`origin/production`, and refuses `msm-prod`/`origin/main` without the
allow flag.

## Files

- `scripts/server/instance.sh` — `create --ref`, `status`, reconfigure rejection, guard call
- `scripts/server/deploy.sh` — `--allow-prod-ref`, guard call
- `scripts/server/common.sh` — shared `require_production_ref_or_ack`
- `CLAUDE.md`, `docs/adr/0029-servers-run-the-production-branch.md`, `scripts/server/README.md`
- `apps/workflow/tests/test_xero_instance_templates.py`
