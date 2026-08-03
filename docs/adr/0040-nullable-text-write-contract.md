# 0040 — Unset is NULL, and the request schema says so

Nullable text columns store NULL for "unset" and never `""`; the API request schema declares those fields nullable-and-nonblank so a blank string is a validation 400 instead of a database IntegrityError.

## Problem

KAN-329, live in v1 production: confirming a "price TBC" purchase-order line
fails with 409 when the line has no item code. The frontend rebuilt the whole
line and sent `item_code: ""`, the request serializer accepted blanks but not
`null`, the service assigned the blank straight to the model, and the
`item_code_not_blank` CHECK constraint raised `IntegrityError` — mapped to 409,
rolling back the user's price.

v1 had already written this rule down ("a nullable column says unset as NULL
and nothing else… serializers set `allow_blank=False`") — as prose in a
migrations section, enforced field by field. Five sibling fields on the same
model coerced blanks; `item_code` was forgotten. A rule maintained by hand in N
places drifts, and the drift is invisible until a user hits the one field
nobody remembered.

## Decision

A nullable text column means NULL when unset — never `""`, never a sentinel.
Enforce it at three layers that cannot disagree: the column carries a
`CHECK (col <> '')` constraint (admin, management commands and integrations all
bypass request validation); the request schema declares the field
nullable-and-nonblank through **one shared type** (`NullableText`), so `""` is
rejected with 422 before any service or query runs and `null` is how a client
clears a value; and services assign validated values directly, never coercing
with `value or None`. Clients clear by sending `null` or omitting the key.

## Why

The shared type is the point. Declared once, the constraint is inherited by
every field that uses it, by the generated OpenAPI schema, and by the generated
TypeScript client — so a newly added nullable field gets the contract for free
and no future editor can forget one. That makes the v1 failure mode
*structurally impossible* rather than merely discouraged.

Rejecting at the schema also puts the error where it can be acted on: 422 with
the offending field named, before the database, instead of an opaque 409 from a
constraint the client cannot see. That is ADR 0015's fail-early posture applied
to the write path, and ADR 0039's one-implementation rule applied to a
validation rule rather than to code. A `value or None` shim in the service
would satisfy the immediate symptom while leaving the contract ambiguous — the
client still cannot tell whether `""` means "clear it" or "I did not change it".

## Alternatives considered

- **Coerce blanks to NULL in the service.** The obvious minimal fix, and what
  v1 did for five of six fields. It hides the ambiguity rather than resolving
  it, has to be repeated per field (which is exactly how v1 drifted), and never
  reaches the generated client, so the frontend keeps sending a value the API
  claims not to accept.
- **Drop the not-blank CHECK constraints and allow `""`.** Defensible where the
  database is the only writer and blank-vs-NULL is a distinction without a
  difference. Rejected here because integrations, management commands and the
  admin all write outside request validation, and `""` vs NULL then splits
  every query and report in two.

## Consequences

One declaration site per rule; adding a nullable field needs no service change.
Clients must send `null` rather than `""` — a real contract change, recorded in
the parity ledger and covered by parametrised tests over the whole field set
(and, where a UI edits these fields, an E2E test of the flow that broke).
Existing v1 clients that send `""` receive a 422 naming the field, which is the
intended, diagnosable failure.
