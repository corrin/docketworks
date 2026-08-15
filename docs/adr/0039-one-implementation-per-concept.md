# 0039 — One implementation per concept

Search before implement; a near-match is extended, never given a sibling.

## Rules

- Before writing any new function, component, service, or endpoint, search the codebase for an existing implementation of the concept. A near-match gets extended or generalised — never a sibling. v1 died of parallel implementations written by AI sessions that did not look (two job services, three cost-line grids, five duplicate-detection subsystems); v2 is also AI-written, so the pressure persists in every session, including this one.
- One obvious home per concept: small feature-scoped modules with predictable names, one generated API layer on the frontend so data access cannot fork, and the import-linter layer contract plus the API-boundary script enforcing what can be machine-enforced.
- When two implementations of one concept are found: choose one canonical behaviour (the user arbitrates if the difference is user-visible), delete the rest — **together with any tests or documentation that entrench the divergence**. Tests asserting both sides of a divergence are evidence of the pathology, not protection against it.
- Test fixtures are covered by this too: `seed_docketworks_prereqs()` in the root `conftest.py` is the one implementation of "what an installation needs before it can do anything", and the shared actors live beside it. Seven app conftests separately rebuilding a staff member and a company is the same pathology in the test tree, where it is easier to excuse and just as expensive.
- Never port v1 code without first checking whether it has siblings; port exactly one canonical behaviour.
- **Unification is never deferred.** The change that would create a second
  implementation — or that discovers one — extracts the shared implementation
  before it merges. "Extract later", "post-cutover cleanup" and every
  equivalent are banned dispositions: a green test suite exists precisely so
  that refactoring is safe *now*, and a deferral note is how one duplicate
  becomes three (measured: the grid render contract reached three inline
  copies under exactly that note before being unified).
- **Responsibilities are exclusive — but checking is not doing.** One
  implementation per concept means one OWNER of each *action*: no other code
  performs it, compensates for it, or re-does it as defence in depth. The live
  example: the production-host scrub (`backport_data_backup`) owns the
  confidential-to-non-confidential transition, so a second dev-side scrubber
  and umask ceremony around restore files were both deleted on this rule
  (2026-08-15) — re-treating data downstream is a second implementation of the
  one policy. If the owner is incomplete, the owner is fixed; the consumer
  never compensates.

  **Verifying a precondition and refusing is not a second implementation.** A
  consumer may check that the owner's work happened and abort when it did not
  — that is fail-early (ADR 0015), and on a destructive or irreversible path it
  is required, not optional. `scripts/ops/verify_scrubbed_backup.py` is the
  shape: it re-scrubs nothing and instead fails an archive that still holds
  credentials. The check CALLS the one implementation of the rule
  (`apps/core/environment.validate_scrub_db_name`,
  `apps/xero/operator_guards.is_production_tenant`) rather than restating it,
  so the rule cannot drift between the site that enforces it and the site that
  relies on it.

  **Check once, at the boundary that matters.** Permission to check is not
  licence to layer: the same precondition asserted at four call depths is
  bloat, and each copy is another place to drift. One enforcement where the
  invariant is created, one check immediately before the destructive or
  irreversible step, and nothing in between. A check whose only possible
  trigger is a mocked-out collaborator — a re-count of what the previous line
  already raised on — is dead code, and goes.
- **Shared concepts live in shared homes.** A domain module importing from
  another domain module is the signal that the imported thing belongs to
  neither — move it to the shared home (frontend `features/shared/`, backend
  `apps/core`) in the same change. A domain feature is not a library.
- **The bar is reference quality.** This codebase is presented as an example
  of coding best practice, and it replaced a system that already worked —
  so "working but structurally compromised" delivers nothing. Architectural
  quality outranks schedule: scope bends, the standard does not. When a
  deadline and a duplicate collide, that is what this bullet is for: the
  duplicate loses.
- Reviews — human, agent, `/code-review` — treat "does this already exist?" as a standing question, because duplication is largely invisible to tooling.
- ADR 0032 is the same principle pointed at the ecosystem instead of the codebase.
