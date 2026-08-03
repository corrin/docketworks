# 0039 — One implementation per concept

Search before implement; a near-match is extended, never given a sibling.

## Rules

- Before writing any new function, component, service, or endpoint, search the codebase for an existing implementation of the concept. A near-match gets extended or generalised — never a sibling. v1 died of parallel implementations written by AI sessions that did not look (two job services, three cost-line grids, five duplicate-detection subsystems); v2 is also AI-written, so the pressure persists in every session, including this one.
- One obvious home per concept: small feature-scoped modules with predictable names, one generated API layer on the frontend so data access cannot fork, and the import-linter layer contract plus the API-boundary script enforcing what can be machine-enforced.
- When two implementations of one concept are found: choose one canonical behaviour (the user arbitrates if the difference is user-visible), delete the rest — **together with any tests or documentation that entrench the divergence**. Tests asserting both sides of a divergence are evidence of the pathology, not protection against it.
- Never port v1 code without first checking whether it has siblings; port exactly one canonical behaviour.
- Reviews — human, agent, `/code-review` — treat "does this already exist?" as a standing question, because duplication is largely invisible to tooling.
- ADR 0032 is the same principle pointed at the ecosystem instead of the codebase.
