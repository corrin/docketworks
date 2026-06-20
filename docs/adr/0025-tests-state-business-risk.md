# 0025 — Every Test Guards Against A Plausible Regression

Every test must state what regression it catches and why that regression is plausible.

## Problem

Tests that assert language or framework behavior waste time: they lock
implementation details, inflate change cost, and make maintainers preserve
assertions that protect nothing. A test proving that `x + x` returns `2*x`
or that a `for` loop visits every element is testing Python — not our code.
Python is not going to suddenly break.

## Decision

Every test must include a docstring or nearby comment that answers: **what
change could a teammate make that this test would catch, and why would this
assertion fail if that regression were introduced?**

Do not merely describe what the test does. "Tests that inactive staff are
excluded" is not enough; "A query refactor could drop the leave-date predicate,
and this test catches it by creating a staff member who left before the target
date" is the expected shape.

If the answer is "Python, Django, etc" then delete the test.  We are testing our code only.

A class-level docstring is sufficient when all tests in that class guard the
same regression surface; but more commonly individual tests need their own comment.

The regression surface can be anything our team might accidentally break: a
calculation, a query shape, a response contract, a permission boundary, a data
integrity invariant — whatever. The test checks the algorithm's contract (its
inputs and observable outputs), not the implementation's internal mechanics.
Asserting on implementation internals (e.g., `CaptureQueriesContext`, private
method calls, branch coverage) is acceptable only when those internals
themselves are the regression risk (an accidental N+1, for example) and no
algorithmic-level test already covers the same risk.

Every real bug that could hit a user and escaped the existing suite is evidence
that the suite did not fully test the data model or behavioural contract it was
claiming to protect. The fix must add a regression test at that contract
boundary — the strict consumer that enforces the shape — not at the easiest
internal side effect. The classic miss: a write that succeeds, so the write-path
test passes, while a strict reader the data later feeds cannot parse what was
stored. The owed test exercises that reader, not just the write, and enforces the
shape rather than softening it ([ADR 0015](0015-fix-data-not-fallback.md)).

When reviewing an existing test, sort it into one of four outcomes:

- **Good:** it already states a plausible regression and catches that regression.
- **Needs comment:** it catches a plausible regression, but the regression is not
  stated in a docstring or nearby comment.
- **Rewrite:** it points at a plausible regression, but the test does not
  actually catch that regression at the right boundary.
- **Delete:** no plausible project regression can be named, or a better test
  already covers the same risk.

## Why

Tests that cannot articulate a plausible regression are dead weight. They make
changes harder without catching bugs. Requiring the regression to be stated
makes review and deletion decisions straightforward: if you cannot name the
breakage this guards against, the test is serving no one.

## Consequences

Tests may be deleted during refactors when no plausible regression can be
articulated. New tests carry a small writing cost, but the suite should be
smaller, clearer, and more defensible. Tests that guard the same regression
through implementation internals while an algorithm-level test already covers
it are redundant and should be removed. Bug fixes carry their regression tests
with them; "no new test" is an explicit review decision, not a silent omission.
