# Fix Delivery Dockets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a cohesive fix for broken delivery dockets: thread `staff` through the six JobEvent-emission sites broken by migration 0079, commit the DocketWorks logo assets so PDF rendering works without a per-machine setup step, and add byte-identical golden-PDF regression tests for both the workshop PDF (Print Job) and the delivery docket so any future rendering drift fails the build.

**Architecture:** Two test layers — a semantic test proves `JobEvent.staff_id` is populated correctly, and a new golden-file test compares raw PDF bytes to a committed golden. Determinism is test-harness-only (`freezegun.freeze_time` + `reportlab.rl_config.invariant = 1`); production PDFs stay dated with real wall-clock time. A shared fixture-builder module is the single source of truth for the test job — used by both the test and a manual regeneration script.

**Tech Stack:** Django 6 tests via `manage.py test`; Playwright for frontend; ReportLab for PDF rendering; `freezegun` (new dev dep) for time freezing; `pypdf` for PDF reading in existing tests.

**Related specs:**
- [`docs/plans/2026-04-25-delivery-docket-staff-fk.md`](./2026-04-25-delivery-docket-staff-fk.md) — staff-FK root-cause analysis and the prior plan. Most code from that plan is already applied to the working tree (uncommitted); this plan consolidates and commits it.
- [`docs/plans/2026-04-25-pdf-golden-tests-design.md`](./2026-04-25-pdf-golden-tests-design.md) — the golden-tests design spec approved in this brainstorming session.

**Working-tree state at start of implementation** (snapshot):

Already applied, uncommitted:
- `apps/job/services/delivery_docket_service.py` — `generate_delivery_docket(job, staff: Staff)` signature, `staff=staff` on JobEvent.
- `apps/job/views/delivery_docket_view.py` — passes `staff=request.user`.
- `apps/workflow/views/xero/xero_invoice_manager.py` — `staff=self.staff` at both emission sites.
- `apps/workflow/views/xero/xero_quote_manager.py` — `staff=self.staff` at both emission sites.
- `apps/process/services/procedure_service.py` — `generate_jsa(job, staff)` signature, `staff=staff` on JobEvent.
- `apps/process/views/procedure_viewsets.py` — passes `staff=request.user`.
- `apps/workflow/fixtures/company_defaults.json` — `logo` and `logo_wide` point at `app_images/...` paths.
- `.gitignore` — `!mediafiles/app_images/` exception already wired.
- `mediafiles/app_images/docketworks_logo.png` and `docketworks_logo_wide.png` — PNG assets present on disk, not yet `git add`ed.
- `apps/job/tests/test_delivery_docket_service.py` — new semantic test (JobEvent.staff_id assertion).
- `apps/job/tests/test_workshop_pdf_service.py` — old inline logo-upload helper removed (no longer needed now the fixture references the committed PNG).
- `frontend/tests/job/print-delivery-docket.spec.ts` — new Playwright smoke.
- `frontend/src/views/JobView.vue` — `data-automation-id="JobView-print-delivery-docket"` added.
- `docs/restore-prod-to-nonprod.md`, `scripts/restore_checks/check_company_defaults.py` — runbook + check-script updates for the new logo fields.

New work still to do (this plan):
- Add `freezegun` dev dep.
- Build golden-PDF fixture builder and tests.
- Build regen script; produce and commit the two golden PDFs.
- Add workshop-PDF automation-id to `JobView.vue` + new Playwright spec.
- Add content-length sanity assertion to the delivery-docket Playwright spec.
- Drop redundant untracked plan file `please-implement-docs-plans-2026-04-16-s-groovy-peacock.md`.

---

## Phase A — Dependencies

### Task 1: Add freezegun as a dev dependency

**Files:**
- Modify: `pyproject.toml` (add under `[tool.poetry.group.dev.dependencies]`)
- Modify: `poetry.lock` (regenerated)

- [ ] **Step 1: Add the dep via poetry**

Run:
```bash
poetry add --group dev freezegun
```

Expected: poetry adds `freezegun = "^<latest>"` to `[tool.poetry.group.dev.dependencies]` in `pyproject.toml` and regenerates `poetry.lock`.

- [ ] **Step 2: Verify it imports**

Run:
```bash
python -c "from freezegun import freeze_time; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore(deps): add freezegun dev dep for PDF golden tests"
```

---

## Phase B — Land staff-FK fixes and semantic test

