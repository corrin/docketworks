"""Fill the fake's store: the organisation's fixtures from recordings, its objects from the mirror.

The mirror is what the application already knows of the organisation; the
recordings carry what the mirror never stores (the organisation record, its
tax rates, its branding themes). Together they are "Xero as of run start",
which the E2E restore puts back after every fake run.
"""

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from xero_python.accounting import Contact
from xero_python.models import BaseModel

from apps.accounting.models import Bill
from apps.accounting.models import CreditNote as CreditNoteModel
from apps.accounting.models import Invoice as InvoiceModel
from apps.accounting.models import Quote as QuoteModel
from apps.accounts.models import Staff, StaffPayrollTerm
from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.purchasing.models import PurchaseOrder as PurchaseOrderModel
from apps.purchasing.models import Stock
from apps.xero.contacts import contact_from_company
from apps.xero.fake import defaults
from apps.xero.fake.minting import as_list, as_mapping, new_id, now_utc, text
from apps.xero.fake.store import FakeXeroStore, Kind
from apps.xero.fake.wire import Json, ms_date_now, to_wire
from apps.xero.models import XeroAccount, XeroPayItem, XeroPayRun
from apps.xero.provider import XeroAccountingProvider

RECORDINGS_DIR = Path(__file__).resolve().parent / "recordings"
FAKE_SUFFIX = " (FAKE XERO)"


def recorded_body(name: str) -> dict[str, Json]:
    """Read one recording's body, as the tenant sent it."""
    document = json.loads((RECORDINGS_DIR / f"{name}.json").read_text())
    if not isinstance(document, dict):
        raise TypeError(f"{name}.json is not a recording document")
    return as_mapping(document["body"], name)


def seed_organisation(store: FakeXeroStore, name: str) -> None:
    """Seed the organisation record, its name suffixed so every banner that prints it says FAKE."""
    recorded = as_list(recorded_body("organisation")["Organisations"], "Organisations")
    organisation = dict(as_mapping(recorded[0], "Organisations[0]"))
    suffixed = f"{name}{FAKE_SUFFIX}"
    organisation["Name"] = suffixed
    # One organisation per tenant, keyed by a UUID derived from the tenant:
    # the store's ids are UUIDs, and a test tenant need not be one.
    organisation_id = str(uuid5(NAMESPACE_URL, store.tenant_id))
    organisation["OrganisationID"] = organisation_id
    store.save(
        Kind.ORGANISATION, organisation_id, organisation, updated_date_utc=now_utc(), name=suffixed
    )


def seed_tax_rates(store: FakeXeroStore) -> None:
    """Every tax rate the recording holds; totals are computed from these."""
    for raw in as_list(recorded_body("tax_rates")["TaxRates"], "TaxRates"):
        rate = as_mapping(raw, "TaxRates[]")
        store.save(
            Kind.TAX_RATE,
            new_id(),
            rate,
            updated_date_utc=now_utc(),
            name=text(rate, "TaxType"),
            status=text(rate, "Status"),
        )


def seed_branding_themes(store: FakeXeroStore, configured_theme_id: str | None) -> None:
    """Two themes at least: the configured one, and the recording's others.

    The company-defaults spec needs an alternative to switch to, and the
    quote and invoice pushes name the configured id; both must exist.
    """
    themes = [
        dict(as_mapping(raw, "BrandingThemes[]"))
        for raw in as_list(recorded_body("branding_themes")["BrandingThemes"], "BrandingThemes")
    ]
    if configured_theme_id is not None and all(
        theme.get("BrandingThemeID") != configured_theme_id for theme in themes
    ):
        first = dict(themes[0])
        first["BrandingThemeID"] = configured_theme_id
        first["Name"] = "Configured"
        themes.insert(0, first)
    for theme in themes:
        theme_id = text(theme, "BrandingThemeID")
        if theme_id is None:
            raise ValueError("a recorded branding theme has no BrandingThemeID")
        store.save(
            Kind.BRANDING_THEME,
            theme_id,
            theme,
            updated_date_utc=now_utc(),
            name=text(theme, "Name"),
        )


# ---- the mirror ---------------------------------------------------------------


