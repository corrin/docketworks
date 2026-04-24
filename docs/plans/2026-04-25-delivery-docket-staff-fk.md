# Delivery docket print: missing staff FK on JobEvent + dev logo setup

> **Filename note:** The plan-mode harness pre-assigned `we-have-a-bug-jolly-codd.md`,
> which violates the project's `YYYY-MM-DD-description.md` convention
> (`feedback_plan_naming.md`). After exiting plan mode, rename to
> `2026-04-25-delivery-docket-staff-fk.md`.

## Context

Migration `apps/job/migrations/0079_alter_jobevent_staff_not_null.py` (applied
2026-04-21) made `JobEvent.staff` `NOT NULL`. The previous JobEvent-staff
initiative (`docs/plans/2026-04-21-jobevent-staff-required.md`) patched 11
callsites but missed every business-action emitter. Six event-creation sites
still pass no `staff` and now raise `IntegrityError` the moment the flow runs
in prod:

| File | Line | event_type |
| --- | --- | --- |
| `apps/job/services/delivery_docket_service.py` | 78 | `delivery_docket_generated` |
| `apps/process/services/procedure_service.py` | 61 | `jsa_generated` |
| `apps/workflow/views/xero/xero_invoice_manager.py` | 250 | `invoice_created` |
| `apps/workflow/views/xero/xero_invoice_manager.py` | 319 | `invoice_deleted` |
| `apps/workflow/views/xero/xero_quote_manager.py` | 206 | `quote_created` |
| `apps/workflow/views/xero/xero_quote_manager.py` | 280 | `quote_deleted` |

The user-visible report is the delivery docket print — that's the path TDD
will cover end-to-end. The other five share root cause and call pattern
(`self.staff` already exists on the Xero managers' `__init__`, and JSA gen
needs a parameter threaded through), so they're bundled into the same PR.

In dev the delivery docket bug is currently masked: `CompanyDefaults.logo_wide`
is empty, so PDF generation raises `ValueError("No wide logo uploaded in
Company Defaults")` in `apps/job/services/workshop_pdf_service.py:529` *before*
the JobEvent row is touched. Fixing the dev setup is what exposes the real
bug locally.

## Three tasks

### Task 1 — TDD: failing tests (backend + Playwright)

**Backend** (`apps/job/tests/test_delivery_docket_service.py`, new):

- Inherit `BaseTestCase` from `apps/testing.py:31` — provides
  `self.test_staff` and loads the `company_defaults` fixture.
- `setUp()` mirrors `DeliveryDocketPDFTests.setUp()` in
  `apps/job/tests/test_workshop_pdf_service.py:333-355`: upload a tiny PNG
  to `CompanyDefaults.logo_wide` so PDF generation can complete; create a
  `Client` and a `Job` with `staff=self.test_staff` and a `job_number`.
- One assertion test:
  `generate_delivery_docket(job, staff=self.test_staff)` returns successfully,
  a `JobEvent` of type `delivery_docket_generated` exists with
  `staff_id == self.test_staff.id` and `detail["filename"]` set, and a
  `JobFile` row was created.
- This test **fails today** because (a) the function signature does not
  accept `staff`, and (b) `JobEvent.objects.create(...)` then raises
  `IntegrityError` on the `staff_id` NOT NULL column.

**Playwright** (`frontend/tests/job/print-delivery-docket.spec.ts`, new):

- Use the existing `authenticatedPage` fixture
  (`frontend/tests/fixtures/auth.ts:14-46`) and the worker-scoped
  `sharedEditJobUrl` fixture (already used by
  `frontend/tests/job/edit-job-settings.spec.ts`) so we don't recreate jobs.
- Add `data-automation-id="JobView-print-delivery-docket"` to the button at
  `frontend/src/views/JobView.vue:255-260` (currently has none).
- Test body:
  1. Navigate to `sharedEditJobUrl`.
  2. Use `page.waitForResponse('**/api/job/jobs/*/delivery-docket/')` while
     clicking the button (popup-blocked `window.open` doesn't matter — we
     only care that the backend returned a PDF, not that the browser opened
     it).
  3. Assert response status is 200 and content-type is `application/pdf`.
