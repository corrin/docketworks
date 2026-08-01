# ADR 0038 — Errors are transparent; rapid debugging outranks disclosure hygiene

## Status

Accepted (2026-08-02).

## Context

Docketworks is installed per client, on infrastructure the client controls,
with a handful of known, trusted staff users — currently one client and six
users. The operator relationship is close: when something breaks, the goal is
that whoever is looking at the screen (or the logs, or the AppError row) can
diagnose it *now*.

The conventional practice of masking error details at the API boundary comes
from a different world: multi-tenant SaaS with thousands of near-anonymous
users, where an exception message is attack surface and the person seeing the
error is never the person fixing it. That mental model is a poor fit here and
importing its reflexes actively harms our dominant operational concern —
rapid error resolution.

## Decision

- API error envelopes carry the **real exception message verbatim** at every
  status, including 500. Every envelope also carries `error_id`
  (ADR 0013) linking to the persisted AppError row.
- Auth rejections state their **specific reason** ("User is inactive.",
  token-validation errors) rather than a generic 401 string.
- In general: transparency is the default and **masking requires
  justification**, not the reverse. Secrets (keys, passwords, tokens) are
  still never echoed — transparency is about failure *causes*, not
  credential material.

## Consequences

- Faster diagnosis for users, support, and AI agents reading envelopes,
  logs, or AppError rows.
- A modest widening of what an authenticated (or in the 500 case, any) caller
  can learn about internals — accepted within this trust boundary.
- If Docketworks ever becomes multi-tenant or internet-exposed to untrusted
  users, this ADR must be revisited before that launch.
