"""Job/accounting factories for company-domain tests (merge, company-jobs).

Minimal factories creating only what each model truly requires, ported from
the factory helpers at the top of v1 ``test_company_merge_service.py``.
"""

import uuid
from datetime import date
from decimal import Decimal

from django.apps import apps as django_apps
from django.db.models import Model
from django.utils import timezone

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.core.models import CompanyDefaults
from apps.crm.models import PhoneCallRecord
from apps.job.models import CostSet, Job
from apps.purchasing.models import PurchaseOrder
from apps.quoting.models import ScrapeJob, SupplierPriceList, SupplierProduct


def _xero_pay_item_model() -> type[Model]:
    """Resolve XeroPayItem dynamically: the layer contract forbids a static
    ``apps.company -> apps.xero`` import, but Job rows require the FK (the
    same inversion Job.save() carries under pyproject's ignore entry)."""
    return django_apps.get_model("xero", "XeroPayItem")


def seed_job_prereqs() -> "Model":
    """Create the rows a Job row requires; return the Ordinary Time pay item."""
    if not CompanyDefaults.objects.filter(id=1).exists():
        shop_company = Company.objects.create(
            name="Shop Company (internal)", xero_last_modified=timezone.now()
        )
        CompanyDefaults.objects.create(id=1, company_name="Test Co", shop_company=shop_company)
    pay_item, _created = _xero_pay_item_model()._default_manager.get_or_create(
        name="Ordinary Time",
        uses_leave_api=False,
        defaults={"multiplier": Decimal("1.00")},
    )
    return pay_item


_next_job_number = {"n": 90000}


def make_job(company: Company, staff: Staff, *, name: str = "Test Job") -> Job:
    """Insert a Job row directly via bulk_create, bypassing Job.save().

    Phase gap tripwire: Job.save() currently ends in
    ``NotImplementedError("Phase 3: apps.job.tasks.request_job_summary_pdf_refresh")``
    (apps/job/tasks is not ported yet), so jobs cannot be saved normally.
    Replace this with a plain ``job.save(staff=...)`` factory when the job
    app's task port lands.
    """
    pay_item = seed_job_prereqs()
    _next_job_number["n"] += 1
    job_id = uuid.uuid4()
    summary = {"cost": 0.0, "rev": 0.0, "hours": 0.0}
    estimate = CostSet.objects.create(job_id=job_id, kind="estimate", rev=1, summary=summary)
    quote = CostSet.objects.create(job_id=job_id, kind="quote", rev=1, summary=summary)
    actual = CostSet.objects.create(job_id=job_id, kind="actual", rev=1, summary=summary)
    job = Job(
        id=job_id,
        name=name,
        job_number=_next_job_number["n"],
        company=company,
        created_by=staff,
        default_xero_pay_item_id=pay_item.pk,
        latest_estimate=estimate,
        latest_quote=quote,
        latest_actual=actual,
        priority=1000.0,
    )
    Job.objects.bulk_create([job])
    return Job.objects.get(id=job_id)


def make_link(company: Company, name: str) -> CompanyPersonLink:
    person = Person.objects.create(name=name)
    return CompanyPersonLink.objects.create(company=company, person=person)


def _invoice_fields(company: Company) -> dict[str, object]:
    return {
        "xero_id": uuid.uuid4(),
        "number": f"TEST-{uuid.uuid4().hex[:8]}",
        "company": company,
        "date": timezone.localdate(),
        "total_excl_tax": Decimal("100.00"),
        "tax": Decimal("15.00"),
        "total_incl_tax": Decimal("115.00"),
        "amount_due": Decimal("115.00"),
        "xero_last_modified": timezone.now(),
        "raw_json": {},
    }


def make_invoice(company: Company, *, invoice_date: date | None = None) -> Invoice:
    fields = _invoice_fields(company)
    if invoice_date is not None:
        fields["date"] = invoice_date
    return Invoice.objects.create(**fields)


def make_bill(company: Company) -> Bill:
    return Bill.objects.create(**_invoice_fields(company))


def make_credit_note(company: Company) -> CreditNote:
    return CreditNote.objects.create(**_invoice_fields(company))


def make_quote(company: Company) -> Quote:
    return Quote.objects.create(
        xero_id=uuid.uuid4(),
        company=company,
        date=timezone.localdate(),
        total_excl_tax=Decimal("100.00"),
        total_incl_tax=Decimal("115.00"),
    )


def make_purchase_order(supplier: Company) -> PurchaseOrder:
    return PurchaseOrder.objects.create(
        supplier=supplier,
        po_number=f"PO-{uuid.uuid4().hex[:8]}",
    )


def make_supplier_price_list(supplier: Company) -> SupplierPriceList:
    return SupplierPriceList.objects.create(supplier=supplier, file_name="test.csv")


def make_supplier_product(supplier: Company, price_list: SupplierPriceList) -> SupplierProduct:
    return SupplierProduct.objects.create(
        supplier=supplier,
        price_list=price_list,
        product_name="Widget",
        item_no=f"ITEM-{uuid.uuid4().hex[:6]}",
        variant_id=f"VAR-{uuid.uuid4().hex[:6]}",
        url=f"https://example.com/{uuid.uuid4().hex[:6]}",
    )


def make_scrape_job(supplier: Company) -> ScrapeJob:
    return ScrapeJob.objects.create(supplier=supplier)


def make_phone_call(
    company: Company | None = None, *, person: Person | None = None
) -> PhoneCallRecord:
    call_datetime = timezone.now()
    return PhoneCallRecord.objects.create(
        provider_call_id=f"merge-test:{uuid.uuid4()}",
        account_code="account",
        call_datetime=call_datetime,
        call_date=timezone.localdate(),
        call_time=call_datetime.time(),
        origin="+6421555123",
        destination="+6496365131",
        company=company,
        person=person,
        raw_json={},
    )
