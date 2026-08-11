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
