"""Deterministic job builder shared by golden-PDF tests and the regen script.

The golden tests compare raw PDF bytes to a committed golden file. Any drift in the test job
fails the byte comparison, so this module is the single source of truth for
every field that influences PDF output.

PDF-visible CompanyDefaults values are seeded here so the builder remains the
single source of truth. The values MUST NOT change — they are
baked into the committed golden bytes.

Callers MUST install the time-freeze and ReportLab-invariant scopes AND
point ``settings.DROPBOX_WORKFLOW_FOLDER`` at a writable directory before
calling ``build_golden_job`` — the fixture copies the logo PNG into the
workflow folder because ``JobFile.file_path`` is a plain ``CharField``
resolved against that root by the workshop PDF's attachment rendering.
"""

from __future__ import annotations

import datetime
import shutil
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.apps import apps as django_apps
from django.conf import settings
from django.db.models import Model

from apps.accounts.models import Staff
from apps.company.models import Company, Person
from apps.core.models import CompanyDefaults
from apps.crm.models import PhoneEndpoint
from apps.job.models import CostLine, Job, JobEvent, JobFile, LabourSubtype

FROZEN_NOW = datetime.datetime(2026, 4, 25, 10, 30, tzinfo=ZoneInfo("Pacific/Auckland"))

# Sits above any realistic dev/prod job number so
# ``Job.generate_job_number()``'s max(starting, highest+1) always resolves
# to STARTING_JOB_NUMBER in both the empty-test-DB and the loaded-dev-DB
# cases. Keeping the two paths byte-identical is the whole point of the
# golden test.
STARTING_JOB_NUMBER = 9999999

LOGO_ATTACHMENT_SOURCE = (
    Path(__file__).resolve().parents[3] / "mediafiles" / "app_images" / "docketworks_logo.png"
)

# Stable absolute path shared by the tests and the regen script.
# ReportLab derives its embedded-image resource name from the file path,
# so a randomised tmp dir would make the workshop PDF's internal image
# reference differ between the regen environment and the test
# environment, breaking byte-identity.
GOLDEN_WORKFLOW_FOLDER = "/tmp/dw-pdf-golden-workflow"  # noqa: S108 -- deliberate fixed path (see above)


def _seed_company_defaults() -> None:
    """Seed CompanyDefaults with stable PDF-visible fixture values."""
    shop_company, _ = Company.objects.get_or_create(
        name="Demo Company Shop",
        defaults={"xero_last_modified": FROZEN_NOW},
    )
    CompanyDefaults.objects.update_or_create(
        id=1,
        defaults={
            "company_name": "Demo Company",
            "company_acronym": "DC",
            "address_line1": "1 Molesworth Street",
            "address_line2": None,
            "city": "Wellington",
            "post_code": "6011",
            "company_email": "info@democompany.example.com",
            "logo": "app_images/docketworks_logo.png",
            "logo_wide": "app_images/docketworks_logo_wide.png",
            "starting_job_number": STARTING_JOB_NUMBER,
            "shop_company": shop_company,
        },
    )


def _ordinary_time_pay_item() -> Model:
    """Fetch/create the Ordinary Time pay item (dynamic model: layer contract)."""
    xero_pay_item_model = django_apps.get_model("xero", "XeroPayItem")
    pay_item, _created = xero_pay_item_model._default_manager.get_or_create(
        name="Ordinary Time",
        uses_leave_api=False,
        defaults={"multiplier": Decimal("1.00")},
    )
    if not isinstance(pay_item, Model):
        raise TypeError("XeroPayItem manager returned a non-model instance")
    return pay_item


