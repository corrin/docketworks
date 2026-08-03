# 0040 — Unset is NULL, and the request schema says so

Nullable text columns store NULL for "unset", never `""`; the schema rejects blanks before the database.

## Rules

- A nullable text column means NULL when unset — never `""`, never a sentinel. Clients clear a value by sending `null` or omitting the key.
- Three layers enforce it and cannot disagree:
  1. the column carries `CHECK (col <> '')` — admin, management commands, and integrations all write outside request validation;
  2. the request schema declares the field through the shared `NullableText` type, so `""` is a `422` naming the field before any service or query runs;
  3. services assign validated values directly.
- New nullable text fields declare `NullableText` and inherit the whole contract — including through the generated OpenAPI schema and TypeScript client — so no future field can be forgotten.
- The `null`-not-`""` write contract is a real client-facing change: it is recorded in the parity ledger and covered by parametrised tests over the whole field set, plus an E2E test of any UI flow that edits these fields.

## Do not

- **`value or None` in a service** — it hides whether the client meant "clear it" or "I didn't change it", and per-field coercion is exactly how v1 drifted: five sibling fields remembered, `item_code` forgotten, and users hit the CHECK constraint as an opaque `409` that rolled back their edit.
- **Dropping the CHECK constraints to allow `""`** — non-API writers bypass the schema, and `""`-vs-NULL then splits every query and report in two.
