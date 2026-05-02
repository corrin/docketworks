# 0017 — Zero backwards compatibility; rewrite every call site in one PR

When a name, URL, signature, or shape changes, every caller changes in the same PR. No deprecation aliases, no dual-name field readers, no parallel old-and-new endpoints, no `getattr` shims, no "for safety" columns retained.

## Problem

Backwards-compatibility shims are trivial to add and expensive to remove. Each one is one line; collectively they make the canonical name no longer canonical, leave two ways to do every operation, and quietly become permanent because removing them is always lower priority than the next feature. A reader of the codebase ends up unable to tell which name, URL, or shape is the real one — every name might be the legacy alias of something else.

## Decision

When something changes, change every caller in the same PR. Old name disappears in the same commit the new name appears. Old URL returns `404`, not a redirect. Old field is removed from the model, not kept null. Old serializer key is removed, not accepted-but-deprecated. Old SDK import path is gone, not re-exported. Tests and CI break loudly on stragglers; that's the point.

## Why

We value the future developer's reading experience over the migration hassle of changing every call site once. Direct rewrite is a one-time cost. Every shim is a cost paid forever — by every reader of the file, every reviewer of every PR that touches it, every assistant trying to orient. The "old way" stops being a real path the moment the rename lands, so leaving it in the codebase actively misinforms.

This is the umbrella principle behind several specific ADRs:

- **ADR 0006** — Old REST URLs return `404`; breaking the frontend is intentional and forces migration to the clean shape.
- **ADR 0015** — Consumers stay strict; data is repaired rather than read through a fallback.
- **ADR 0016** — Renamed identifiers remove the old name in the same commit, with no aliases.

## Alternatives considered

- **Deprecation cycle: keep the old shape working, mark it deprecated, remove it in a later release.** Strongly defendable for a public library or any codebase with external consumers who can't be edited atomically. Rejected here: this codebase has no external SDK consumers — frontend ships from the same monorepo (ADR 0008), there is no third-party API. The deprecation cycle's whole purpose is to give callers you don't control time to migrate; we don't have callers we don't control.
- **Compatibility shims behind a feature flag.** Defendable when a rollback risk is real. Rejected: a flag that both sides have to know about is itself a shim with the same forever-cost; we'd rather take the rollback risk on a clean change than carry the flag.

## Consequences

The codebase reads as a single coherent shape rather than as the union of its current and legacy shapes. Every name, URL, and field means exactly what it says. Cost: a rename or shape change is a wider PR than it would otherwise be — touching every caller is the work, not optional cleanup. Externally-coordinated changes (a third-party integration we don't control) need an explicit out-of-band heads-up rather than an in-codebase compatibility layer.