The staff-FK code changes are already in the working tree. This phase verifies the existing semantic test passes with them applied, then commits the bundle as one cohesive change.

### Task 2: Verify the semantic test passes against the applied fix

**Files:**
- Run: `apps/job/tests/test_delivery_docket_service.py` (already in working tree, untracked)

- [ ] **Step 1: Run the semantic test**

Run:
```bash
python manage.py test apps.job.tests.test_delivery_docket_service -v 2
```

Expected: 1 test passes (`GenerateDeliveryDocketTests.test_generate_attributes_jobevent_to_calling_staff`). If it fails with `IntegrityError: NOT NULL constraint failed: job_jobevent.staff_id`, the staff-FK fix was not applied correctly — inspect `apps/job/services/delivery_docket_service.py` and check the `staff=staff` kwarg reached line 83 of the `JobEvent.objects.create(...)` call. Do not proceed until green.

### Task 3: Commit staff-FK fixes and semantic test

**Files:**
- Modify (commit): `apps/job/services/delivery_docket_service.py`
- Modify (commit): `apps/job/views/delivery_docket_view.py`
- Modify (commit): `apps/workflow/views/xero/xero_invoice_manager.py`
- Modify (commit): `apps/workflow/views/xero/xero_quote_manager.py`
- Modify (commit): `apps/process/services/procedure_service.py`
- Modify (commit): `apps/process/views/procedure_viewsets.py`
- Create (commit): `apps/job/tests/test_delivery_docket_service.py`

- [ ] **Step 1: Stage the six code changes + the semantic test**

```bash
git add \
  apps/job/services/delivery_docket_service.py \
  apps/job/views/delivery_docket_view.py \
  apps/workflow/views/xero/xero_invoice_manager.py \
  apps/workflow/views/xero/xero_quote_manager.py \
  apps/process/services/procedure_service.py \
  apps/process/views/procedure_viewsets.py \
  apps/job/tests/test_delivery_docket_service.py
```

- [ ] **Step 2: Verify nothing else got staged accidentally**

```bash
git status
```

Expected: only the seven paths above are in `Changes to be committed`. `mediafiles/`, `JobView.vue`, etc. should still be unstaged.

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
fix(job,workflow,process): thread staff FK through all JobEvent emitters

Migration 0079 made JobEvent.staff NOT NULL. Six emission sites were
still passing no staff, raising IntegrityError the moment each flow
ran in prod:

- generate_delivery_docket (user-reported: "Print Delivery Docket" 500s)
- XeroInvoiceManager.invoice_created / invoice_deleted
- XeroQuoteManager.quote_created / quote_deleted
- ProcedureService.generate_jsa

delivery_docket_service and generate_jsa gain a required staff parameter
threaded from their views (request.user). Xero managers already had
self.staff in scope; they just needed to pass it. A new semantic test in
apps/job/tests/test_delivery_docket_service.py asserts JobEvent.staff_id
is populated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Commit DocketWorks logo assets and dev-setup docs

### Task 4: Stage and commit committed-assets changes

**Files:**
- Create (commit): `mediafiles/app_images/docketworks_logo.png`
- Create (commit): `mediafiles/app_images/docketworks_logo_wide.png`
- Modify (commit): `.gitignore`
- Modify (commit): `apps/workflow/fixtures/company_defaults.json`
- Modify (commit): `docs/restore-prod-to-nonprod.md`
- Modify (commit): `scripts/restore_checks/check_company_defaults.py`
- Modify (commit): `apps/job/tests/test_workshop_pdf_service.py` (removes now-redundant inline logo-upload helper)

- [ ] **Step 1: Stage**

```bash
git add \
  mediafiles/app_images/docketworks_logo.png \
  mediafiles/app_images/docketworks_logo_wide.png \
  .gitignore \
  apps/workflow/fixtures/company_defaults.json \
  docs/restore-prod-to-nonprod.md \
  scripts/restore_checks/check_company_defaults.py \
  apps/job/tests/test_workshop_pdf_service.py
```

- [ ] **Step 2: Sanity-check the PNG byte sizes**

```bash
ls -l mediafiles/app_images/*.png
```

Expected: both files present and non-zero (should be around 170 KB and 208 KB).

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(branding): commit DocketWorks logo assets for shipped installs

Ships docketworks_logo.png and docketworks_logo_wide.png under
mediafiles/app_images/ so fresh installs have working letterhead
branding out of the box without a per-machine asset copy step. The
company_defaults fixture now references them at app_images/... (resolved
under MEDIA_ROOT = mediafiles/).

