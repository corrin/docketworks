# PDF Golden Tests — Print Job and Print Delivery Docket

Design spec for byte-identical regression tests covering the two user-facing
PDFs the system produces: the workshop PDF (Print Job) and the delivery docket
(Print Delivery Docket).

## Relates to

This spec sits alongside
[`docs/plans/2026-04-25-delivery-docket-staff-fk.md`](./2026-04-25-delivery-docket-staff-fk.md),
which fixes the underlying staff-FK bug in six JobEvent-emission sites and
commits the DocketWorks logo PNGs to `mediafiles/app_images/`. Both pieces
are parts of the same delivery — "fix broken delivery dockets, including the
test". The staff-FK plan is the real-world fix; this spec is the
byte-identical regression guard that will catch any future rendering drift.
The implementation plan (produced next via `writing-plans`) will unify both
into a single file-by-file sequence.

## Goal

Produce the same PDF bytes on every test run, for both outputs. A committed
golden PDF in the repo is the oracle; the test asserts raw byte equality.
Any drift — intentional or accidental — fails the test and forces a
deliberate regeneration.

This directly addresses the class of regressions the staff-FK bug sat inside:
the rendering pipeline silently returned a PDF that was "still a PDF" but was
behaving differently. Byte equality is the strictest possible contract.

## Non-goals

- Determinism in production. Real PDFs keep their `CreationDate`/`ModDate`
  metadata; customers get real wall-clock timestamps in "Delivery Date:".
- Semantic-layer assertions about JobEvent attribution. The existing
  `apps/job/tests/test_delivery_docket_service.py` covers that at the level of
  `JobEvent.staff_id`. Byte equality is a different regression surface.
- Testing PDF merging / attachments behaviour exhaustively. One known
  attachment (the square DocketWorks logo PNG) is exercised; the merge code
  (`process_attachments`) is `pypdf` — upstream — and doesn't need coverage
  here.

## Architecture

### One test file, two test methods

- **New file:** `apps/job/tests/test_pdf_goldens.py`
- **New class:** `PDFGoldenTests(BaseTestCase)`
- **Two methods:**
  - `test_delivery_docket_matches_golden()` —
    `generate_delivery_docket(job, staff=self.test_staff)` → compare
    `pdf_buffer.getvalue()` to `fixtures/expected_delivery_docket.pdf`.
  - `test_workshop_pdf_matches_golden()` —
    `create_workshop_pdf(job)` → compare buffer bytes to
    `fixtures/expected_workshop.pdf`.

Both methods share the deterministic job built in `setUp`.

### Shared fixture builder

- **New module:** `apps/job/tests/_pdf_golden_fixtures.py`
- Exports:
  - `FROZEN_NOW` — `datetime(2026, 4, 25, 10, 30, tzinfo=ZoneInfo("Pacific/Auckland"))`.
    NZ DST-aware to match the Wellington company in `company_defaults.json`
    and the `timezone.localtime` calls in the renderer.
  - `build_golden_job(test_staff) -> Job` — creates Client, ClientContact,
    Job, CostSets with CostLines, and the logo JobFile attachment. All DB
    writes happen inside a `freeze_time(FROZEN_NOW)` context so `created_at`,
    `accounting_date`, etc. are pinned.
  - `STARTING_JOB_NUMBER = 1001` — set on `CompanyDefaults` before Job
    creation so the generator issues `1001`. Guards against any other
    test-data that may have created a Job #1 in the same run.

The fixture builder is imported by the test **and** by
`scripts/regen_golden_pdfs.py` so they cannot diverge.

### Deterministic job — specific values

| Field | Value |
|---|---|
| `Client.name` | `ACME Engineering Ltd` |
| `Client.phone` | `+64 4 555 1234` |
| `ClientContact.name` | `Jane Doe` |
| `ClientContact.phone` | `+64 21 555 5678` |
| `Job.name` | `Custom Bracket Fabrication` |
| `Job.description` | `Stainless steel mounting bracket, 200x100x5mm, 4 holes per spec` |
| `Job.notes` | `<p>Use 316 grade. Laser cut then fold. Powder coat matte black.</p>` |
| `Job.delivery_date` | `2026-05-09` |
| `Job.order_number` | `PO-ACME-12345` |
| `Job.pricing_methodology` | `time_materials` |
| `Job.speed_quality_tradeoff` | `balanced` |
| `Job.staff` | `self.test_staff` |
| `Job.job_number` | `1001` (from `STARTING_JOB_NUMBER`) |

