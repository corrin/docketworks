# 0027 — A capability deploys with the means to operate it

A change that introduces operator-governable state ships the surface to see and change that state in the same increment.

## Rules

- When a change introduces state an operator is expected to read, set, or retire — rates, catalogues, toggles, anything tunable per install — the surface to manage that state ships in the same deployable increment. Config that requires a migration to change is a broken deploy, not a smaller ticket.
- Scope work by deployable capability, not ticket boundaries. A ticket split that strands the means of control is a planning artifact, not a licence to ship half a feature; estimate "add labour subtypes" to include managing them.
- Reporting and analysis built *on top of* a capability are a separate unit and may ship later. The means to *operate* it may not.
- The E2E test named at plan time (ADR 0026) is the tripwire: planning a test that drives operating the capability exposes missing controls before any code exists, and the test fails while they remain absent.