.gitignore gains a targeted exception for mediafiles/app_images/ so the
shipped assets are tracked while user uploads remain ignored. The restore
runbook and check_company_defaults.py script are updated to describe and
verify the new logo_wide field. The test_workshop_pdf_service inline
logo-upload helper is removed — tests now rely on the shipped asset.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Verify the existing workshop PDF test still passes after the helper removal**

Run:
```bash
python manage.py test apps.job.tests.test_workshop_pdf_service -v 2
```

Expected: all tests pass, including `DeliveryDocketPDFTests.test_delivery_docket_is_exactly_two_pages` which now relies on the committed `logo_wide` asset.

---

## Phase D — Golden-PDF fixture builder

### Task 5: Create the shared fixture-builder module

**Files:**
- Create: `apps/job/tests/_pdf_golden_fixtures.py`

- [ ] **Step 1: Write the fixture builder**

```python
"""Deterministic job builder shared by golden-PDF tests and the regen script.

The golden tests compare raw PDF bytes to a committed golden file. Any
drift in the test job fails the byte comparison, so this module is the
single source of truth for every field that influences PDF output.

Importers MUST install the time-freeze and ReportLab-invariant scopes
before calling ``build_golden_job`` — the deterministic job relies on
``freeze_time(FROZEN_NOW)`` being active so ``Job.created_at`` and
``CostLine.accounting_date`` take frozen values.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile

from apps.accounts.models import Staff
from apps.client.models import Client, ClientContact
from apps.job.models import CostLine, Job, JobFile
from apps.workflow.models import CompanyDefaults

FROZEN_NOW = datetime.datetime(
    2026, 4, 25, 10, 30, tzinfo=ZoneInfo("Pacific/Auckland")
)

STARTING_JOB_NUMBER = 1001


def build_golden_job(test_staff: Staff) -> Job:
    """Build the deterministic test job and return it.

    Caller must have ``freezegun.freeze_time(FROZEN_NOW)`` active.
    """
    company = CompanyDefaults.get_solo()
    company.starting_job_number = STARTING_JOB_NUMBER
    company.save()

    client = Client.objects.create(
        name="ACME Engineering Ltd",
        phone="+64 4 555 1234",
        xero_last_modified=FROZEN_NOW,
    )

    contact = ClientContact.objects.create(
        client=client,
        name="Jane Doe",
        phone="+64 21 555 5678",
    )

    job = Job.objects.create(
        client=client,
        contact=contact,
        name="Custom Bracket Fabrication",
        description=(
            "Stainless steel mounting bracket, 200x100x5mm, 4 holes per spec"
        ),
        notes=(
            "<p>Use 316 grade. Laser cut then fold. "
            "Powder coat matte black.</p>"
        ),
        delivery_date=datetime.date(2026, 5, 9),
        order_number="PO-ACME-12345",
        pricing_methodology="time_materials",
        speed_quality_tradeoff="balanced",
        staff=test_staff,
    )

    estimate = job.cost_sets.get(kind="estimate")
    CostLine.objects.create(
        cost_set=estimate,
        kind="time",
        desc="Fabrication",
        quantity=Decimal("2.00"),
        unit_cost=Decimal("32.00"),
        unit_rev=Decimal("105.00"),
        accounting_date=FROZEN_NOW.date(),
    )
    CostLine.objects.create(
        cost_set=estimate,
        kind="time",
        desc="Welding",
        quantity=Decimal("1.50"),
        unit_cost=Decimal("32.00"),
        unit_rev=Decimal("105.00"),
        accounting_date=FROZEN_NOW.date(),
    )

    actual = job.cost_sets.get(kind="actual")
    CostLine.objects.create(
        cost_set=actual,
        kind="material",
        desc="Stainless steel sheet 3mm",
        quantity=Decimal("2.50"),
        unit_cost=Decimal("0"),
        unit_rev=Decimal("0"),
        accounting_date=FROZEN_NOW.date(),
    )
    CostLine.objects.create(
        cost_set=actual,
        kind="material",
        desc="M6 fasteners",
        quantity=Decimal("12.00"),
        unit_cost=Decimal("0"),
        unit_rev=Decimal("0"),
        accounting_date=FROZEN_NOW.date(),
    )

    with open(
        "mediafiles/app_images/docketworks_logo.png", "rb"
    ) as src:
        logo_bytes = src.read()

    attachment = JobFile.objects.create(
        job=job,
        filename="docketworks_logo.png",
        mime_type="image/png",
        print_on_jobsheet=True,
        status="active",
    )
    attachment.file_path.save(
        "docketworks_logo.png",
        ContentFile(logo_bytes),
        save=True,
    )

    return job
```

