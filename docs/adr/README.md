# Architecture Decision Records

Short records capturing *why* we chose an approach — the problem, the decision, alternatives ruled out, consequences. Mechanics ("what changed") live in the linked PR; this directory preserves the reasoning that ages better than the code.

## Conventions

- **Filename:** `NNNN-short-kebab-topic.md`, zero-padded 4-digit sequential.
- **Numbering is stable.** Never renumber. New ADRs append.
- **Length target:** 30–50 lines. If you need more, the PR description probably already has it.
- **Status lifecycle:** `Proposed` → `Accepted`. Superseded ADRs stay in place and link forward.

## Template

See [`_template.md`](_template.md). Copy, renumber, fill in.

## Index

| N    | Title                                             |
| ---- | ------------------------------------------------- |
| 0001 | Exception deduplication via AlreadyLoggedException |
| 0002 | Auth gate: single global gate with explicit allowlist |
| 0003 | ETag-based optimistic concurrency for job edits   |
| 0004 | Cursor-based job delta sync                       |
| 0005 | CostLine emitter polymorphism                     |
| 0006 | REST API resource hierarchy and operationId hygiene |
| 0007 | Denormalized payroll sync with reconciliation     |
| 0008 | Frontend subtree merge over submodule             |
| 0009 | Environment flag tiers (DEV / UAT / PROD)         |
| 0010 | Single deploy.sh for prod and UAT via FQDN detection |
| 0011 | Codesight pre-commit wiki-mode integration        |
| 0012 | Accounting provider strategy pattern              |
| 0013 | Error message clarity wins over information hiding |
| 0014 | Explicit `else` branches on non-trivial `if`       |
