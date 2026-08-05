"""Job/accounting factories for company-domain tests (merge, company-jobs).

Factories create only what each model truly requires so tests do not inherit
unrelated defaults.
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
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import PurchaseOrder
from apps.quoting.models import ScrapeJob, SupplierPriceList, SupplierProduct


def _xero_pay_item_model() -> type[Model]:
    """Resolve XeroPayItem dynamically: the layer contract forbids a static
    ``apps.company -> apps.xero`` import, but Job rows require the FK (the
    same inversion Job.save() carries under pyproject's ignore entry)."""
    return django_apps.get_model("xero", "XeroPayItem")


# The Xero pay-item catalogue a real tenant carries: earnings rates keyed by
# wage multiplier plus the leave types. Time-entry pricing resolves a pay item
# for every multiplier it is handed, so the earnings rates must all exist.
EARNINGS_RATES = (
    ("Ordinary Time", Decimal("1.00")),
    ("Time and one half", Decimal("1.50")),
    ("Double time", Decimal("2.00")),
    ("Unpaid", Decimal("0.00")),
)
LEAVE_TYPES = ("Annual Leave", "Sick Leave", "Bereavement Leave", "Unpaid Leave")


def seed_pay_items() -> None:
    """Create the standard Xero pay-item catalogue (earnings rates + leave types)."""
    manager = _xero_pay_item_model()._default_manager
    for name, multiplier in EARNINGS_RATES:
        manager.get_or_create(
            name=name,
            uses_leave_api=False,
            defaults={"multiplier": multiplier, "xero_id": f"xero-earnings-{multiplier}"},
        )
    for name in LEAVE_TYPES:
        manager.get_or_create(
            name=name,
            uses_leave_api=True,
            defaults={
                "multiplier": None,
                "xero_id": f"xero-leave-{name.lower().replace(' ', '-')}",
            },
        )


def seed_job_prereqs() -> "Model":
    """Create the rows a Job row requires; return the Ordinary Time pay item."""
    if not CompanyDefaults.objects.filter(id=1).exists():
        shop_company = Company.objects.create(
            name="Shop Company (internal)", xero_last_modified=timezone.now()
        )
        CompanyDefaults.objects.create(id=1, company_name="Test Co", shop_company=shop_company)
    seed_pay_items()
    return _xero_pay_item_model()._default_manager.get(name="Ordinary Time", uses_leave_api=False)


def make_job(company: Company, staff: Staff, *, name: str = "Test Job") -> Job:
    """Create a Job through the real save path.

    ``Job.save()`` generates the job number and cost sets itself; the factory
    only needs the prerequisites (CompanyDefaults + Ordinary Time pay item).
    """
    seed_job_prereqs()
    job = Job(name=name, company=company)
    job.save(staff=staff)
    return job


def make_material_line(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
    job: Job,
    *,
    set_kind: str = "actual",
    rev: str = "100.00",
    cost: str = "10.00",
    quantity: str = "1",
    on: date | None = None,
) -> CostLine:
    """One material cost line on the given cost set (total_rev = qty x rev).

    Time lines carry staff/pay-item constraints — use the timesheet
    conftest's make_time_line for those.
    """
    return CostLine.objects.create(
        cost_set=job.cost_sets.get(kind=set_kind),
        kind="material",
        desc=f"{set_kind} material line",
        quantity=Decimal(quantity),
        unit_cost=Decimal(cost),
        unit_rev=Decimal(rev),
        accounting_date=on if on is not None else timezone.localdate(),
    )


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


def make_invoice(
    company: Company,
    *,
    invoice_date: date | None = None,
    job: Job | None = None,
    status: str | None = None,
    total_excl_tax: Decimal | None = None,
) -> Invoice:
    fields = _invoice_fields(company)
    if invoice_date is not None:
        fields["date"] = invoice_date
    if job is not None:
        fields["job"] = job
    if status is not None:
        fields["status"] = status
    if total_excl_tax is not None:
        fields["total_excl_tax"] = total_excl_tax
        # Keep the NZ GST relationship consistent with the default fields.
        fields["tax"] = total_excl_tax * Decimal("0.15")
        fields["total_incl_tax"] = total_excl_tax * Decimal("1.15")
        fields["amount_due"] = fields["total_incl_tax"]
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
