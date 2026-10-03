# Test review — 2026-10-03

GPT: This review starts at `1f87fd1` on `chore/test-ci-cleanup`. Its criterion is:
**would a developer rewriting the application code make plausible mistakes that this
test catches?** Library adapters and application configuration contracts can earn
tests. A test need not catch every possible mistake, and a surviving mutation alone
is not a reason to delete it.

## Backend CI order

Metrics now run immediately after dependency installation, followed by status-table
and schema checks; pytest runs last. No check was removed. The first branch run
([37074896919](https://github.com/corrin/docketworks/actions/runs/37074896919))
failed at metrics and stopped the backend job in 54 seconds, with pytest skipped.
Generated reports are refreshed with the test changes.

## Scope and decisions

The review reconciled exactly with the baseline inventory:
3,053 Python definitions and 849 TypeScript definitions, including browser tests and
18 frontend harness definitions. Two additional TypeScript definitions arrived on
`main` through `ed1b69a` during the review and were also reviewed: **3,904 definitions
in total**. They assert literal weekday headers on the two single-day timesheet pages.
The review also covered 140 shell assertion sites in three scripts. Parameterized definitions and shell loops count once here; executed
case counts below therefore differ from the inventory.

| Source definitions | Keep | Strengthen | Delete |
| --- | ---: | ---: | ---: |
| Python and TypeScript | 3,855 | 41 | 8 |
| Shell assertion sites | 140 | 0 | 0 |

Each decision records behavior, a plausible application mistake, and review evidence.
Kept tests received static assertion/contract review; setup and implementation were
inspected where the contract was ambiguous. They were not all mutation-tested.
The initial 38 strengthened definitions have targeted mutation evidence, followed
by restored-code runs. Two additional purchase-order scenarios have real-vendor
verification after correcting ownership fixtures and misleading readback assertions.
One further repair loads the live credentials/tenant for the recordings check; its
vendor comparison remains unverified after the quota floor was reached.
All temporary application mutations were removed. No application behavior or coverage
threshold changed in this cleanup.

The detailed per-test ledger is retained locally at `docs/test-review.json`,
untracked and gitignored. It is not part of the PR or available in a fresh clone.
This report retains the decisions, representative mutation evidence and validation
results needed to review the change.

## Deletions

| Deleted check | Reason and retained protection |
| --- | --- |
| Parser provider constant comparison | Compared constants; the prompt/gateway test checks provider selection on the actual call. |
| Price-extraction docstring headings | Documentation copy does not exercise extraction behavior. |
| Phone-call tab constant copy | Rendered phone-call tests retain tab titles and query wiring. |
| TanStack URL serialization demonstration | Calls library/native functions only; application query round trips remain. |
| Missing quote relation forced by monkeypatch | Fabricates an unreachable state despite the non-null restricted relation and job initialization; real empty quotes, missing jobs and revisions remain. |
| Absence of removed process history manager | Obsolete library attribute check; real ProcessEvent audit behavior remains. |
| Webhook allowlist membership | Redundant entry because the login middleware already passes API routes through; anonymous signed request and dispatch tests remain. |
| Beat task importable as Python attribute | Celery dispatches registered names, which need not be import paths; the actual registry contract remains. |

Removed obsolete body-class/SortableJS absence assertions from three drag tests while
retaining actual drag, card visibility, cardinality and column-highlight checks. These
are retained tests, not three additional deletions. Timestamp-offset and password-
whitespace tests from calibration remain because application parsing/normalization
can plausibly break them.

## Strengthened behavior

The repaired definitions replace weak fixtures, self-derived expectations or
key/count-only checks with distinguishing outcomes. Examples:

- Pagination asserts actual second-page records; ordering fixtures contain competing rows.
- Incremental scraping observes saved rows between pages, including the final partial batch.
- API-key refusal preserves the original secret and emits none; creation prints it once.
- A registered migration transforms historical rows rather than merely importing its helper.
- Company provider calls observe the phone at call time, and creation uses nondefault flags.
- Process updates advance persisted timestamps; archived references are refused and labels resolve.
- Job timelines contain a real event, reopening persists state, and refreshed PDFs replace bytes.
- Stock eligibility distinguishes partially populated rows and verifies actual queued dispatch.
- Stock timestamps preserve the exact offset-aware instant, not merely its year/date prefix.
- Xero seeding uses a genuine rounding tie and a disabled-to-enabled transition; client proxies forward after reset.
- Accounting expectations derive from independently seeded approvals, not returned output.
- Diagnostics wrappers must execute children, transfer bytes/environment and reap a failed pipeline's producer.
- Frontend dirty-row saves, image URL snapshots and deletion rollback use fixtures that expose accidental changes.

For example, replacing offset preservation with `replace(tzinfo=UTC)` passed both old
stock timestamp tests and failed both repaired tests. Skipping PDF refresh passed the
old count/subset checks and failed the new dispatched-job/content assertions. Mutations
were restored before final verification; production code is unchanged in the branch.

## Verification

- Backend baseline: 3,397 passed; 90.10% coverage, 743.45 seconds.
- Combined final backend: 3,393 passed; 90.10% coverage, 1,351.06 seconds.
  Six Python test deletions and two additional parameter cases explain the net reduction
  of four executed unit cases. The final mock-target typing correction additionally
  passed all 18 tests in the diagnostics subprocess module.
- Frontend baseline: 697 passed. Cleanup before merging main: 695 passed. Final after
  merging the two weekday-header tests: 697 passed across 98 files, 178.66 seconds.
  Coverage unchanged: 60.51% statements, 53.12% branches, 55.90% functions and 61.46% lines.
- Initial frontend runs at default concurrency timed out under host load. The baseline
  passed with four workers and final coverage with two, without changing test timeouts.
- Domain runs passed before integration: job/purchasing/timesheet 1,041 cases,
  Xero/accounting/platform 984, company 176, diagnostics 154, config/scripts 258;
  affected-module and restored-mutation runs also passed. These overlapping counts are
  verification evidence, not extra inventory entries.
- Frontend lint/type checking and Playwright discovery passed (175 browser cases in
  59 files). Discovery is not browser execution.
- Release-utils and server-template shell suites passed. The Docker/UFW suite was
  skipped because Docker was unavailable to its runner; static review is not execution.
- Live integration on `198c45a`: 29 passed, 4 failed in 1,107.07 seconds. See below.
  After repairing purchase-order tests, that module passed four cases, including both
  changed scenarios; three later cases stopped at the configured daily quota floor
  of 100. No quota override or retry.
- E2E execution is deferred by the owner's explicit choice to keep the existing
  development stack running. Its fixed ports and database reset/restore cannot safely
  share that stack. The PR remains draft; this is not a green release gate.

## Findings and limitations

The integration failures are preserved, not hidden by weakened expectations:

1. CRM portal credentials (base URL, username and password) are not configured.
2. The Xero fake-recordings freshness check omitted the opt-in credential fixture and
   inherited a fake unit-test tenant. This is a test setup defect, not evidence that
   the development environment lacks Xero credentials. The fixture now explicitly
   loads those credentials and shadows the unit tenant fixture. Full catalogue
   verification is deferred because the integration runs reached the daily quota floor.
3. The purchase-order test used a `TEST-<hex>` number while claiming local ownership;
   the documented rule is the instance prefix plus decimal digits. Its quantity
   overwrite was correct for that fixture. The repaired test uses a unique locally
   owned number and reads the actual vendor quantity and deletion status. A second
   scenario now checks the documented explicit-push policy instead of claiming an
   obsolete automatic collision resolver. Both repaired scenarios passed live.
4. The outbound-link probe reported the fake invoice URL in
   `frontend/src/test/crmJobRow.ts` as HTTP 404. The fixture now uses a reserved example
   domain, recognized by the existing probe exclusions. The rendered href assertion
   remains and both affected component tests pass; a source scan confirms the fake
   invoice is no longer emitted as an application link.

A separate local reproduction confirmed payroll synchronization can rename/link
matched employees before discovering that an unmatched employee needs a missing
company address. The old test covered only unmatched creation; its name now states
that narrower guarantee. The [history entry](rewrite-history.md#2026-10-03--systematic-test-review)
records a reproducible mixed-batch failure. Application fixes remain outside this cleanup.

The purchase-order inbound-deletion unit test exercises the transform directly;
`sync_entities` skips deleted rows before that transform. It does not prove end-to-end
inbound deletion. More generally, a reviewed test suite and coverage percentage do
not establish complete application coverage. The browser/integration gates remain
visibly incomplete.
