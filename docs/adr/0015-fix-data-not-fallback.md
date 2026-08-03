# 0015 — Fix incorrect data; do not add read-side fallbacks

When a consumer finds data that violates the model's contract, repair the data; never soften the consumer.

## Rules

- Fix the data, in order of preference: (1) a data migration that reconstructs the canonical field from another in-row source; (2) an emission-side fix that stops wrong data being produced; (3) both. Data migrations are dry-run and verified before applying.
- The consumer stays strict: no `COALESCE`, no "if empty, read the other field", no schema relaxation, no tolerant parsing. A fallback makes the canonical field non-canonical for every future reader, and once readers cope, nothing ever forces the data to be fixed.
- If rows genuinely cannot be reconstructed (e.g. events never emitted because a `.update()` bypassed `save()`), escalate — raise, alert, leave them visibly broken — and record the unrecoverable subset as an emission-audit task. Never silently degrade.

## Do not

- **The one-line read-side fallback** — it spreads: the same workaround appears in service B, then C, and the field is authoritative nowhere.
- **Making the field optional to accommodate bad rows** — the same workaround moved into the type system, where it is harder to see and outlives everyone's memory of why.
