# 0059 — The app supports one data model; legacy data is migrated to comply

Every record has exactly one supported shape. Data written in an older shape is rewritten to comply by a one-off migration, and no code is written that can read the old shape.

## Rules

- The migration is the only place that knows the old shape, it runs once, and after it has run nothing in the codebase mentions that shape at all — not a column, not a model, not a branch, not a flag, and not a comment describing what old rows look like.
- Where the old value cannot be reconstructed, the migration still decides one canonical value and writes it, or deletes the row. Best effort is the requirement: an approximate value every reader can trust beats an accurate absence every reader must handle.
- A nullable column added because historical rows have no value for it is the same workaround moved into the type system (ADR 0015). Backfill it and make it `NOT NULL`, or do not add the column.
- A model, table or column whose purpose is to describe data the app no longer produces is a second data model. Its name usually says so.
- Migrating the data is the whole job: reconstructing it, rehearsing the migration against a restored copy, and deleting the transitional code in the same release.
- Where the existing model already has a representation for the fact, use it rather than inventing one — the shape that records "this happened historically and left no balance" is normally already present for the cutover that first needed it.

## Do not

- **A permanent record acknowledging that some rows are different** — the acknowledgement outlives every reader who knew why, and each new reader must then handle both shapes.
- **A comment saying the model can be deleted once the data is reconciled** — nothing reconciles it, so the deletion point never arrives. Do the migration now instead.