def _accounting_dates(body: dict[str, Json]) -> datetime:
    """Read the instant a rendered Accounting body says it changed, for the listing order."""
    updated = body.get("UpdatedDateUTC")
    if not isinstance(updated, str) or not updated.startswith("/Date("):
        raise SeedError("a rendered body carries no UpdatedDateUTC; the mirror row is not Xero's")
    millis = int(updated.removeprefix("/Date(").split("+")[0].rstrip(")/"))
    return datetime.fromtimestamp(millis / 1000, tz=UTC)


class SeedError(ValueError):
    """A mirror row the seed cannot turn into a Xero object; the row is the problem."""


def _raw(row: object, label: str) -> Mapping[str, object]:
    raw = getattr(row, "raw_json", None)
    if not isinstance(raw, Mapping):
        raise SeedError(f"{label} has no raw_json to render; it was never mirrored from Xero")
    if raw.get("_e2e_stub"):
        raise SeedError(
            f"{label} was written by the readonly provider, not Xero; restore the database"
        )
    return raw


def seed_contacts(store: FakeXeroStore) -> int:
    """Every company Xero knows: rendered from its last mirrored record, or from its columns.

    A company the application pushed but the sync has not yet read back has
    an id and no raw_json; it is rendered the way the push rendered it
    (contact_from_company, the one contact builder), over Xero's defaults.
    """
    count = 0
    for company in Company.objects.filter(xero_contact_id__isnull=False).iterator():
        contact_id = str(company.xero_contact_id)
        # An empty body is no body: the standing seed company ("Demo Company
        # Shop", the onboarding's own row) carries {} rather than NULL.
        if isinstance(company.raw_json, Mapping) and company.raw_json:
            body = to_wire(Contact, company.raw_json)
        else:
            pushed = XeroAccountingProvider._to_xero_payload(contact_from_company(company))
            body = {**defaults.CONTACT, **as_mapping(pushed, contact_id), "ContactID": contact_id}
            body["UpdatedDateUTC"] = ms_date_now(company.xero_last_modified)
        store.save(
            Kind.CONTACT,
            contact_id,
            body,
            updated_date_utc=company.xero_last_modified,
            name=text(body, "Name"),
            status=text(body, "ContactStatus"),
        )
        count += 1
    return count


def _seed_documents(
    store: FakeXeroStore, kind: Kind, model: type[BaseModel], rows: Iterable[object], label: str
) -> int:
    count = 0
    number_key = {
        Kind.INVOICE: "InvoiceNumber",
        Kind.CREDIT_NOTE: "CreditNoteNumber",
        Kind.QUOTE: "QuoteNumber",
        Kind.PURCHASE_ORDER: "PurchaseOrderNumber",
        Kind.ITEM: "Code",
        Kind.ACCOUNT: "Code",
    }[kind]
    for row in rows:
        xero_id = getattr(row, "xero_id", None)
        if xero_id is None:
            # Not in Xero yet (a local purchase order awaiting its push); Xero
            # would not list it either.
            continue
        body = to_wire(model, _raw(row, f"{label} {xero_id}"))
        store.save(
            kind,
            str(xero_id),
            body,
            updated_date_utc=_accounting_dates(body),
            number=text(body, number_key),
            name=text(body, "Name") if kind in (Kind.ITEM, Kind.ACCOUNT) else None,
            status=text(body, "Status"),
        )
        count += 1
    return count


def seed_accounting(store: FakeXeroStore) -> dict[str, int]:
    """Everything the Accounting mirror holds, by kind."""
    from xero_python.accounting import (  # noqa: PLC0415 -- SDK models resolved at seed time
        Account,
        CreditNote,
        Invoice,
        Item,
        PurchaseOrder,
        Quote,
    )

    return {
        "contacts": seed_contacts(store),
        "invoices": _seed_documents(
            store, Kind.INVOICE, Invoice, InvoiceModel.objects.iterator(), "invoice"
        )
        + _seed_documents(store, Kind.INVOICE, Invoice, Bill.objects.iterator(), "bill"),
        "credit_notes": _seed_documents(
            store, Kind.CREDIT_NOTE, CreditNote, CreditNoteModel.objects.iterator(), "credit note"
        ),
        "quotes": _seed_documents(store, Kind.QUOTE, Quote, QuoteModel.objects.iterator(), "quote"),
        "purchase_orders": _seed_documents(
            store, Kind.PURCHASE_ORDER, PurchaseOrder, PurchaseOrderModel.objects.iterator(), "PO"
        ),
        "items": _seed_documents(
            store, Kind.ITEM, Item, Stock.objects.filter(xero_id__isnull=False).iterator(), "item"
        ),
        "accounts": _seed_documents(
            store, Kind.ACCOUNT, Account, XeroAccount.objects.iterator(), "account"
        ),
    }


