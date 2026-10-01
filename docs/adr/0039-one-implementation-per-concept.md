# 0039 — One implementation per concept
Superseded in part: ownership of a shared concept is ADR 0055.

Search before implement; a near-match is extended, never given a sibling.

## Rules

- Before writing any new function, component, service, or endpoint, search the codebase for an existing implementation of the concept. A near-match gets extended or generalised — never a sibling. This codebase is AI-written, so the pressure to write a parallel implementation recurs in every session, including this one.
- One obvious home per concept: small feature-scoped modules with predictable names, one generated API layer on the frontend so data access cannot fork, and the import-linter layer contract plus the API-boundary script enforcing what can be machine-enforced. Which context owns a backend concept is ADR 0055's question; consumers use the owner's public contracts, and frontend shared primitives live in `features/shared/`.
- When two implementations of one concept are found: choose one canonical behaviour (the user arbitrates if the difference is user-visible), delete the rest — **together with any tests or documentation that entrench the divergence**. Tests asserting both sides of a divergence are evidence of the pathology, not protection against it.
- Test fixtures are covered by this too: `seed_docketworks_prereqs()` (`apps/company/tests/job_fixtures.py`, called from the root `conftest.py`) is the one implementation of "what an installation needs before it can do anything", and the shared actors live in the root `conftest.py` beside that call. An app conftest rebuilding a staff member and a company is the same pathology in the test tree, where it is easier to excuse and just as expensive.
- Never port v1 code without first checking whether it has siblings; port exactly one canonical behaviour.
- **Unification is never deferred.** The change that would create a second implementation — or that discovers one — extracts the shared implementation before it merges. "Extract later", "post-cutover cleanup" and every equivalent are banned dispositions: a green test suite exists precisely so that refactoring is safe *now*, and a deferral note is how one duplicate becomes three.
- Reviews — human, agent, `/code-review` — treat "does this already exist?" as a standing question, because duplication is largely invisible to tooling.
- ADR 0032 is the same principle pointed at the ecosystem instead of the codebase.
- Fable: **One owner per action, and the consumer never compensates.** If the owner is incomplete, the owner is fixed; re-treating its output downstream is a second implementation of the one policy. Verifying a precondition and refusing is not: a consumer may check that the owner's work happened and abort when it did not, and on a destructive or irreversible path it must. The check calls the one implementation of the rule (`apps/core/environment.validate_scrub_db_name`, `apps/xero/operator_guards.is_production_tenant`) rather than restating it, and it runs once, immediately before the destructive step — the same precondition asserted at four call depths is bloat, and each copy is another place to drift.

## Do not

- Fable: **Defence in depth around an owner you could fix** — the second layer hides the first layer's defect and is a second implementation of its policy; a check whose only possible trigger is a mocked-out collaborator is dead code.
