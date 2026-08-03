# 0017 — Zero backwards compatibility; rewrite every call site in one PR

When a name, URL, signature, or shape changes, every caller changes in the same PR.

## Rules

- The old name disappears in the same commit the new one appears. Old URL → `404`, not a redirect. Old model field → removed, not kept null "for safety". Old serializer key → rejected, not accepted-but-deprecated. Old import path → gone, not re-exported.
- Tests and CI breaking on stragglers is the mechanism working: fix the straggler.
- This codebase has no callers it does not control — the frontend ships from the same monorepo (ADR 0008) and there is no third-party API. The exceptions are the externally held URLs listed in CLAUDE.md's porting rules (Xero OAuth/webhook, CRM phone ingestion, ServiceApiKey consumers); changes there are coordinated with the external party, not shimmed in code.
- The `xero_*` model fields kept null on a non-Xero installation (ADR 0012) are not "old fields kept for safety" — they are the active provider strategy's columns and stay.

## Do not

- **Deprecation aliases, `getattr` shims, dual-name readers** — each is one line to add and permanent to carry; collectively every name becomes possibly-the-legacy-alias of something else, and the canonical name stops being canonical.
- **Compatibility behind a feature flag** — the flag is itself a shim both sides must know about; take the clean change and accept the rollback risk.