def _naive(moment: datetime | None) -> str:
    """Payroll's timestamp form: ISO-8601, UTC, no offset."""
    if moment is None:
        raise SeedError("a payroll object has no timestamp")
    return moment.astimezone(UTC).replace(tzinfo=None).isoformat()


def _day(value: date | None) -> str | None:
    """Payroll's date form for a date field: midnight, no offset (recordings/employee.json)."""
    return None if value is None else f"{value.isoformat()}T00:00:00"


def seed_payroll(store: FakeXeroStore, calendar_id: str) -> dict[str, int]:
    """Employees from Staff and their terms, pay items from the mirror, pay runs and slips."""
    from xero_python.payrollnz import (  # noqa: PLC0415 -- SDK models resolved at seed time
        PayRun,
        PaySlip,
    )

    counts = {"employees": 0, "pay_items": 0, "pay_runs": 0, "pay_slips": 0}
    staff_rows = Staff.objects.filter(
        xero_tenant_id=store.tenant_id, xero_user_id__isnull=False
    ).prefetch_related("payroll_terms")
    for staff in staff_rows:
        employee_id = str(staff.xero_user_id)
        employee: dict[str, Json] = {
            **_EMPLOYEE_TEMPLATE,
            "employeeID": employee_id,
            "firstName": staff.first_name,
            "lastName": staff.last_name,
            "email": staff.payroll_email,
            "startDate": _day(staff.employment_start_date),
            "endDate": _day(staff.date_left),
            "payrollCalendarID": calendar_id,
            "updatedDateUTC": _naive(staff.xero_last_modified or now_utc()),
            "createdDateUTC": _naive(staff.xero_last_modified or now_utc()),
        }
        stamp = staff.xero_last_modified or now_utc()
        store.save(
            Kind.EMPLOYEE,
            employee_id,
            employee,
            updated_date_utc=stamp,
            name=f"{staff.first_name} {staff.last_name}",
            parent_id=None,
        )
        for term in staff.payroll_terms.all():
            _seed_term(store, employee_id, term, stamp)
        counts["employees"] += 1

    counts["pay_items"] = _seed_pay_items(store)
    for pay_run in XeroPayRun.objects.filter(xero_tenant_id=store.tenant_id).iterator():
        run_id = str(pay_run.xero_id)
        body = to_wire(PayRun, _raw(pay_run, f"pay run {run_id}"))
        store.save(
            Kind.PAY_RUN,
            run_id,
            body,
            updated_date_utc=pay_run.xero_last_modified,
            status=text(body, "payRunStatus"),
        )
        counts["pay_runs"] += 1
        for slip in pay_run.pay_slips.all():
            slip_body = to_wire(PaySlip, _raw(slip, f"pay slip {slip.xero_id}"))
            store.save(
                Kind.PAY_SLIP,
                str(slip.xero_id),
                slip_body,
                updated_date_utc=slip.xero_last_modified,
                parent_id=run_id,
            )
            counts["pay_slips"] += 1
    return counts


def _seed_term(
    store: FakeXeroStore, employee_id: str, term: StaffPayrollTerm, stamp: datetime
) -> None:
    """One payroll term as the two Xero records the sync reads it back from.

    Rendered from the same columns ``_current_employee_projection`` reads,
    so the sync's incoming checksum equals its stored one and it writes
    nothing (tests/test_payroll_routes.py proves that equality).
    """
    hourly = term.pay_basis == "hourly"
    salary: dict[str, Json] = {
        **_SALARY_TEMPLATE,
        "salaryAndWagesID": term.xero_salary_wage_id or new_id(),
        "ratePerUnit": float(term.hourly_rate) if hourly and term.hourly_rate is not None else None,
        "annualSalary": float(term.annual_salary) if term.annual_salary is not None else None,
        "effectiveFrom": _day(term.effective_from),
        "status": "Active",
        "paymentType": "Hourly" if hourly else "Salary",
    }
    store.save(
        Kind.SALARY_AND_WAGE,
        str(salary["salaryAndWagesID"]),
        salary,
        updated_date_utc=stamp,
        parent_id=employee_id,
    )
    if term.xero_working_pattern_id is None and not term.working_weeks:
        return
    pattern: dict[str, Json] = {
        "payeeWorkingPatternID": term.xero_working_pattern_id or new_id(),
        "effectiveFrom": _day(term.effective_from),
        "workingWeeks": [
            {day: float(week.get(day, 0)) for day in _WEEKDAYS} for week in term.working_weeks
        ],
    }
    store.save(
        Kind.WORKING_PATTERN,
        str(pattern["payeeWorkingPatternID"]),
        pattern,
        updated_date_utc=stamp,
        parent_id=employee_id,
    )


