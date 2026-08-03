# 0026 — Plan the tests before the plan is approved

A work plan is not ready for approval until it names the tests the work owes.

## Rules

- The plan names each owed test, its layer, and what it guards, before approval:
  - **User-facing behaviour** (a screen, a flow, a value an operator depends on) owes an end-to-end test that drives the real UI through the real API; a backend unit test is not a substitute. Naming the E2E at plan time is also a completeness check — a capability that cannot yet be driven end-to-end is missing scope (often the management surface, ADR 0027), and the planned test exposes that before any code exists.
  - **Complex or editable logic** (a calculation, an invariant a teammate might refactor) owes a unit test at that logic's contract.
- A change can owe both; a purely mechanical change may owe neither — but "no test, because…" is a decision recorded in the plan, never a silent omission.
- A bug-fix plan names the test that would have failed before the fix and passes after. "No new test" requires stating why the suite already covers it or why no useful automated boundary exists (ADR 0025).
- Tests designed before the code pin **purpose**, not implementation: if changing the code's purpose wouldn't fail the test, or changing only its implementation would, the test is wrong. Tests written after the code assert whatever the code already does — green by construction, guarding nothing, taxing every future edit.
