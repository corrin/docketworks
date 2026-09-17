# Architecture Decision Records

Decisions that shape this codebase, written for the reader about to do work here — usually an LLM session. Each ADR states rules, not history. Read alongside `CLAUDE.md`.

## Conventions

- **Filename:** `NNNN-short-kebab-topic.md`, zero-padded 4-digit sequential.
- **Numbering is stable.** Never renumber; never re-use a number; gaps from removed ADRs stay as gaps. Code cites ADRs by number.
- **Substance bar.** An ADR captures a non-obvious decision a careful reader of the code couldn't reconstruct.
- **Every sentence is load-bearing:** a rule, or the forcing fact that makes a rule stick. No narrative problem statements, no essays defending alternatives, no consequences sections restating the decision — deliberation history lives in git. Rationale is a clause attached to its rule.
- **Clear prose, not fragments.** Brevity comes from cutting sentences that don't change behaviour, never from telegraphic writing — compressed fragments are harder to follow than plain sentences.
- **Tempting wrong turns** go under `## Do not` as a prohibition plus a one-line reality, only when the temptation is real.
- **An ADR lands in its own commit.** An ADR written in the same commit as the code it authorises has not been decided, only justified, and the code was never weighed against a rule that existed before it.
- **An ADR an AI drafted is unratified until the owner says otherwise** (ADR 0051), and an unratified ADR is not authority for changing behaviour. Mark it, then ask.

## Template

See [`_template.md`](_template.md). Copy, renumber, fill in.

## Index