- [ ] **Step 2: Verify the cost_sets.get calls work**

The plan assumes `Job` post-save creates one `CostSet` for each `kind`
(at least `"estimate"` and `"actual"`) automatically. Confirm by reading
`apps/job/models/job.py:generate_job_number` and surrounding Job.save
behaviour — if auto-creation doesn't happen, replace `.get` with
explicit `CostSet.objects.create(job=job, kind="estimate", rev=1)`.

Run:
```bash
grep -n "cost_sets\|CostSet.*create" apps/job/models/job.py apps/job/services/job_rest_service.py 2>/dev/null | head -20
```

Inspect the output and adjust the fixture builder if needed. If the test
uses `.get()` and no CostSet was auto-created, Task 7 will fail with
`CostSet.DoesNotExist` — fix by switching to `objects.create()` there.

- [ ] **Step 3: Verify the JobFile field name matches**

```bash
grep -nE "class JobFile|file_path|filename" apps/job/models/file.py apps/job/models/__init__.py 2>/dev/null | head -15
```

If the field is named something other than `file_path`, update
`attachment.file_path.save(...)` accordingly. Likewise if `filename` is
populated from the saved file rather than passed as a kwarg.

---

## Phase E — Golden-PDF tests

### Task 6: Write the golden-PDF test

**Files:**
- Create: `apps/job/tests/test_pdf_goldens.py`

- [ ] **Step 1: Write the test**

```python
"""Byte-identical golden tests for the two user-facing PDFs.

When either test fails and the change is intentional, regenerate the
golden via::

    python scripts/regen_golden_pdfs.py

Then inspect the binary diff in git (open the new golden in a PDF viewer
to confirm the visual change matches intent) and commit.
"""

from pathlib import Path

from django.test import override_settings
from freezegun import freeze_time
from reportlab import rl_config

from apps.job.services.delivery_docket_service import generate_delivery_docket
from apps.job.services.workshop_pdf_service import create_workshop_pdf
from apps.job.tests._pdf_golden_fixtures import FROZEN_NOW, build_golden_job
from apps.testing import BaseTestCase

GOLDENS_DIR = Path(__file__).parent / "fixtures"
EXPECTED_DELIVERY_DOCKET = GOLDENS_DIR / "expected_delivery_docket.pdf"
EXPECTED_WORKSHOP = GOLDENS_DIR / "expected_workshop.pdf"

REGEN_HINT = (
    "If this rendering change is intentional, regenerate the golden via "
    "`python scripts/regen_golden_pdfs.py` and commit the updated file."
)


class PDFGoldenTests(BaseTestCase):
    """PDF bytes must match the committed golden exactly."""

    def setUp(self):
        super().setUp()
        self._freezer = freeze_time(FROZEN_NOW)
        self._freezer.start()
        self.addCleanup(self._freezer.stop)

        self._prev_invariant = rl_config.invariant
        rl_config.invariant = 1
        self.addCleanup(
            lambda: setattr(rl_config, "invariant", self._prev_invariant)
        )

        self.job = build_golden_job(self.test_staff)

    def test_delivery_docket_matches_golden(self):
        pdf_buffer, _job_file = generate_delivery_docket(
            self.job, staff=self.test_staff
        )
        actual = pdf_buffer.getvalue()
        expected = EXPECTED_DELIVERY_DOCKET.read_bytes()
        self.assertEqual(actual, expected, msg=REGEN_HINT)

    def test_workshop_pdf_matches_golden(self):
        pdf_buffer = create_workshop_pdf(self.job)
        actual = pdf_buffer.getvalue()
        expected = EXPECTED_WORKSHOP.read_bytes()
        self.assertEqual(actual, expected, msg=REGEN_HINT)
```

- [ ] **Step 2: Run the test to confirm it fails (TDD red)**

The golden files don't exist yet; the test should fail with a
FileNotFoundError on `read_bytes()`.

Run:
```bash
python manage.py test apps.job.tests.test_pdf_goldens -v 2
```

