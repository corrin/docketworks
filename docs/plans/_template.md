# Title

## Context

Why this change is being made — the problem or need it addresses, what prompted it, and the intended outcome.

## Feature Parity Inventory

**Required for any work that replaces or rewrites an existing component, page, model, or endpoint. Delete this
section only if the change adds net-new behaviour that replaces nothing.**

Enumerate every capability the OLD version exposed (buttons, actions, fields, shortcuts, edge cases — sourced
from its template/emits, its tests, E2E specs, ADRs). One row per capability. Default decision is **keep**;
**drop** requires explicit user sign-off; **defer** requires a ticket.

| Old capability | New location | Status (keep / drop+signoff / defer) |
|---|---|---|
| … | … | … |

## Approach

The recommended implementation. Name the critical files to be modified. For a pattern repeated across many
files, describe it once with a few representative paths.

## Files to modify

- …

## Verification

How to test end-to-end: run the code / drive the real flow, plus the tests to run.
