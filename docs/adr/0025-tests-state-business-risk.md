# 0025 — Every test guards against a plausible regression

Every test states what regression it catches and why the assertion would fail if that regression were introduced.

## Rules

- Every test carries a docstring (or nearby comment) answering: **what change could a teammate make that this test would catch, and why would this assertion fail then?** "Tests that inactive staff are excluded" is not enough; the expected shape is "A query refactor could drop the leave-date predicate, and this test catches it by creating a staff member who left before the target date." A class-level docstring suffices only when every test in the class guards the same regression surface.
- **A unit test exists only when all three of these can be named, and the docstring names them.** A unit test guards a Docketworks algorithm against a bug a developer might introduce; nothing else earns one.
  1. **A block of code inside Docketworks.** Not a library's arithmetic, not a vendor's data, not a framework default. If the value the assertion checks is produced outside this repository, there is nothing of ours to guard.
  2. **An edit to that block a competent developer might make.** A refactor that drops a predicate, a reordering, a changed default, a boundary moved by one. An edit nobody competent would consider is not a regression, and a test waiting for it is busy work.
  3. **That edit fails this assertion.** Proven by making the edit, running the test, and restoring (ADR 0052).
  If any one cannot be named, there must not be a unit test.
- If the answer is "Python/Django/the framework breaks", delete the test — we test our code only.
- **At plan time.** A plan names each test the work owes — its layer and what it guards — before approval. User-facing behaviour (a screen, a flow, a value an operator depends on) owes an end-to-end test that drives the real UI through the real API, seeded to production volume (ADR 0054); a backend unit test is no substitute, and a capability that cannot yet be driven end-to-end is missing scope, often its management surface (ADR 0027). Complex or editable logic owes a unit test at its contract. A bug-fix plan names the test that failed before the fix and passes after. "No test, because…" is a decision recorded in the plan, never a silent omission. Tests designed before the code pin purpose (ADR 0052); tests written after it assert whatever the code already does.
- **Deciding the regression is half the work.** ADR 0052 decides whether the assertion can see it, ADR 0054 whether the data can produce it, and ADR 0063 the conventions every test in this suite follows.
- Test the algorithm's contract — inputs and observable outputs — not implementation internals. Asserting internals (`CaptureQueriesContext`, private method calls) is allowed only when the internal is itself the regression risk (an accidental N+1) and no contract-level test covers the same risk.
- A real bug that escaped the suite owes its regression test at the contract boundary that failed — the strict consumer that enforces the shape, not the easiest internal side effect. The classic miss: the write-path test passes while a strict reader cannot parse what was stored; the owed test exercises that reader.
- Temporary operational code with a planned deletion point gets no permanent regression tests — validate with rehearsal, dry-run, runbook, or operator evidence. Durable contracts the work leaves behind (data shape, deploy semantics, systemd/Celery setup, API behaviour, permissions, user-facing code) are tested even when the rollout that introduced them was one-off.
- When reviewing an existing test, sort it: **good** (states and catches a plausible regression) / **needs comment** (catches one, doesn't state it) / **rewrite** (right risk, wrong boundary) / **delete** (no plausible regression nameable, or a better test covers it). Tests may be deleted during refactors when no regression can be articulated.

## Do not

- **Assert a value that something outside Docketworks produces** — a vendor's price list, a library's cost arithmetic, a framework's serialisation. Such a test retires with the first external change, and until then it guards a number we do not own; re-pointing it at the vendor's next model or version is catch-up, not a fix. Delete it.
- **Keep a test because the code path exists** — a mapping, a loop or a branch that is too simple to get wrong has no edit a competent developer would make that the test would catch.
