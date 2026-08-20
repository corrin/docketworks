# 0052 — A test survives a rewrite and fails a behaviour change

Design every test so that a total rewrite of the implementation would leave it passing, and so
that any change to what the code guarantees would make it fail. A test that has to be deleted
when its feature is rewritten was testing the implementation, and a test that keeps passing when
the guarantee is removed was testing nothing.

ADR 0025 decides **which** regression a test guards. This one decides **whether the assertion can
see it** — and the two-sided check above is how you find out, before writing the assertion rather
than after the rewrite.

## Rules

- **Ask both questions before choosing the assertion.** *If someone reimplemented this from the
  requirement alone, would my test still pass?* If no, it is pinned to today's code — the wrong
  boundary, an internal, a message string, a call order that is incidental rather than required.
  *If someone removed the guarantee, would my test fail?* If no, it is asserting something true
  either way. Both answers must be yes; either one alone is satisfiable by a useless test.
- **Prove the second question by breaking the code.** Revert or comment out the line under test,
  run it, confirm it fails, restore. A test never seen to fail is an assertion about nothing, and
  this costs under a minute — which is the whole argument for doing it every time. Where the fix
  was a reordering rather than an addition, move the call back and re-run; the ordering is the
  property.
- **Assert against the requirement's own vocabulary.** State the expectation in the terms the
  business states it in — this week's hours reach Xero once, a blocked week is refused before
  anything is spent, a leave day debits a balance — and reach for the code only to drive it.
  Assertions written by reading the implementation inherit its mistakes and its shape, which is
  how a suite ends up being the same program written twice.
- **Where the property is a cost, an order or a count, assert the count.** A refusal that happens
  before any external call reads identically to one that happens after a hundred of them, so the
  message is invariant across the fix. Record the would-be calls in a list, assert the list, and
  put the meaning in the assertion message
  (`assert xero_writes == [], "a locally-knowable refusal spent Xero calls to reach"`). The same
  holds for queries, retries and writes.
- **Never assert a definition.** `timesheet + leave_api + xero_computed == total` cannot fail
  while `timesheet` is computed as `total - leave_api - xero_computed`; it tests subtraction and
  survives every rewrite for the wrong reason. Two values meant to agree must come from two
  independent paths — the split the report shows against the split actually posted, line for line.
- **Reach the code through the door the product uses.** Test setup that uses `.update(...)`,
  `bulk_create`, raw SQL or a hand-built object skips `save`, `clean`, signals and the service
  owning the write, so it never crosses the code under test — and it will keep passing through a
  rewrite by never having executed the thing that was rewritten. Three live defects survived a
  full suite that way in August 2026: every test nulled a pay item with a queryset `.update()`, so
  nothing exercised the validation that still forbade NULL, the service that still copied the
  wrong pay item, or the settings write that silently did nothing. Fixtures may take shortcuts to
  reach an unrelated starting state; the path under test may not.
- **Treat a test that a rewrite invalidates as a finding, not a chore.** Requirements survive
  rewrites — that is what makes them requirements — so deleting a test during one is evidence
  about the test. The requirement it should have asserted is still untested, and the rewrite is
  when to write it.
- **Assert one property per test, and let its name say which.** A test asserting the refusal, the
  message, the count and the resulting state fails for four reasons and diagnoses none.
- **Pair a refusal with its converse.** A guard that refuses everything passes every test written
  about refusing. The blocked week must be refused; the same week's own draft must still post.

## Do not

- **Assert the error message and call the guard covered** — the message is usually identical
  before and after the fix, which is why the gap survived long enough to need one.
- **Add a test to a suite you have not seen fail** — a green run of a new test proves the test
  ran, not that anything is guarded.
- **Mirror the implementation's structure in the test's structure** — one test per branch, named
  after the branch, is a copy of the code rather than a check on it, and every one of them dies
  the day the branches change.
