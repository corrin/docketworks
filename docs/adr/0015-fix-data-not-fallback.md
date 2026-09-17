# 0015 — Fix incorrect data; do not add read-side fallbacks

When a consumer finds data that violates the model's contract, repair the data; never soften the consumer.

## Rules

- Fix the data, in order of preference: (1) a data migration that reconstructs the canonical field from another in-row source; (2) an emission-side fix that stops wrong data being produced; (3) both. Data migrations are dry-run and verified before applying.
- The consumer stays strict: no `COALESCE`, no "if empty, read the other field", no schema relaxation, no tolerant parsing. A fallback makes the canonical field non-canonical for every future reader, and once readers cope, nothing ever forces the data to be fixed.
- If rows genuinely cannot be reconstructed (e.g. events never emitted because a `.update()` bypassed `save()`), escalate — raise, alert, leave them visibly broken — and record the unrecoverable subset as an emission-audit task. Never silently degrade.
- Fable: when validation rejects data that production has held and used for years, suspect the model before the data. ADR 0028 presumes the contract right where code and contract disagree; long-standing real data is the one witness that outranks both, and a contract it fails is a contract written too tight (the 2026-08-04 scan flagged 63 rows, 32 of them a too-strict contract and one "junk" line holding $119.50).
- Where a component owns its query it reports its own pending and error states; where a caller owns the query, the caller resolves both before rendering and passes a value the child can trust. Optional loading and error props that default to false are refused: a caller that forgets them gets "nothing is wrong", which is the read-side fallback one level up (the JobPicker coalesced a pending, a failed and an empty status list into one empty map).

## Do not

- **The one-line read-side fallback** — it spreads: the same workaround appears in service B, then C, and the field is authoritative nowhere.
