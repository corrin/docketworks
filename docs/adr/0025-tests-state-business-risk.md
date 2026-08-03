# 0025 — Every test guards against a plausible regression

Every test states what regression it catches and why the assertion would fail if that regression were introduced.

## Rules

- Every test carries a docstring (or nearby comment) answering: **what change could a teammate make that this test would catch, and why would this assertion fail then?** "Tests that inactive staff are excluded" is not enough; the expected shape is "A query refactor could drop the leave-date predicate, and this test catches it by creating a staff member who left before the target date." A class-level docstring suffices only when every test in the class guards the same regression surface.
- If the answer is "Python/Django/the framework breaks", delete the test — we test our code only.
- Test the algorithm's contract — inputs and observable outputs — not implementation internals. Asserting internals (`CaptureQueriesContext`, private method calls) is allowed only when the internal is itself the regression risk (an accidental N+1) and no contract-level test covers the same risk.
- A real bug that escaped the suite owes its regression test at the contract boundary that failed — the strict consumer that enforces the shape, not the easiest internal side effect. The classic miss: the write-path test passes while a strict reader cannot parse what was stored; the owed test exercises that reader.
- Temporary operational code with a planned deletion point gets no permanent regression tests — validate with rehearsal, dry-run, runbook, or operator evidence. Durable contracts the work leaves behind (data shape, deploy semantics, API behaviour, permissions) are tested even when the rollout that introduced them was one-off.
- E2E selectors: elements the tests drive or assert against expose stable `data-automation-id` attributes. Never depend on incidental DOM position (`nth(3)`, "the next card") for values or controls whose meaning matters.
- An E2E wait on a mutation's response matches URL and method only — never status — then asserts success explicitly, with the actual status and body in the failure message. A status-filtered wait can never match a real failure, so a failed mutation surfaces as a generic timeout that hides exactly the regression the wait exists to catch.
- When reviewing an existing test, sort it: **good** (states and catches a plausible regression) / **needs comment** (catches one, doesn't state it) / **rewrite** (right risk, wrong boundary) / **delete** (no plausible regression nameable, or a better test covers it). Tests may be deleted during refactors when no regression can be articulated.