**Estimate CostSet CostLines (time):**

| desc | quantity | unit_cost | unit_rev |
|---|---|---|---|
| `Fabrication` | `2.00` | `32.00` | `105.00` |
| `Welding` | `1.50` | `32.00` | `105.00` |

**Actual CostSet CostLines (material):**

| desc | quantity |
|---|---|
| `Stainless steel sheet 3mm` | `2.50` |
| `M6 fasteners` | `12.00` |

**Attachment:**

One `JobFile` referencing the committed square logo at
`mediafiles/app_images/docketworks_logo.png`, with `print_on_jobsheet=True`
and `mime_type="image/png"`. This exercises the `process_attachments` image-
merging path in `create_workshop_pdf`.

## Determinism mechanism

`setUp()` installs three scopes, each with `addCleanup`:

1. **Time:** `self._freezer = freeze_time(FROZEN_NOW); self._freezer.start()`.
   Covers `Job.created_at` (auto_now_add), the renderer's
   `timezone.now()` / `timezone.localtime(...)` calls ("ENTRY DATE",
   "Delivery Date:"), and the delivery-docket filename timestamp.
2. **ReportLab:** `rl_config.invariant = 1`. Suppresses `/CreationDate`,
   `/ModDate`, and the time-seeded `/ID` array in the PDF trailer.
3. **Disk writes:** `override_settings(DROPBOX_WORKFLOW_FOLDER=tmp)` pointing
   at a `tempfile.mkdtemp()` cleaned up in teardown. The delivery-docket
   service writes a physical copy of the PDF to disk; without this override
   it would touch the real workflow folder.

Production code changes: none. All three knobs live only for the duration of
`PDFGoldenTests.setUp` → `tearDown`.

## Committed assets

Already uncommitted under `mediafiles/app_images/`; to be added in this work:

- `mediafiles/app_images/docketworks_logo.png` (square; also the test
  attachment)
- `mediafiles/app_images/docketworks_logo_wide.png` (letterhead banner)

`.gitignore` already carries the `!mediafiles/app_images/` exception
(line 48 and line 192) — no edit needed.

## Golden PDFs

- `apps/job/tests/fixtures/expected_delivery_docket.pdf` — 2 pages (Company
  Copy + Customer Copy) of the deterministic job.
- `apps/job/tests/fixtures/expected_workshop.pdf` — workshop PDF of the same
  job, including the merged logo attachment page.

Both are binary and checked into git. Byte-level diffs show up in review as
"binary files differ"; reviewers open the PDF locally to confirm the visual
change matches the intent.

## Regeneration script

- **New file:** `scripts/regen_golden_pdfs.py`
- Imports `build_golden_job` + the service functions; installs the same
  `freeze_time` + `rl_config.invariant` scopes; calls
  `generate_delivery_docket(...)` and `create_workshop_pdf(...)`; writes the
  byte output to the two golden paths.
- Uses `logging`, not print (per `feedback_scripts_logging.md`). Logs
  `"Wrote <path> (<n> bytes)"` for each file.
- Run manually after a deliberate rendering change: `python
  scripts/regen_golden_pdfs.py`. The test's failing output includes a one-
  line pointer: `"Run scripts/regen_golden_pdfs.py to regenerate if this
  change is intentional."`

## Frontend tests

Connection smokes — the frontend's job is to prove the Vue layer wires to
the already-tested backend, nothing more.

### Delivery docket: `frontend/tests/job/print-delivery-docket.spec.ts`

Already exists. One change: add a content-length sanity assertion so an
"HTTP 200 with empty body" regression cannot pass.

```ts
expect(Number(response.headers()['content-length'] ?? 0)).toBeGreaterThan(1000)
```

### Workshop PDF: `frontend/tests/job/print-workshop-pdf.spec.ts`

**New file.** Symmetric to the delivery docket spec:

1. Navigate to `sharedEditJobUrl`.
2. `page.waitForResponse('**/api/job/jobs/*/workshop-pdf/**')` while
   clicking the Print Job button.
3. Assert status 200, content-type `application/pdf`, content-length > 1000.

