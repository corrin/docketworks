# 0061 — Checking is not doing: one owner per action, one check at the boundary that matters
Unratified: Fable

Responsibilities are exclusive — one owner performs each action, and no other code performs it, compensates for it or re-does it as defence in depth — but a consumer may verify that the owner's work happened and refuse when it did not.

## Rules

- One implementation per concept (ADR 0039) means one owner of each action. If the owner is incomplete, the owner is fixed; the consumer never compensates. Re-treating data downstream is a second implementation of the one policy: the production-host scrub (`backport_data_backup`) owns the confidential-to-non-confidential transition, so no dev-side scrubber and no umask ceremony around restore files exists.
- **Verifying a precondition and refusing is not a second implementation.** A consumer may check that the owner's work happened and abort when it did not — that is fail-early (ADR 0015), and on a destructive or irreversible path it is required, not optional. `scripts/ops/verify_scrubbed_backup.py` is the shape: it re-scrubs nothing and instead fails an archive that still holds credentials.
- **The check calls the one implementation of the rule** (`apps/core/environment.validate_scrub_db_name`, `apps/xero/operator_guards.is_production_tenant`) rather than restating it, so the rule cannot drift between the site that enforces it and the site that relies on it.
- **Check once, at the boundary that matters.** Permission to check is not licence to layer: the same precondition asserted at four call depths is bloat, and each copy is another place to drift. One enforcement where the invariant is created, one check immediately before the destructive or irreversible step, and nothing in between.

## Do not

- **A check whose only possible trigger is a mocked-out collaborator** — a re-count of what the previous line already raised on is dead code, and goes.
- **Defence in depth around an owner you could fix** — the second layer hides the first layer's defect and is a second implementation of its policy.