- No pre-flight wrapper around the missing-logo case — if Task 2 hasn't
  been applied the request returns 500 and the assertion blows up; that's
  the right failure mode (fail early, no friendly translations).
- Today this test fails: the response is HTTP 500 due to the staff FK bug.

### Task 2 — Dev setup: commit DocketWorks logo PNGs + extend existing runbook step

Per user direction: no new management command — extend the existing
`loaddata company_defaults` step.

- **Commit two PNG assets to the repo** (user-supplied files):
  - `apps/workflow/fixtures/app_images/docketworks_logo.png` — square logo
  - `apps/workflow/fixtures/app_images/docketworks_logo_wide.png` — wide banner
- **Update `apps/workflow/fixtures/company_defaults.json`** to set
  `logo` and `logo_wide` to the relative `MEDIA_ROOT` paths
  (`app_images/docketworks_logo.png`,
  `app_images/docketworks_logo_wide.png`). Note: the model field's
  `upload_to="company_logos/"` (`apps/workflow/models/company_defaults.py:227-232`)
  is unchanged — that controls where future *user-uploaded* logos in admin
  go; ImageField just stores whatever path string is in the DB, so a
  fixture pointing at `app_images/...` for the shipped DocketWorks branding
  works alongside a `company_logos/...` upload path for real instances.
- **Wire into existing setup paths** — single `cp` line, no Python:
  - `docs/restore-prod-to-nonprod.md` Step 6, immediately before the
    `loaddata` line:
    ```bash
    mkdir -p "$MEDIA_ROOT/app_images"
    cp apps/workflow/fixtures/app_images/*.png "$MEDIA_ROOT/app_images/"
    ```
    Update the Step 6 narrative to say "replaces real company name *and
    logos* with demo values".
  - `scripts/server/instance.sh` — add the same two-line block right
    before the existing `dw-run.sh ... loaddata company_defaults.json`
    invocation (find via the `loaddata apps/workflow/fixtures/ai_providers.json`
    pattern at `scripts/server/instance.sh:392`; company_defaults loaddata
    happens via the runbook, not instance.sh — so for instance.sh the
    file copy happens once during instance creation, before any restore).
  - Extend `scripts/restore_checks/check_company_defaults.py` to also
    print/assert `company.logo_wide` is non-empty (one extra line,
    matching the existing print-and-return style).

The PDF code at `workshop_pdf_service.py:518-532` still raises if
`logo_wide` is missing — no fallback added, consistent with
`feedback_no_fallbacks.md`.

### Task 3 — Real fix: thread `staff` through all six event-emission sites

**Delivery docket (the user-reported path, covered by Task 1 tests):**
- `apps/job/services/delivery_docket_service.py:18` — change signature to
  `generate_delivery_docket(job: Job, staff: Staff) -> tuple[BytesIO, JobFile]`.
  Update the docstring; pass `staff=staff` in the `JobEvent.objects.create(...)`
  call at line 78. Mirror the existing pattern in
  `apps/job/services/job_rest_service.py:322-334`.
- `apps/job/views/delivery_docket_view.py:47` — pass `request.user` through:
  `pdf_buffer, job_file = generate_delivery_docket(job, staff=request.user)`.
  `IsOfficeStaff` already guarantees an authenticated office Staff.

**Xero managers (4 sites, `self.staff` already in scope per `__init__`):**
- `apps/workflow/views/xero/xero_invoice_manager.py:250` (`invoice_created`)
  — add `staff=self.staff,`.
- `apps/workflow/views/xero/xero_invoice_manager.py:319` (`invoice_deleted`)
  — add `staff=self.staff,`.
- `apps/workflow/views/xero/xero_quote_manager.py:206` (`quote_created`) —
  add `staff=self.staff,`.
- `apps/workflow/views/xero/xero_quote_manager.py:280` (`quote_deleted`) —
  add `staff=self.staff,`.

**JSA generation (1 site, no staff in scope yet):**
- `apps/process/services/procedure_service.py` — `generate_jsa()` currently
  has no staff. Thread a `staff: Staff` parameter through `generate_jsa()`
  and pass `staff=staff` at line 61. Update its single caller (find via
  `grep -rn "generate_jsa" apps/`) to pass `request.user` if user-initiated,
  or `Staff.get_automation_user()` if scheduled — established pattern from
  `docs/plans/2026-04-21-jobevent-staff-required.md`.