Expected: 2 tests fail with `FileNotFoundError: [Errno 2] No such file
or directory: '.../apps/job/tests/fixtures/expected_delivery_docket.pdf'`
(or equivalent for the workshop golden). If instead you see a failure
from `build_golden_job` or a `CostSet.DoesNotExist`, address that
first — the fixture builder is broken and will block everything
downstream.

---

## Phase F — Regeneration script + produce goldens

### Task 7: Write the regeneration script

**Files:**
- Create: `scripts/regen_golden_pdfs.py`

- [ ] **Step 1: Write the script**

```python
"""Regenerate both committed golden PDFs.

Run manually after a deliberate change to the PDF rendering code::

    python scripts/regen_golden_pdfs.py

The output is compared byte-for-byte by
``apps/job/tests/test_pdf_goldens.py``.
"""

import logging
import os
import sys
from pathlib import Path

import django
from freezegun import freeze_time
from reportlab import rl_config

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
django.setup()

from django.db import transaction  # noqa: E402

from apps.accounts.models import Staff  # noqa: E402
from apps.job.services.delivery_docket_service import (  # noqa: E402
    generate_delivery_docket,
)
from apps.job.services.workshop_pdf_service import create_workshop_pdf  # noqa: E402
from apps.job.tests._pdf_golden_fixtures import (  # noqa: E402
    FROZEN_NOW,
    build_golden_job,
)

GOLDENS_DIR = (
    Path(__file__).resolve().parent.parent
    / "apps"
    / "job"
    / "tests"
    / "fixtures"
)
EXPECTED_DELIVERY_DOCKET = GOLDENS_DIR / "expected_delivery_docket.pdf"
EXPECTED_WORKSHOP = GOLDENS_DIR / "expected_workshop.pdf"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("regen_golden_pdfs")


def main() -> None:
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)

    test_staff, _ = Staff.objects.get_or_create(
        email="golden-regen@example.com",
        defaults={
            "first_name": "Golden",
            "last_name": "Regen",
            "is_workshop_staff": False,
            "is_office_staff": False,
        },
    )

    rl_config.invariant = 1
    try:
        with freeze_time(FROZEN_NOW), transaction.atomic():
            job = build_golden_job(test_staff)

            delivery_bytes = generate_delivery_docket(
                job, staff=test_staff
            )[0].getvalue()
            workshop_bytes = create_workshop_pdf(job).getvalue()

            # Roll back the DB changes — the script is idempotent and
            # must not leave test data behind on the dev DB.
            transaction.set_rollback(True)
    finally:
        rl_config.invariant = 0

    EXPECTED_DELIVERY_DOCKET.write_bytes(delivery_bytes)
    logger.info(
        "Wrote %s (%d bytes)",
        EXPECTED_DELIVERY_DOCKET,
        len(delivery_bytes),
    )

    EXPECTED_WORKSHOP.write_bytes(workshop_bytes)
    logger.info(
        "Wrote %s (%d bytes)",
        EXPECTED_WORKSHOP,
        len(workshop_bytes),
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create the fixtures directory**

```bash
mkdir -p apps/job/tests/fixtures
```

Expected: directory exists. (Already exists per the earlier recon, but
this is idempotent.)

- [ ] **Step 3: Run the script to produce both goldens**

```bash
python scripts/regen_golden_pdfs.py
```

Expected:
```
... INFO Wrote .../apps/job/tests/fixtures/expected_delivery_docket.pdf (<N> bytes)
... INFO Wrote .../apps/job/tests/fixtures/expected_workshop.pdf (<N> bytes)
```

Both byte counts should be non-zero (typically 150-500 KB for the
workshop PDF given the merged logo attachment).

If the script crashes with a fixture-builder issue (e.g.
`CostSet.DoesNotExist`), go back to Task 5 Step 2 and fix the builder —
the test and the script share the same code path.

- [ ] **Step 4: Open both goldens in a PDF viewer**

```bash
xdg-open apps/job/tests/fixtures/expected_delivery_docket.pdf
xdg-open apps/job/tests/fixtures/expected_workshop.pdf
```

Inspect visually:
- Delivery docket: 2 pages, "DELIVERY DOCKET - DC Copy" and "DELIVERY
  DOCKET - Customer Copy" headings, handover section shows `Delivery
  Date: Sat, 25 Apr 2026` and `Delivery Docket Number: 1001`.
- Workshop PDF: letterhead banner, Job 1001 title, time-used table with
  Fabrication 2h / Welding 1h 30m, materials table with Stainless steel
  sheet 3mm / M6 fasteners, logo attachment page appended.

If either PDF looks wrong, fix the fixture builder / rendering code and
re-run the script.

### Task 8: Verify golden tests now pass (TDD green)

- [ ] **Step 1: Run the tests**

```bash
python manage.py test apps.job.tests.test_pdf_goldens -v 2
```

Expected: 2 tests pass.

- [ ] **Step 2: Run them twice more to confirm determinism is stable**

```bash
python manage.py test apps.job.tests.test_pdf_goldens -v 2
python manage.py test apps.job.tests.test_pdf_goldens -v 2
```

Expected: both runs pass. If any run fails with "PDFs differ", the
determinism setup is incomplete — most likely something in ReportLab is
still reading a live clock. Inspect the diff by reading both PDFs with
`pypdf` and comparing `/CreationDate`, `/ModDate`, `/ID`:

```bash
python -c "
from pypdf import PdfReader
for p in ['apps/job/tests/fixtures/expected_delivery_docket.pdf']:
    r = PdfReader(p)
    print(p, r.metadata, r.trailer.get('/ID'))