def build_golden_job(test_staff: Staff) -> Job:
    """Build the deterministic test job and return it.

    Caller must have ``freezegun.freeze_time(FROZEN_NOW)`` active and
    ``settings.DROPBOX_WORKFLOW_FOLDER`` pointing at a writable dir.
    """
    if not settings.DROPBOX_WORKFLOW_FOLDER:
        raise RuntimeError(
            "build_golden_job requires settings.DROPBOX_WORKFLOW_FOLDER "
            "to point at a writable directory (use override_settings in "
            "tests or set it directly in the regen script)."
        )

    test_staff.first_name = "Golden"
    test_staff.last_name = "Worker"
    test_staff.save(update_fields=["first_name", "last_name"])

    _seed_company_defaults()

    # The letterhead prints the shop's main-line number
    # (workshop_pdf_service._primary_company_endpoint_number). Create it here
    # so PDF output stays byte-identical regardless of which seed fixtures a
    # caller happens to load — this builder is the single source of truth for
    # every field that influences the rendered PDF.
    PhoneEndpoint.objects.create(
        number="+6496365131",
        label="Main line",
        endpoint_type=PhoneEndpoint.EndpointType.MAIN_LINE,
    )

    company = Company.objects.create(
        name="ACME Engineering Ltd",
        xero_last_modified=FROZEN_NOW,
    )

    person = Person.objects.create(name="Jane Doe")

    # Job.save() resolves the default Ordinary Time pay item; seed it first.
    pay_item = _ordinary_time_pay_item()

    job = Job(
        company=company,
        person=person,
        name="Custom Bracket Fabrication",
        description=("Stainless steel mounting bracket, 200x100x5mm, 4 holes per spec"),
        notes=("<p>Use 316 grade. Laser cut then fold. Powder coat matte black.</p>"),
        delivery_date=datetime.date(2026, 5, 9),
        order_number="PO-ACME-12345",
        pricing_methodology="time_materials",
        speed_quality_tradeoff="balanced",
    )
    job.save(staff=test_staff)
    JobEvent.objects.create(
        job=job,
        staff=test_staff,
        event_type="status_changed",
        timestamp=FROZEN_NOW - datetime.timedelta(days=4),
        delta_after={"status": "approved"},
    )

    estimate = job.cost_sets.get(kind="estimate")
    for subtype_name, desc, quantity in [
        ("Workshop", "Fabrication and welding", Decimal("3.50")),
        ("Admin", "Project administration", Decimal("0.75")),
        ("Quoting", "Quote review", Decimal("0.50")),
        ("Onsite", "Site measure", Decimal("1.25")),
        ("Supervision", "Workshop supervision", Decimal("0.50")),
    ]:
        CostLine.objects.create(
            cost_set=estimate,
            kind="time",
            labour_subtype=LabourSubtype.objects.get(name=subtype_name),
            desc=desc,
            quantity=quantity,
            unit_cost=Decimal("32.00"),
            unit_rev=Decimal("105.00"),
            accounting_date=FROZEN_NOW.date(),
        )

    actual = job.cost_sets.get(kind="actual")
    for subtype_name, desc, quantity in [
        ("Workshop", "Workshop actual", Decimal("1.25")),
        ("Admin", "Admin actual", Decimal("0.25")),
        ("Onsite", "Onsite actual", Decimal("0.50")),
    ]:
        CostLine.objects.create(
            cost_set=actual,
            kind="time",
            labour_subtype=LabourSubtype.objects.get(name=subtype_name),
            desc=desc,
            quantity=quantity,
            unit_cost=Decimal("32.00"),
            unit_rev=Decimal("105.00"),
            accounting_date=FROZEN_NOW.date(),
            staff=test_staff,
            xero_pay_item_id=pay_item.pk,
            meta={
                "staff_id": str(test_staff.id),
                "date": FROZEN_NOW.date().isoformat(),
                "is_billable": True,
                "wage_rate_multiplier": 1.0,
            },
        )

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

    job_folder = Path(settings.DROPBOX_WORKFLOW_FOLDER) / f"Job-{job.job_number}"
    job_folder.mkdir(parents=True, exist_ok=True)
    attachment_dest = job_folder / "docketworks_logo.png"
    shutil.copyfile(LOGO_ATTACHMENT_SOURCE, attachment_dest)
    attachment_dest.chmod(0o600)

    JobFile.objects.create(
        job=job,
        filename="docketworks_logo.png",
        file_path=f"Job-{job.job_number}/docketworks_logo.png",
        mime_type="image/png",
        print_on_jobsheet=True,
        status="active",
    )

    return job