All six fail loudly if `staff` is missing — consistent with
`feedback_no_fallbacks.md`.

## Critical files

**Modify:**
- `apps/job/services/delivery_docket_service.py`
- `apps/job/views/delivery_docket_view.py`
- `apps/workflow/views/xero/xero_invoice_manager.py`
- `apps/workflow/views/xero/xero_quote_manager.py`
- `apps/process/services/procedure_service.py` + its caller
- `apps/workflow/fixtures/company_defaults.json` (add `logo`, `logo_wide` paths)
- `frontend/src/views/JobView.vue` (add `data-automation-id`)
- `docs/restore-prod-to-nonprod.md` (Step 6: add `cp` block)
- `scripts/server/instance.sh` (add the same `cp` block before company-defaults loaddata)
- `scripts/restore_checks/check_company_defaults.py` (assert `logo_wide`)

**Create:**
- `apps/job/tests/test_delivery_docket_service.py`
- `frontend/tests/job/print-delivery-docket.spec.ts`
- `apps/workflow/fixtures/app_images/docketworks_logo.png` (binary, user-supplied)
- `apps/workflow/fixtures/app_images/docketworks_logo_wide.png` (binary, user-supplied)

## Reuses

- `BaseTestCase.test_staff` and `company_defaults` fixture — `apps/testing.py:31-50`
- `_create_test_image()` and `setUp()` logo upload — `apps/job/tests/test_workshop_pdf_service.py:321-344`
- `authenticatedPage` and `sharedEditJobUrl` fixtures — `frontend/tests/fixtures/auth.ts`
- Correct staff-passing pattern — `apps/job/services/job_rest_service.py:322-334`
- `Staff.get_automation_user()` for scheduled JSA generation — `apps/accounts/models.py`

## Verification

1. **Reproduce baseline (red)**
   - On a clean dev DB after restore-prod-to-nonprod (now including the
     `cp` of the DocketWorks PNGs into `MEDIA_ROOT/app_images/`), the
     logo failure is out of the way.
   - `pytest apps/job/tests/test_delivery_docket_service.py` — **fails** with
     `IntegrityError: NOT NULL constraint failed: job_jobevent.staff_id`.
   - With dev server running:
     `npx playwright test frontend/tests/job/print-delivery-docket.spec.ts`
     — **fails** on the 500 response assertion.

2. **Apply Task 3 fix** (all six sites in one commit; the four Xero ones and
   the JSA one don't have failing tests yet, so verify by code review +
   manual smoke).

3. **Confirm green**
   - `pytest apps/job/tests/test_delivery_docket_service.py` — passes; the
     created `JobEvent` has `staff_id == self.test_staff.id`.
   - `pytest apps/job/tests/test_workshop_pdf_service.py` — still passes
     (existing 2-pages test unaffected).
   - `pytest apps/` — full suite green.
   - `npx playwright test frontend/tests/job/print-delivery-docket.spec.ts`
     — passes.

4. **Manual smoke (dev server, after seeding the new logos)**
   - Open a job in the UI, click "Print Delivery Docket". PDF opens in a new
     tab (the DocketWorks banner shows in the letterhead). No toast error.
   - In the DB:
     `SELECT staff_id, event_type, detail FROM job_jobevent WHERE event_type='delivery_docket_generated' ORDER BY timestamp DESC LIMIT 1;`
     — `staff_id` is the logged-in user's id, not NULL.
   - For the Xero/JSA paths, exercise once each in dev (create a Xero quote,
     delete it; create an invoice, delete it; generate a JSA) and confirm
     each emits its `JobEvent` with the expected `staff_id`.

5. **Restore-prod-to-nonprod end-to-end**
   - Re-run the runbook from a fresh prod backup. Step 6 now `cp`s the two
     PNGs into `MEDIA_ROOT/app_images/` before `loaddata`, and the fixture
     references those paths. `check_company_defaults.py` confirms
     `logo_wide` is non-empty.