"
```

If `/CreationDate` or `/ModDate` is present, `rl_config.invariant = 1`
is not taking effect — check the import order in
`test_pdf_goldens.py` (the flag must be set before any `Canvas(...)`
construction, and the renderer reads it per-Canvas).

### Task 9: Commit the fixture builder, tests, regen script, and goldens

**Files:**
- Create (commit): `apps/job/tests/_pdf_golden_fixtures.py`
- Create (commit): `apps/job/tests/test_pdf_goldens.py`
- Create (commit): `apps/job/tests/fixtures/expected_delivery_docket.pdf`
- Create (commit): `apps/job/tests/fixtures/expected_workshop.pdf`
- Create (commit): `scripts/regen_golden_pdfs.py`

- [ ] **Step 1: Stage**

```bash
git add \
  apps/job/tests/_pdf_golden_fixtures.py \
  apps/job/tests/test_pdf_goldens.py \
  apps/job/tests/fixtures/expected_delivery_docket.pdf \
  apps/job/tests/fixtures/expected_workshop.pdf \
  scripts/regen_golden_pdfs.py
```

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
test(job): byte-identical golden PDFs for workshop and delivery docket

A deterministic job fixture, frozen time, and ReportLab's invariant mode
together produce the same PDF bytes every test run. Two committed
golden PDFs under apps/job/tests/fixtures/ are the oracle; the tests
assert raw byte equality.

Determinism is test-harness-only (freezegun + rl_config.invariant in
setUp with addCleanup) — production rendering is unchanged, real PDFs
keep their CreationDate/ModDate metadata.

scripts/regen_golden_pdfs.py is the manual regeneration helper: it
imports the same fixture builder the tests use so the two paths cannot
drift. Invoke after any deliberate rendering change, inspect the PDF
diff, commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase G — Frontend tests and automation-ids

### Task 10: Add workshop-PDF automation-id to JobView.vue

**Files:**
- Modify: `frontend/src/views/JobView.vue:249-254`

- [ ] **Step 1: Add the data-automation-id**

Before:
```vue
            <button
              class="inline-flex items-center justify-center h-9 px-3 rounded-md bg-gray-100 text-gray-700 border border-gray-300 text-sm font-medium hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500"
              @click="printJob"
            >
              <Printer class="w-4 h-4 mr-1" /> Print
            </button>
```

After:
```vue
            <button
              data-automation-id="JobView-print-workshop-pdf"
              class="inline-flex items-center justify-center h-9 px-3 rounded-md bg-gray-100 text-gray-700 border border-gray-300 text-sm font-medium hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500"
              @click="printJob"
            >
              <Printer class="w-4 h-4 mr-1" /> Print
            </button>
```

- [ ] **Step 2: Audit sibling action-row buttons for other missing IDs**

```bash
grep -n "<button" frontend/src/views/JobView.vue | head -20
```

For each `<button>` in the header action row (roughly lines 240-265),
check whether it already has `data-automation-id`. Add one using the
`JobView-<kebab-action>` convention if missing. Scope is this
header block only — don't sweep the whole file.

If there are no other unaided buttons in the header range, no change
needed beyond the one above.

### Task 11: Add content-length assertion to delivery-docket Playwright spec

**Files:**
- Modify: `frontend/tests/job/print-delivery-docket.spec.ts`

- [ ] **Step 1: Add the assertion**

After the existing `expect(response.headers()['content-type']).toContain('application/pdf')` line, add:

```ts
    expect(Number(response.headers()['content-length'] ?? 0)).toBeGreaterThan(1000)
