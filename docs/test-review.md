# Test review — 2026-10-03

This review starts at `1f87fd1` on `chore/test-ci-cleanup`. Its criterion is:
**would a developer rewriting the application code make plausible mistakes that this
test catches?** Library wrappers and configuration contracts can earn tests. A test
need not catch every possible mistake.

The [per-test ledger](test-review.json) records the actual reviewed identifiers,
behaviour, rewrite risk, decision and evidence. **This is an ongoing review:**
identifiers absent from the ledger have not been signed off. Inventory and test
execution are not substitutes for reviewing an assertion against its implementation.

## Baseline

- Backend: 3,397 passed, 90.10% coverage, 743.45 seconds.
- Frontend: 697 tests passed with four workers; coverage was 60.51% statements,
  53.12% branches, 55.90% functions and 61.46% lines. Default concurrency produced
  initial-data timeouts under host load (12 failures, then 37 on a repeat); a focused
  rerun and the four-worker full suite passed without changing tests or timeouts.
- Live integration and E2E gates have not yet run for this review.

## First batch

Deleted the parser-provider constant comparison and price-extraction docstring-heading
check. Provider selection remains checked on the actual parser gateway call in
`TestPrompt.test_the_prompt_the_model_receives_is_the_rendered_one`.

Strengthened four tests and deliberately broke their application code:

| Guarantee | Mistake introduced | Observed failure |
| --- | --- | --- |
| Incremental scraper saving | Defer all writes until the last page | Persisted counts `[0,0,0,0,0,5]` instead of `[0,0,2,2,4,5]` |
| Cleared item code clears Xero status | Omit the reset for an absent code | Stale `True` instead of `False` |
| Requested menu order wins | Sort by name instead of configured order | Reversed expected menu items |
| Record both input and output spend | Omit output cost | `0.00012` instead of `0.00046` |

All four mutations failed at their intended assertions and were restored. The cost
test now supplies controlled vendor prices rather than pinning LiteLLM's live table.
The affected suite passed 126 tests before the mutation experiment; the restored
implementation then passed all 88 tests in the four modules containing strengthened tests.

The timestamp-offset and password-whitespace tests from the calibration discussion
remain: they catch plausible mistakes in application parsing and normalisation.