def _seed_pay_items(store: FakeXeroStore) -> int:
    """Leave types and earnings rates from XeroPayItem, over the recorded shapes."""
    leave_template = as_mapping(
        as_list(recorded_body("leave_types")["leaveTypes"], "leaveTypes")[0], "leaveTypes[0]"
    )
    rate_template = as_mapping(
        as_list(recorded_body("earnings_rates")["earningsRates"], "earningsRates")[0],
        "earningsRates[0]",
    )
    count = 0
    for item in XeroPayItem.objects.filter(
        xero_tenant_id=store.tenant_id, xero_id__isnull=False
    ).iterator():
        item_id = str(item.xero_id)
        if item.uses_leave_api:
            body: dict[str, Json] = {**leave_template, "leaveTypeID": item_id, "name": item.name}
            kind = Kind.LEAVE_TYPE
        else:
            # payroll_sync.get_earnings_rates infers the multiplier from
            # rateType; this is that inference run backwards, so the sync
            # reads the multiplier the mirror already holds.
            multiplier = item.multiplier
            if multiplier is None:
                rate_type, multiple = "FixedAmount", None
            elif multiplier == 1:
                rate_type, multiple = "RatePerUnit", None
            else:
                rate_type, multiple = "MultipleOfOrdinaryEarningsRate", float(multiplier)
            body = {
                **rate_template,
                "earningsRateID": item_id,
                "name": item.name,
                "rateType": rate_type,
                "multipleOfOrdinaryEarningsRate": multiple,
            }
            kind = Kind.EARNINGS_RATE
        store.save(kind, item_id, body, updated_date_utc=now_utc(), name=item.name)
        count += 1
    return count


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# recordings/employee.json: the fields Xero returns for every employee. The
# SDK's Employee refuses a missing date of birth or address, and Staff holds
# neither, so both are placeholders — a fixed date and empty address lines —
# which the application never reads (payroll_employees._snapshot names the
# fields it does).
_EMPLOYEE_TEMPLATE: dict[str, Json] = {
    "dateOfBirth": "1970-01-01T00:00:00",
    "address": {"addressLine1": "", "city": "", "postCode": "", "countryName": "NEW ZEALAND"},
    "engagementType": None,
    "fixedTermEndDate": None,
    "employmentType": "Employee",
    "jobTitle": None,
}

# recordings/salary_and_wages.json. The earnings rate is the recorded
# organisation's ordinary-time rate: the SDK refuses the field absent and the
# application never reads it.
_SALARY_TEMPLATE: dict[str, Json] = {
    "earningsRateID": "2980135c-5ec8-4907-aaef-4096f407ca7d",
    "numberOfUnitsPerWeek": 40.0,
    "numberOfUnitsPerDay": 8.0,
    "daysPerWeek": 5.0,
    "workPatternType": "RegularWeek",
}


def seed_everything(store: FakeXeroStore, *, organisation_name: str) -> dict[str, int]:
    """Run the whole seed in dependency order: fixtures, then contacts, then what names them."""
    company = CompanyDefaults.get_solo()
    seed_organisation(store, organisation_name)
    seed_tax_rates(store)
    seed_branding_themes(
        store,
        str(company.xero_sales_branding_theme_id) if company.xero_sales_branding_theme_id else None,
    )
    counts = seed_accounting(store)
    calendar_id = company.xero_payroll_calendar_id
    if calendar_id is not None:
        counts.update(seed_payroll(store, str(calendar_id)))
    return counts