```

The final test body should end:

```ts
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('application/pdf')
    expect(Number(response.headers()['content-length'] ?? 0)).toBeGreaterThan(1000)
  })
})
```

### Task 12: Create the workshop-PDF Playwright spec

**Files:**
- Create: `frontend/tests/job/print-workshop-pdf.spec.ts`

- [ ] **Step 1: Write the spec**

```ts
import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return match[1]
}

test.describe('print workshop pdf', () => {
  test.setTimeout(60000)

  test('GET /workshop-pdf/ returns a PDF', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    const printButton = autoId(page, 'JobView-print-workshop-pdf')
    await expect(printButton).toBeVisible({ timeout: 10000 })

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/job/jobs/${jobId}/workshop-pdf/`) &&
        response.request().method() === 'GET',
      { timeout: 30000 },
    )

    await printButton.click()
    const response = await responsePromise

    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('application/pdf')
    expect(Number(response.headers()['content-length'] ?? 0)).toBeGreaterThan(1000)
  })
})
```

- [ ] **Step 2: Verify the actual workshop-PDF URL shape**

```bash
grep -rn "workshop-pdf\|workshop_pdf\|WorkshopPDF\|WorkshopPdf" apps/job/urls.py frontend/src/services/ 2>/dev/null | head -10
```

Confirm the URL is `/api/job/jobs/{id}/workshop-pdf/` (trailing slash).
If the actual URL pattern differs, adjust the `waitForResponse` matcher
accordingly.

- [ ] **Step 3: Run both Playwright specs**

With dev server and Playwright set up, run:
```bash
cd frontend && npx playwright test \
  tests/job/print-delivery-docket.spec.ts \
  tests/job/print-workshop-pdf.spec.ts
```

Expected: both tests pass.

If the workshop spec fails because `JobView-print-workshop-pdf` is not
found, confirm Task 10 Step 1 was saved. If it fails on content-type,
the API route exists but returns something other than a PDF — inspect
the backend.

### Task 13: Commit the frontend changes

**Files:**
- Modify (commit): `frontend/src/views/JobView.vue`
- Modify (commit): `frontend/tests/job/print-delivery-docket.spec.ts`
- Create (commit): `frontend/tests/job/print-workshop-pdf.spec.ts`

- [ ] **Step 1: Stage**

```bash
git add \
  frontend/src/views/JobView.vue \
  frontend/tests/job/print-delivery-docket.spec.ts \
  frontend/tests/job/print-workshop-pdf.spec.ts
```

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
test(frontend): print-job and print-delivery-docket connection smokes

Adds a sibling Playwright spec for the Print Job (workshop PDF) button
symmetric to the existing delivery-docket spec: click the button, wait
for the PDF response, assert status + content-type + a minimum
content-length so an "HTTP 200 with empty body" regression cannot pass
silently.

The delivery-docket spec gains the same content-length assertion.
JobView.vue gains data-automation-id="JobView-print-workshop-pdf" on
the workshop print button.

Both specs are connection smokes — the backend golden tests own
byte-identical PDF coverage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase H — Clean up stale plan file

### Task 14: Remove the previous session's malformed plan filename

**Files:**
- Delete: `docs/plans/please-implement-docs-plans-2026-04-16-s-groovy-peacock.md`

The file is an artifact of the prior session's harness misnaming — the
same execution-plan content it contains is already covered by the
brainstorming output and this implementation plan, and its filename
violates `feedback_plan_naming.md`.

- [ ] **Step 1: Confirm the file is redundant**

```bash
diff docs/plans/please-implement-docs-plans-2026-04-16-s-groovy-peacock.md \
     docs/plans/2026-04-25-fix-delivery-dockets-implementation.md
```

Expect substantial differences (it's a different plan). Then:

```bash
head -5 docs/plans/please-implement-docs-plans-2026-04-16-s-groovy-peacock.md
```

Confirm it's the sales-pipeline-report execution plan referenced
earlier in the session (unrelated to this work).

- [ ] **Step 2: Decide**

If the file genuinely captures in-progress sales-pipeline-report work
that hasn't been committed elsewhere, rename it to
`docs/plans/2026-04-16-sales-pipeline-report-execution.md` and
commit in a separate PR. Otherwise delete.

- [ ] **Step 3: If deleting, remove it**

```bash
git rm docs/plans/please-implement-docs-plans-2026-04-16-s-groovy-peacock.md
```

Or if the file is still untracked (not yet in git), just:

```bash
rm docs/plans/please-implement-docs-plans-2026-04-16-s-groovy-peacock.md
```

- [ ] **Step 4: Commit (if deleted via git rm)**

```bash
git commit -m "chore(docs): drop misnamed plan file from prior session"
```

Skip this if the file was untracked and merely rm'd — nothing to commit.

---

## Phase I — Final verification and PR

### Task 15: Run the full backend test suite

- [ ] **Step 1: Run everything**

```bash
python manage.py test apps -v 1
```

Expected: all tests pass. If failures appear in files unrelated to this
work, leave them for the user to triage — do not touch them.

- [ ] **Step 2: Re-run the golden tests alone three times**

```bash
for i in 1 2 3; do \
  python manage.py test apps.job.tests.test_pdf_goldens -v 2 || break; \
done
```

Expected: 3 passes back-to-back. Any flake means determinism is not yet
airtight.

### Task 16: Open the PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/delivery-dockets-broke
```

- [ ] **Step 2: Create the PR**

```bash
gh pr create --title "fix(job): repair broken delivery dockets + byte-identical PDF golden tests" --body "$(cat <<'EOF'
## Summary
- Thread `staff` through the six JobEvent emitters that broke under
  migration 0079's NOT NULL constraint (delivery docket, Xero
  invoice/quote create+delete, JSA generate).
- Commit DocketWorks logo assets under `mediafiles/app_images/` so
  PDF rendering works on fresh installs without a per-machine copy step.
- Add byte-identical golden-PDF tests for both the workshop PDF
  (Print Job) and the delivery docket, using `freezegun` + ReportLab's
  `invariant` mode (test-harness-only; production output unchanged).
- Add Playwright smoke tests for both print buttons.

See [`docs/plans/2026-04-25-fix-delivery-dockets-implementation.md`](../blob/fix/delivery-dockets-broke/docs/plans/2026-04-25-fix-delivery-dockets-implementation.md) for the implementation plan and its two source specs.

## Test plan
- [ ] `python manage.py test apps.job.tests.test_delivery_docket_service apps.job.tests.test_pdf_goldens apps.job.tests.test_workshop_pdf_service -v 2` green
- [ ] `python manage.py test apps` green (no regressions)
- [ ] `cd frontend && npx playwright test tests/job/print-delivery-docket.spec.ts tests/job/print-workshop-pdf.spec.ts` green
- [ ] Manual: click "Print" and "Print Delivery Docket" on a real job in dev — PDFs open in a new tab, no 500 errors.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

---

## Self-review notes

- **Spec coverage:** Every section of the golden-tests spec maps to a
  task above: architecture → Tasks 5-8, determinism mechanism → Task 6
  setUp, file layout → Tasks 5/6/7/9, regen script → Task 7, frontend →
  Tasks 10-13, relationship to existing tests → unchanged.
- **Staff-FK plan coverage:** Tasks 3 and 4 commit the six staff-FK
  fixes and the dev-setup bundle already present in the working tree;
  the semantic test from Phase B proves the fix.
- **No placeholders:** every step has explicit code, exact commands, and
  expected output. The two "verify by inspection" steps (Task 5 Step 2
  about CostSet autocreation, Task 12 Step 2 about URL shape) have
  explicit grep commands and adjustment instructions — not vague
  "figure it out" handoffs.
- **Type consistency:** `FROZEN_NOW` and `build_golden_job(test_staff)`
  used identically in Tasks 5, 6, and 7. `EXPECTED_DELIVERY_DOCKET` /
  `EXPECTED_WORKSHOP` paths match between the test and the regen
  script.
- **Risk item:** Task 5 makes two assumptions — that `Job.save` auto-
  creates an `estimate` and an `actual` CostSet (so `.get(kind=...)`
  resolves), and that `JobFile` has a `file_path` FileField. Both are
  confirmed via grep steps in Task 5; the plan adjusts in place if
  either assumption turns out false. If they do fail, they fail at
  Task 6 Step 2 (the first time the fixture runs), which is cheap to
  catch.
