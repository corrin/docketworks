# Architecture Decision Records

Short records that tell future developers how to code in this codebase: the problem, the decision, the why, the alternatives ruled out, and the consequences. Read these alongside `CLAUDE.md`.

## Conventions

- **Filename:** `NNNN-short-kebab-topic.md`, zero-padded 4-digit sequential.
- **Numbering is stable.** Never renumber. New ADRs append.
- **Length target:** ~50 lines. If you need more, the topic is probably two ADRs.
- **Alternatives must be real.** Only list alternatives a senior developer would defend on a different project. No strawmen.

## Template

See [`_template.md`](_template.md). Copy, renumber, fill in.

## Index

| N    | Title                                                          |
| ---- | -------------------------------------------------------------- |
| 0001 | Exception deduplication via AlreadyLoggedException             |
| 0002 | Auth gate: single global gate with explicit allowlist          |
| 0003 | ETag-based optimistic concurrency for Job and PO edits         |
| 0004 | Job mutations require a self-contained delta envelope          |
| 0005 | Emit-tool pattern for Gemini structured output                 |
| 0006 | REST resource hierarchy and operationId hygiene                |
| 0007 | Xero Payroll NZ sync with four-bucket hour categorisation      |
| 0008 | Frontend integrated as a git subtree (not submodule)           |
| 0009 | Frontend resolves backend `.env` by convention                 |
| 0010 | Single `deploy.sh` with hostname detection                     |
| 0011 | Codesight runs via pre-commit in wiki mode; output committed   |
| 0012 | Accounting provider strategy with registry                     |
| 0013 | Error message clarity wins over information hiding             |
| 0014 | Explicit `else` branches on non-trivial `if`                   |
| 0015 | Fix incorrect data; do not add read-side fallbacks             |
| 0016 | Ambiguous names trigger rename, not grandfathering             |
| 0017 | Zero backwards compatibility; rewrite every call site in one PR |
| 0018 | Fail early, handle unhappy cases first, no fallbacks           |
| 0019 | Every exception is persisted to AppError before re-raise       |
| 0020 | Frontend/Backend separation: data is backend, presentation is frontend |
| 0021 | Frontend reads and writes the API only through the generated client |
