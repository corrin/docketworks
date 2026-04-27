# 0013 — Fix incorrect data; do not add read-side fallbacks

When a consumer finds data shaped differently from the model's contract, restore the contract by repairing the data (migration, emission fix, or both) — never by softening the consumer.

- **Status:** Accepted
- **Date:** 2026-04-27
- **PR(s):** [#247](https://github.com/corrin/docketworks/pull/247) — fix(job): backfill JobEvent.delta_after on legacy status/created rows

## Context

CLAUDE.md's "FAIL EARLY, NO FALLBACKS / trust the data model" section forbids reading code that papers over malformed inputs, but the codebase has no explicit answer for the symmetric question: when we discover data that *is* malformed, what do we do? The temptation is always to make the consumer tolerant ("just fall back to `detail.changes` if `delta_after` is empty"). That's how single-purpose workarounds spread until the canonical field is no longer authoritative anywhere. The forcing case was `SalesPipelineService` reading `JobEvent.delta_after.status` against a DB where 1,299 status_changed events and 954 job_created events had `delta_after = NULL` — a backfill artefact from migration 0075 having been a no-op against an empty `HistoricalJob`. Both options were live: a one-line fallback in the service, or two data migrations.

## Decision

When a consumer's invariant is violated by stored data, fix the data. In order of preference: (1) data migration that reconstructs the canonical field from another in-row source already populated by an earlier migration, (2) emission-side patch that closes the path producing wrong data going forward, (3) both. The consumer stays strict — no `COALESCE`, no `or detail.changes…`, no schema relaxation, no "tolerant" reads. If the data cannot be reconstructed (the source is genuinely lost), escalate — raise, alert, leave the row visibly broken — rather than silently degrade. Document the unrecoverable subset as out of scope and treat its existence as a separate emission-audit task, not as a reason to relax the contract.

## Alternatives considered

- **Read-side fallback in the consumer:** trivial to write but spreads workaround logic across every reader, makes the canonical field non-authoritative, and lets the underlying data drift further because nothing forces a fix.
- **Schema relaxation (make the field optional / accept multiple shapes):** moves the workaround into the type system; same drift, lower visibility.
- **Synthesise placeholder data on the fly at read time:** quietly corrupts the audit trail; future readers can't tell real records from placeholders.

## Consequences

- **Positive:** the canonical field stays canonical; consumers remain simple and reviewable; data-quality bugs surface as migrations or emission fixes (visible in git history) rather than as ever-growing reader complexity; CLAUDE.md's fail-early stance becomes operationally complete.
- **Negative / costs:** data migrations carry their own risk and have to be dry-run + verified before applying; some "incorrect data" categories are genuinely unrecoverable (e.g., transitions that were never emitted because a `.update()` bypassed `Job.save()`), so this ADR commits us to the harder fix — auditing emission sites — rather than synthesising fake events.
- **Follow-ups:** the JobEvent silent-archive (3 jobs) and silent in_progress→completed transitions (~170 in 2025) flagged in PR #247 are exactly this case — they require an emission-side audit, not a backfill, and that work is owned separately under this ADR's umbrella.
