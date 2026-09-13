# 0039 — One implementation per concept
Superseded in part: ownership of a shared concept is ADR 0055; checking is not doing is ADR 0061.

Search before implement; a near-match is extended, never given a sibling.

## Rules

- Before writing any new function, component, service, or endpoint, search the codebase for an existing implementation of the concept. A near-match gets extended or generalised — never a sibling. This codebase is AI-written, so the pressure to write a parallel implementation recurs in every session, including this one.
- One obvious home per concept: small feature-scoped modules with predictable names, one generated API layer on the frontend so data access cannot fork, and the import-linter layer contract plus the API-boundary script enforcing what can be machine-enforced. Which context owns a backend concept is ADR 0055's question; consumers use the owner's public contracts, and frontend shared primitives live in `features/shared/`.
- When two implementations of one concept are found: choose one canonical behaviour (the user arbitrates if the difference is user-visible), delete the rest — **together with any tests or documentation that entrench the divergence**. Tests asserting both sides of a divergence are evidence of the pathology, not protection against it.
- Test fixtures are covered by this too: `seed_docketworks_prereqs()` (`apps/company/tests/job_fixtures.py`, called from the root `conftest.py`) is the one implementation of "what an installation needs before it can do anything", and the shared actors live in the root `conftest.py` beside that call. An app conftest rebuilding a staff member and a company is the same pathology in the test tree, where it is easier to excuse and just as expensive.
- Never port v1 code without first checking whether it has siblings; port exactly one canonical behaviour.
- **Unification is never deferred.** The change that would create a second implementation — or that discovers one — extracts the shared implementation before it merges. "Extract later", "post-cutover cleanup" and every equivalent are banned dispositions: a green test suite exists precisely so that refactoring is safe *now*, and a deferral note is how one duplicate becomes three.
- Reviews — human, agent, `/code-review` — treat "does this already exist?" as a standing question, because duplication is largely invisible to tooling.
- ADR 0032 is the same principle pointed at the ecosystem instead of the codebase; ADR 0061 is the same principle applied to checks and compensations.
