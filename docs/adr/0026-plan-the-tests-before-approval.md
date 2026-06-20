# 0026 — Plan The Tests Before The Plan Is Approved

A work plan is not ready for approval until it names the tests the work owes; tests are designed during planning, not after the code.

## Problem

Plans get approved describing what to build; the tests appear afterwards, written against
whatever code emerged. Two failures follow. The labour-subtype work was user-facing —
operators set per-install rates — so it owed an end-to-end test. Had that test been named
in the plan, it would have driven the UI to change a rate and **failed, because no UI
existed** — surfacing the missing management surface at plan time, not in production.
Instead no E2E was planned, and the unit tests that did appear re-asserted the
implementation just written: green by construction, guarding no regression, taxing every
future edit.

## Decision

The tests a change owes are part of its plan, named and agreed **before the plan is
approved** — TDD lifted to the planning step. A plan that does not say what will be
tested, at which layer, and what each test guards is not ready for approval.

Choose the tests by the risk the work carries:

- **User-facing behaviour** (a screen, a flow, a value an operator depends on) owes an
  **end-to-end test** that drives the real UI through the real API. A backend unit test is
  not a substitute for proving the flow works.
- **Complex or editable logic** (a calculation, an invariant a teammate might refactor)
  owes a **unit test** at that logic's contract.

A change can owe both; a purely mechanical change may owe neither — but "neither" is a
decision recorded in the plan, not a silent omission.

Bug-fix plans name the regression test the bug owes. If a real user-impacting bug escaped
the suite, the plan names the test that would have failed before the fix and now passes;
"no new test" is acceptable only when the plan states why the existing suite already
covers the bug or why no useful automated boundary exists (see
[ADR 0025](0025-tests-state-business-risk.md)).

Because the tests are designed before the code, they pin **purpose**, not implementation:
a test that mirrors the code just written guards nothing and must instead assert the
business contract (see [ADR 0025](0025-tests-state-business-risk.md)). If changing the
code's purpose wouldn't fail the test, or changing only its implementation would, the test
is wrong.

## Why

Designing tests after the code is what produces change-detectors: with the implementation
in front of you, the path of least resistance is to assert what it already does — green
the day written, red the day someone improves the code, never red the day behaviour
regresses. Deciding the tests against intent, before the code exists, is the only point at
which they can be designed to catch a regression rather than describe a line. Naming the
E2E at plan time does more than schedule a test: it is a completeness check on the work
itself — a user-facing capability that cannot yet be driven end-to-end is not buildable as
specified, and the planned test exposes that before code, forcing the missing surface into
scope ([ADR 0027](0027-deploy-capability-with-its-controls.md)).

## Alternatives considered

- **Write tests after implementation, judged at review** — common and flexible. But by
  review the tests are already shaped by the code, the change-detectors are already
  written, and a missing E2E is a gap to relitigate rather than a plan item that was agreed.
- **Coverage targets** — mandate N% line coverage instead of reasoned, planned selection.
  Coverage rewards volume over relevance and is trivially met by change-detectors that
  guard nothing — the failure mode this ADR exists to stop.

## Consequences

Plans carry a short test section: the tests owed, their layer, and what each guards —
reviewed and agreed before implementation. User-facing work therefore carries an E2E test
(Playwright against live endpoints — slow; see the E2E discipline in `CLAUDE.md`) by
design. Trivial work records "no test, because…" and moves on. Some change-detector tests
get deleted rather than maintained.