Requires adding `data-automation-id="JobView-print-workshop-pdf"` to the
existing Print button at `frontend/src/views/JobView.vue:249-254` (handler
`printJob`, currently has no automation id).

### Opportunistic automation-id sweep

While we're in `JobView.vue`, audit the view's header/toolbar region (roughly
the range containing the Print and Print Delivery Docket buttons) for other
interactive elements without `data-automation-id`. Add ids with the existing
`JobView-<kebab-action>` naming convention. Scope is this file only — not a
whole-app sweep. Concretely: the Print button (this work), and any sibling
buttons in the same action row that lack ids. Found-and-unaddressed ones go
into a follow-up card, not this PR.

## Relationship to existing tests

- `apps/job/tests/test_delivery_docket_service.py` — **keep as-is.** Covers
  JobEvent.staff attribution at the semantic layer. If the staff FK bug
  reappears that test fails with a clear `staff_id` assertion, which is a
  better failure signal than "PDFs differ" from the golden test.
- `apps/job/tests/test_workshop_pdf_service.py` — **keep as-is.** Covers
  page counts, HTML conversion, and a range of semantic behaviours.

The golden tests complement these; they do not subsume them.

## Critical files

**New:**
- `apps/job/tests/test_pdf_goldens.py`
- `apps/job/tests/_pdf_golden_fixtures.py`
- `apps/job/tests/fixtures/expected_delivery_docket.pdf` (binary golden)
- `apps/job/tests/fixtures/expected_workshop.pdf` (binary golden)
- `scripts/regen_golden_pdfs.py`
- `frontend/tests/job/print-workshop-pdf.spec.ts`

**Modify:**
- `frontend/tests/job/print-delivery-docket.spec.ts` (add content-length
  assertion)
- `frontend/src/views/JobView.vue` (add `data-automation-id="JobView-print-workshop-pdf"`
  to the Print button at lines 249-254; plus any sibling action-row buttons
  missing ids — see "Opportunistic automation-id sweep" above)
- `pyproject.toml` (add `freezegun` under `[tool.poetry.group.dev.dependencies]`)
- `poetry.lock` (regenerated by `poetry add --group dev freezegun`)

**Commit (already present in working tree, currently untracked):**
- `mediafiles/app_images/docketworks_logo.png`
- `mediafiles/app_images/docketworks_logo_wide.png`

## Reuses

- `BaseTestCase.test_staff` and `company_defaults` fixture —
  `apps/testing.py`.
- Canvas `invariant` kwarg / `rl_config.invariant` flag — ReportLab 4.4+
  built-in deterministic mode.
- `freezegun.freeze_time` — **must be added** to
  `[tool.poetry.group.dev.dependencies]` in `pyproject.toml`. It is not
  currently a direct docketworks dep (only appears as transitive extras of
  other packages), so `python -c "import freezegun"` fails in the current
  environment. `poetry add --group dev freezegun` lands it cleanly.
- Playwright `authenticatedPage` and `sharedEditJobUrl` fixtures —
  `frontend/tests/fixtures/auth.ts`.
- `autoId` helper — `frontend/tests/fixtures/helpers.ts`.

## Verification

1. `python manage.py test apps.job.tests.test_pdf_goldens -v 2` — both
   methods pass; `pdf_buffer.getvalue()` matches the committed golden
   byte-for-byte.
2. `python manage.py test apps.job.tests.test_delivery_docket_service -v 2`
   — still passes (JobEvent attribution unaffected).
3. `python manage.py test apps.job.tests.test_workshop_pdf_service -v 2` —
   still passes (existing page-count and HTML tests unaffected).
4. `python scripts/regen_golden_pdfs.py` produces byte-identical output to
   what's already committed (tautology if the tests pass, but confirms the
   script isn't drifting from the test path).
5. With the dev server running:
   `npx playwright test frontend/tests/job/print-delivery-docket.spec.ts
   frontend/tests/job/print-workshop-pdf.spec.ts` — both pass (status,
   content-type, content-length).

## Out of scope

- Structural (text-extraction) assertions on the PDFs. If a future golden
  failure is ambiguous to read as a binary diff, we add pypdf text
  extraction then — not pre-emptively.
- PDF attachments beyond the single logo. More complex attachment matrices
  only get added if a merge-path regression actually shows up.
- Frontend byte-identity. Backend owns that contract.
