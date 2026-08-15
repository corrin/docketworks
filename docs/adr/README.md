# Architecture Decision Records

Decisions that shape this codebase, written for the reader about to do work here — usually an LLM session. Each ADR states rules, not history. Read alongside `CLAUDE.md`.

## Conventions

- **Filename:** `NNNN-short-kebab-topic.md`, zero-padded 4-digit sequential.
- **Numbering is stable.** Never renumber; never re-use a number; gaps from removed ADRs stay as gaps. Code cites ADRs by number.
- **Substance bar.** An ADR captures a non-obvious decision a careful reader of the code couldn't reconstruct.
- **Every sentence is load-bearing:** a rule, or the forcing fact that makes a rule stick. No narrative problem statements, no essays defending alternatives, no consequences sections restating the decision — deliberation history lives in git. Rationale is a clause attached to its rule.
- **Clear prose, not fragments.** Brevity comes from cutting sentences that don't change behaviour, never from telegraphic writing — compressed fragments are harder to follow than plain sentences.
- **Tempting wrong turns** go under `## Do not` as a prohibition plus a one-line reality, only when the temptation is real.

## Template

See [`_template.md`](_template.md). Copy, renumber, fill in.

## Index

| N | Title |
| --- | --- |
| [0001](0001-exception-already-logged-dedup.md) | Idempotent error persistence |
| [0002](0002-auth-gate-global-allowlist.md) | Auth gate: single global gate with explicit allowlist |
| [0003](0003-etag-optimistic-concurrency.md) | ETag-based optimistic concurrency for Job and PO edits |
| [0004](0004-job-delta-envelope.md) | Job mutations require a self-contained delta envelope |
| [0005](0005-emit-tools-pattern.md) | Emit-tool pattern for Gemini structured output |
| [0006](0006-rest-resource-hierarchy.md) | REST resource hierarchy and operationId hygiene |
| [0007](0007-xero-payroll-sync.md) | Xero Payroll NZ sync with four-bucket hour categorisation |
| [0008](0008-frontend-subtree-merge.md) | Frontend integrated as a git subtree (not submodule) |
| [0012](0012-accounting-provider-strategy.md) | Accounting provider strategy with registry |
| [0013](0013-error-message-clarity-over-info-hiding.md) | Error clarity follows the authentication boundary |
| [0015](0015-fix-data-not-fallback.md) | Fix incorrect data; do not add read-side fallbacks |
| [0017](0017-zero-backwards-compatibility.md) | Zero backwards compatibility; rewrite every call site in one PR |
| [0019](0019-mandatory-error-persistence.md) | Unexpected exceptions are persisted to AppError |
| [0020](0020-frontend-backend-separation.md) | Frontend/Backend separation: data is backend, presentation is frontend |
| [0021](0021-frontend-generated-api-client-only.md) | Frontend reads and writes the API only through the generated client |
| [0024](0024-celery-async-task-processing.md) | Background work runs through Celery; tasks are idempotent and tenant-aware |
| [0025](0025-tests-state-business-risk.md) | Every test guards against a plausible regression |
| [0026](0026-plan-the-tests-before-approval.md) | Plan the tests before the plan is approved |
| [0027](0027-deploy-capability-with-its-controls.md) | A capability deploys with the means to operate it |
| [0028](0028-type-annotations-are-data-contracts.md) | Type annotations are data contracts |
| [0029](0029-servers-run-the-production-branch.md) | Separate integration from production releases |
| [0030](0030-first-class-people-and-company-links.md) | First-class People and Company links |
| [0031](0031-single-logging-gate-debug-namespaces.md) | One logging gate: the debug library with namespaces |
| [0032](0032-prefer-libraries-over-homegrown.md) | Less code is better: prefer libraries over homegrown implementations |
| [0033](0033-version-constraints-record-tested-versions.md) | Version constraints record what passed testing, not what is compatible |
| [0034](0034-company-merges-are-xero-first.md) | Company identity and merges are Xero-first |
| 0035–0037 | (reserved: ninja adoption, beat-in-code, workflow decomposition — written as their phases land) |
| [0038](0038-transparent-errors-trusted-environment.md) | Errors are transparent inside the authenticated trust boundary |
| [0039](0039-one-implementation-per-concept.md) | One implementation per concept |
| [0040](0040-nullable-text-write-contract.md) | Unset is NULL, and the request schema says so |
| [0041](0041-one-llm-gateway.md) | One LLM gateway, and it lives in apps/ai |
| 0042 | (reserved: v1 data migration — written when that phase lands) |
| [0043](0043-comments-record-the-rejected-alternative.md) | Comments record the rejected alternative |
| [0045](0045-call-the-right-function-no-shims.md) | Call the right function; never return a shape the caller must decode |
| [0046](0046-numbers-on-the-wire.md) | Numbers on the wire; the frontend owns all formatting |
| [0047](0047-asgi-serving-and-sse-push.md) | The application is served over ASGI, and data versions are pushed over SSE |
| [0048](0048-own-what-you-wipe-database-safety.md) | A role wipes only what it owns; deliberateness is graded, prod wipes need an explicit assertion and are always recoverable |
| [0049](0049-one-home-per-operational-script.md) | Operational scripts are homed by confidentiality and recurrence: client adhoc, repo adhoc, scripts/, management command |
| [0050](0050-integrations-are-proven-against-the-real-thing.md) | Every integration is proven against the real thing, and nothing merges without it |
