# 0015 — Fix incorrect data; do not add read-side fallbacks

When a consumer finds data shaped differently from the model's contract, repair the data (migration, emission fix, or both). Never soften the consumer.

## Problem

CLAUDE.md's "FAIL EARLY, NO FALLBACKS / trust the data model" rule forbids consumers that paper over malformed inputs, but says nothing about the symmetric question: when stored data *is* malformed, what do we do? The temptation is always the one-line read-side fallback ("if `delta_after` is empty, just read `detail.changes` instead"). Forcing case: `SalesPipelineService` was reading `JobEvent.delta_after.status` against a DB where 1,299 status_changed rows and 954 job_created rows had `delta_after = NULL` — a backfill artefact from a prior migration that had been a no-op against an empty `HistoricalJob`. The two options were a one-line fallback in the service or two data migrations.

## Decision

When stored data violates a consumer's invariant, fix the data. In order of preference: (1) data migration that reconstructs the canonical field from another in-row source; (2) emission-side patch that closes the path producing wrong data going forward; (3) both. The consumer stays strict — no `COALESCE`, no `or detail.changes…`, no schema relaxation, no tolerant reads. If the data genuinely cannot be reconstructed, escalate (raise, alert, leave the row visibly broken) rather than silently degrade. Document the unrecoverable subset as a separate emission-audit task.

## Why

Read-side fallbacks spread. One-line workaround in service A becomes the same workaround in service B, then C, and the canonical field is no longer authoritative anywhere. Once that happens, the underlying data drifts further because nothing forces a fix. Repairing data once leaves the canonical field actually canonical — every consumer reads the same thing, every reader is simple, every quality bug surfaces as a migration in git history rather than as ever-growing reader complexity.

## Alternatives considered

- **Read-side fallback in the consumer.** Strongly defendable in pragmatic shipping cultures and totally common in the wild. Rejected here: this codebase trusts its data contracts (CLAUDE.md), and the cost of a fallback is paid forever by every reader of that field.
- **Schema relaxation — make the field optional or accept multiple shapes.** Defendable when the field genuinely has two meanings. Rejected when the field has one meaning and just has bad rows: this moves the workaround into the type system, same drift, lower visibility.

## Consequences

Canonical fields stay canonical; consumers stay simple. Cost: data migrations carry their own risk and have to be dry-run + verified before applying. Some "incorrect data" categories are genuinely unrecoverable (transitions that were never emitted because a `.update()` bypassed `Job.save()`) — those require an emission-side audit, not a backfill.