| N | Title |
| --- | --- |
| [0001](0001-exception-already-logged-dedup.md) | Error persistence is idempotent: one failure, one AppError row |
| [0002](0002-auth-gate-global-allowlist.md) | Auth gate: single global gate with explicit allowlist |
| [0003](0003-etag-optimistic-concurrency.md) | Job, PO and stocktake mutations carry If-Match: missing is 428, stale is 412 |
| [0004](0004-job-delta-envelope.md) | Job mutations require a self-contained delta envelope |
| 0005 | (retired 2026-09-13: Gemini emit-tools no longer exist; every AI call is [0041](0041-one-llm-gateway.md)'s gateway) |
| [0006](0006-rest-resource-hierarchy.md) | Identifiers live in the URL path, bodies carry data only, one endpoint per operation |
| [0007](0007-xero-payroll-sync.md) | Xero payroll posts each hour category through the one surface that can represent it, and never posts a public holiday |
| 0008 | (retired 2026-09-13: this repository was never a subtree; the one-repo rule lives in [0017](0017-zero-backwards-compatibility.md)) |
| 0009–0011, 0014, 0016, 0018, 0022–0023, 0044 | (numbers never carried into this repository; no record of what they held) |
| [0012](0012-accounting-provider-strategy.md) | Every accounting read and write reaches the vendor only through get_provider(); SDK types never cross the boundary |
| 0013 | (retired 2026-09-13: merged into [0038](0038-transparent-errors-trusted-environment.md)) |
| [0015](0015-fix-data-not-fallback.md) | Fix incorrect data; do not add read-side fallbacks |
| [0017](0017-zero-backwards-compatibility.md) | Zero backwards compatibility; rewrite every call site in one PR |
| [0019](0019-mandatory-error-persistence.md) | Unexpected exceptions are persisted to AppError |
| [0020](0020-frontend-backend-separation.md) | Frontend/Backend separation: data is backend, presentation is frontend |
| [0021](0021-frontend-generated-api-client-only.md) | Frontend reads and writes the API only through the generated client |
| [0024](0024-celery-async-task-processing.md) | Background work runs through Celery; tasks are idempotent and write-side |
| [0025](0025-tests-state-business-risk.md) | Every test guards against a plausible regression |
| [0026](0026-plan-the-tests-before-approval.md) | Plan the tests before the plan is approved |
| [0027](0027-deploy-capability-with-its-controls.md) | A capability deploys with the means to operate it |
| [0028](0028-type-annotations-are-data-contracts.md) | Type annotations are data contracts |
| [0029](0029-servers-run-the-production-branch.md) | Separate integration from production releases |
| [0030](0030-first-class-people-and-company-links.md) | Person owns identity, CompanyPersonLink owns the relationship, jobs point at the person |
| [0031](0031-single-logging-gate-debug-namespaces.md) | One logging gate: the `debug` library with namespaces |
| [0032](0032-prefer-libraries-over-homegrown.md) | Less code is better: prefer libraries over homegrown implementations |
| [0033](0033-version-constraints-record-tested-versions.md) | Version constraints record what passed testing, not what is compatible |
| [0034](0034-company-merges-are-xero-first.md) | Company identity and merges are Xero-first |
| 0035–0037 | (unused: ninja adoption, beat-in-code and the workflow-app decomposition landed without an ADR) |
| [0038](0038-transparent-errors-trusted-environment.md) | Authenticated callers get the real exception; anonymous callers get fixed wording and no secrets |
| [0039](0039-one-implementation-per-concept.md) | One implementation per concept |
| [0040](0040-nullable-text-write-contract.md) | Unset is NULL, and the request schema says so |
| [0041](0041-one-llm-gateway.md) | One LLM gateway, and it lives in apps/ai |
| 0042 | (unused: the v1 data migration ran on 2026-08-29 without an ADR; its record is the Cutover section of [`rewrite-history.md`](../rewrite-history.md)) |
| [0043](0043-comments-record-the-rejected-alternative.md) | Comments record the rejected alternative |
| 0045 | (retired 2026-09-13: merged into [0028](0028-type-annotations-are-data-contracts.md)) |
| [0046](0046-numbers-on-the-wire.md) | Numbers on the wire; the frontend owns all formatting |
| [0047](0047-asgi-serving-and-sse-push.md) | The application is served over ASGI, and data versions are pushed over SSE |
| [0048](0048-own-what-you-wipe-database-safety.md) | A role wipes only what it owns; production wipes need an explicit assertion and are always recoverable |
| [0049](0049-one-home-per-operational-script.md) | Operational scripts are homed by confidentiality and recurrence |
| [0050](0050-integrations-are-proven-against-the-real-thing.md) | Every integration is proven against the real thing, and nothing merges without it |
| [0051](0051-ai-rationales-name-their-author.md) | AI rationales name their author until ratified |
| [0052](0052-tests-survive-rewrites.md) | Assert the guarantee, not the implementation: a rewrite leaves the test passing and a behaviour change fails it |
| [0053](0053-integration-credentials-are-typed-columns-on-one-singleton.md) | Integration credentials are typed columns on one singleton; never .env, never CompanyDefaults |
| [0054](0054-screens-are-tested-at-production-volume.md) | A screen is tested at the volume production gives it |
| [0055](0055-modular-monolith-context-ownership.md) | New code lives in the context that owns its concept, and dependencies point one way |
| [0056](0056-vendor-calls-are-recorded-per-call.md) | Every external vendor call is recorded, one row per call |
| [0057](0057-line-identity-and-creation-order.md) | Persisted lines keep permanent ids and a server-defined creation order |
| [0058](0058-write-refusals-live-in-the-application.md) | Code that looks short and simple runs short and simple: a write refusal lives in one application function, never in a trigger |
| [0059](0059-one-data-model-legacy-data-is-migrated.md) | The app supports one data model; legacy data is migrated to comply |
| [0060](0060-an-iteration-run-may-fake-an-integration.md) | The fake Xero is a drop-in replacement for Xero's API, proven against Xero by recordings |
| [0061](0061-checking-is-not-doing.md) | Checking is not doing: one owner per action, one check at the boundary that matters |
| [0062](0062-ai-provider-selection-and-administration.md) | A caller selects an AI provider from the configured catalogue, and Admin → Integrations owns the catalogue |
| [0063](0063-test-suite-conventions.md) | Every test starts from a provisioned instance and asserts over what it created; E2E drives the UI by automation id |
| [0064](0064-an-instance-is-verified-on-a-copy-of-its-database.md) | A deployed instance is verified by the E2E suite on a copy of its database, against the fake Xero, with users fenced out |
| [0065](0065-each-instance-owns-its-redis-server.md) | Each instance owns its Redis server |
| [0066](0066-the-new-instance-path-is-rehearsed-after-every-merge.md) | The new-instance path is rehearsed on a throwaway instance after every merge |
