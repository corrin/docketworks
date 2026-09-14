"""Fill the fake's organisation: fixtures from recordings, its objects from the mirror.

The mirror is what the application already knows of the organisation; the
recordings carry what the mirror never stores (the organisation record, its
tax rates, its branding themes, its pay calendar). Together they are "Xero
as of run start", which the E2E restore puts back after every fake run.
"""

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from xero_python import accounting as sdk_accounting
from xero_python import payrollnz as sdk_payroll
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
from apps.timesheet.services.payroll_employee_sync import hours_per_week, xero_employee_email
from apps.xero.contacts import contact_from_company
from apps.xero.fake import defaults
from apps.xero.fake.minting import as_list, as_mapping, now_utc, text
from apps.xero.fake.models import (
    RESOURCES,
    Document,
    FakeAccount,
    FakeBrandingTheme,
    FakeContact,
    FakeCreditNote,
    FakeEarningsRate,
    FakeEmployee,
    FakeInvoice,
    FakeItem,
    FakeLeaveType,
    FakeOrganisation,
    FakePayRun,
    FakePayRunCalendar,
    FakePaySlip,
    FakePurchaseOrder,
    FakeQuote,
    FakeSalaryAndWage,
    FakeTaxRate,
    FakeWorkingPattern,
)
from apps.xero.fake.wire import Json, ms_date_now, to_wire
from apps.xero.models import XeroAccount, XeroPayItem, XeroPayRun
from apps.xero.provider import XeroAccountingProvider

RECORDINGS_DIR = Path(__file__).resolve().parent / "recordings"
FAKE_SUFFIX = " (FAKE XERO)"


class SeedError(ValueError):
    """A mirror row the seed cannot turn into a Xero object; the row is the problem."""


def recorded_body(name: str) -> dict[str, Json]:
    """Read one recording's body, as the tenant sent it."""
    document = json.loads((RECORDINGS_DIR / f"{name}.json").read_text())
    if not isinstance(document, dict):
        raise TypeError(f"{name}.json is not a recording document")
    return as_mapping(document["body"], name)


def held_objects(tenant_id: str) -> int:
    """How many rows the organisation holds across every table."""
    return sum(model._default_manager.filter(tenant_id=tenant_id).count() for model in RESOURCES)


def empty(tenant_id: str) -> None:
    """Forget everything the organisation holds, children before their owners."""
    for model in reversed(RESOURCES):
        model._default_manager.filter(tenant_id=tenant_id).delete()


# ---- fixtures from recordings ---------------------------------------------------


def seed_organisation(tenant_id: str, name: str) -> None:
    """Seed the organisation record, its name suffixed so every banner that prints it says FAKE."""
    recorded = as_list(recorded_body("organisation")["Organisations"], "Organisations")
    organisation = dict(as_mapping(recorded[0], "Organisations[0]"))
    organisation["Name"] = f"{name}{FAKE_SUFFIX}"
    # One organisation per tenant, keyed by a UUID derived from the tenant:
    # the tables' ids are UUIDs, and a test tenant need not be one.
    organisation["OrganisationID"] = str(uuid5(NAMESPACE_URL, tenant_id))
    FakeOrganisation.from_wire(tenant_id, organisation, updated_date_utc=now_utc())


def seed_tax_rates(tenant_id: str) -> None:
    """Every tax rate the recording holds; totals are computed from these."""
    for raw in as_list(recorded_body("tax_rates")["TaxRates"], "TaxRates"):
        FakeTaxRate.write(
            tenant_id, uuid4(), as_mapping(raw, "TaxRates[]"), updated_date_utc=now_utc()
        )


def seed_branding_themes(tenant_id: str, configured_theme_id: str | None) -> None:
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
        FakeBrandingTheme.from_wire(tenant_id, theme, updated_date_utc=now_utc())


def seed_pay_run_calendar(tenant_id: str, calendar_id: str, name: str) -> None:
    """Seed the organisation's pay calendar: the configured id and name over the recorded shape."""
    recorded = as_list(recorded_body("pay_run_calendars")["payRunCalendars"], "payRunCalendars")
    calendar = dict(as_mapping(recorded[0], "payRunCalendars[0]"))
    calendar["payrollCalendarID"] = calendar_id
    calendar["name"] = name
    FakePayRunCalendar.from_wire(tenant_id, calendar)


# ---- the mirror ---------------------------------------------------------------


def _raw(row: object, label: str) -> Mapping[str, object]:
    raw = getattr(row, "raw_json", None)
    if not isinstance(raw, Mapping):
        raise SeedError(f"{label} has no raw_json to render; it was never mirrored from Xero")
    if raw.get("_e2e_stub"):
        raise SeedError(
            f"{label} was written by the readonly provider, not Xero; restore the database"
        )
    return raw


def seed_contacts(tenant_id: str) -> int:
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
            body = to_wire(sdk_accounting.Contact, company.raw_json)
        else:
            pushed = XeroAccountingProvider._to_xero_payload(contact_from_company(company))
            body = {**defaults.CONTACT, **as_mapping(pushed, contact_id), "ContactID": contact_id}
            body["UpdatedDateUTC"] = ms_date_now(company.xero_last_modified)
        FakeContact.from_wire(tenant_id, body)
        count += 1
    return count


def _hold_embedded_contact(tenant_id: str, body: Mapping[str, Json], label: str) -> None:
    """Hold the contact a document embeds when the mirror never held it as a company.

    Xero embeds the contact's record in every document (recordings/
    invoice.json), so a bill against a supplier the application does not
    hold as a company still names a contact Xero holds; that record is
    seeded from the embedding, and only what the embedding carries: a
    mirrored block may omit the status, and the column allows that.
    """
    embedded = body.get("Contact")
    if not isinstance(embedded, Mapping):
        raise SeedError(f"{label} carries no Contact block")
    contact_id = text(embedded, "ContactID")
    if contact_id is None:
        raise SeedError(f"{label} names no ContactID")
    if FakeContact.held(tenant_id, contact_id) is None:
        if "Name" not in embedded:
            raise SeedError(f"{label} names contact {contact_id}, which nothing holds")
        FakeContact.from_wire(tenant_id, embedded)


def _seed_documents(
    tenant_id: str,
    model: type[Document],
    sdk_model: type[BaseModel],
    rows: Iterable[object],
    label: str,
) -> int:
    count = 0
    for row in rows:
        xero_id = getattr(row, "xero_id", None)
        if xero_id is None:
            # Not in Xero yet (a local purchase order awaiting its push); Xero
            # would not list it either.
            continue
        body = to_wire(sdk_model, _raw(row, f"{label} {xero_id}"))
        _hold_embedded_contact(tenant_id, body, f"{label} {xero_id}")
        # The mirror's key is the id, whatever the stored body says it is.
        model.write(tenant_id, UUID(str(xero_id)), body)
        count += 1
    return count


def _seed_keyed(
    tenant_id: str,
    model: type[FakeItem] | type[FakeAccount],
    sdk_model: type[BaseModel],
    rows: Iterable[object],
    label: str,
) -> int:
    count = 0
    for row in rows:
        xero_id = getattr(row, "xero_id", None)
        if xero_id is None:
            continue
        model.write(
            tenant_id, UUID(str(xero_id)), to_wire(sdk_model, _raw(row, f"{label} {xero_id}"))
        )
        count += 1
    return count


def seed_accounting(tenant_id: str) -> dict[str, int]:
    """Everything the Accounting mirror holds, by kind."""
    return {
        "contacts": seed_contacts(tenant_id),
        "invoices": _seed_documents(
            tenant_id,
            FakeInvoice,
            sdk_accounting.Invoice,
            InvoiceModel.objects.iterator(),
            "invoice",
        )
        + _seed_documents(
            tenant_id, FakeInvoice, sdk_accounting.Invoice, Bill.objects.iterator(), "bill"
        ),
        "credit_notes": _seed_documents(
            tenant_id,
            FakeCreditNote,
            sdk_accounting.CreditNote,
            CreditNoteModel.objects.iterator(),
            "credit note",
        ),
        "quotes": _seed_documents(
            tenant_id, FakeQuote, sdk_accounting.Quote, QuoteModel.objects.iterator(), "quote"
        ),
        "purchase_orders": _seed_documents(
            tenant_id,
            FakePurchaseOrder,
            sdk_accounting.PurchaseOrder,
            PurchaseOrderModel.objects.iterator(),
            "PO",
        ),
        "items": _seed_keyed(
            tenant_id,
            FakeItem,
            sdk_accounting.Item,
            Stock.objects.filter(xero_id__isnull=False).iterator(),
            "item",
        ),
        # Scoped to the tenant, as the payroll phases are. The mirror keeps
        # account rows from earlier tenants and rows the sync never stamped
        # (production: 148 of 149 carry no tenant); the hourly accounts sync
        # stamps every account the tenant still has, and a row it never
        # touches is one the tenant no longer has.
        "accounts": _seed_keyed(
            tenant_id,
            FakeAccount,
            sdk_accounting.Account,
            XeroAccount.objects.filter(xero_tenant_id=tenant_id).iterator(),
            "account",
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


def seed_payroll(tenant_id: str, calendar_id: str) -> dict[str, int]:
    """Employees from Staff and their terms, pay items from the mirror, pay runs and slips."""
    counts = {"employees": 0, "pay_items": 0, "pay_runs": 0, "pay_slips": 0}
    staff_rows = Staff.objects.filter(
        xero_tenant_id=tenant_id, xero_user_id__isnull=False
    ).prefetch_related("payroll_terms")
    for staff in staff_rows:
        employee_id = str(staff.xero_user_id)
        # The address Xero holds is the one the real seed sent when it created
        # the employee, office first; payroll_email alone rendered null for a
        # staff member Xero itself lists with an email.
        email = xero_employee_email(staff)
        if email is None:
            raise SeedError(
                f"staff {staff.id} is linked to employee {employee_id} but has no email to render"
            )
        stamp = staff.xero_last_modified or now_utc()
        employee = FakeEmployee.from_wire(
            tenant_id,
            {
                **_EMPLOYEE_TEMPLATE,
                "employeeID": employee_id,
                "firstName": staff.first_name,
                "lastName": staff.last_name,
                "email": email,
                "startDate": _day(staff.employment_start_date),
                "endDate": _day(staff.date_left),
                "payrollCalendarID": calendar_id,
                "createdDateUTC": _naive(stamp),
            },
            updated_date_utc=stamp,
        )
        terms = list(staff.payroll_terms.all())
        for term in terms:
            _seed_term(employee, term, stamp)
        if not terms:
            _seed_created_records(employee, staff, stamp)
        counts["employees"] += 1

    counts["pay_items"] = _seed_pay_items(tenant_id)
    for pay_run in XeroPayRun.objects.filter(xero_tenant_id=tenant_id).iterator():
        run_id = str(pay_run.xero_id)
        run = FakePayRun.from_wire(
            tenant_id,
            to_wire(sdk_payroll.PayRun, _raw(pay_run, f"pay run {run_id}")),
            updated_date_utc=pay_run.xero_last_modified,
        )
        counts["pay_runs"] += 1
        for slip in pay_run.pay_slips.all():
            FakePaySlip.from_wire(
                tenant_id,
                to_wire(sdk_payroll.PaySlip, _raw(slip, f"pay slip {slip.xero_id}")),
                updated_date_utc=slip.xero_last_modified,
                pay_run=run,
            )
            counts["pay_slips"] += 1
    return counts


def _seed_term(employee: FakeEmployee, term: StaffPayrollTerm, stamp: datetime) -> None:
    """One payroll term as the two Xero records the sync reads it back from.

    Rendered from the same columns ``_current_employee_projection`` reads,
    so the sync's incoming checksum equals its stored one and it writes
    nothing (tests/test_payroll_routes.py proves that equality).
    """
    hourly = term.pay_basis == "hourly"
    salary: dict[str, Json] = {
        **_SALARY_TEMPLATE,
        "salaryAndWagesID": term.xero_salary_wage_id or str(uuid4()),
        "ratePerUnit": float(term.hourly_rate) if hourly and term.hourly_rate is not None else None,
        "annualSalary": float(term.annual_salary) if term.annual_salary is not None else None,
        "effectiveFrom": _day(term.effective_from),
        "status": "Active",
        "paymentType": "Hourly" if hourly else "Salary",
    }
    FakeSalaryAndWage.from_wire(
        employee.tenant_id, salary, updated_date_utc=stamp, employee=employee
    )
    if term.xero_working_pattern_id is None and not term.working_weeks:
        return
    pattern: dict[str, Json] = {
        "payeeWorkingPatternID": term.xero_working_pattern_id or str(uuid4()),
        "effectiveFrom": _day(term.effective_from),
        "workingWeeks": [
            {day: float(week.get(day, 0)) for day in _WEEKDAYS} for week in term.working_weeks
        ],
    }
    FakeWorkingPattern.from_wire(
        employee.tenant_id, pattern, updated_date_utc=stamp, employee=employee
    )


def _seed_created_records(employee: FakeEmployee, staff: Staff, stamp: datetime) -> None:
    """Render the pay record and pattern the real seed created for a staff member with no terms.

    A linked staff member without payroll terms (the E2E user after a restore)
    was created in Xero from base_wage_rate, the contracted hours and the start
    date (payroll_employees._create_salary_and_wage, _create_working_pattern),
    so those two records are what the tenant holds and what the inbound
    refresh requires; the mirror learns them only after that refresh.
    """
    hours = hours_per_week(staff)
    total_hours = sum(hours.values())
    working_days = sum(1 for value in hours.values() if value > 0)
    salary: dict[str, Json] = {
        **_SALARY_TEMPLATE,
        "salaryAndWagesID": str(uuid4()),
        "numberOfUnitsPerWeek": total_hours,
        "numberOfUnitsPerDay": total_hours / working_days,
        "daysPerWeek": float(working_days),
        "ratePerUnit": float(staff.base_wage_rate),
        "annualSalary": 0.0,
        "effectiveFrom": _day(staff.employment_start_date),
        "status": "Active",
        "paymentType": "Hourly",
    }
    FakeSalaryAndWage.from_wire(
        employee.tenant_id, salary, updated_date_utc=stamp, employee=employee
    )
    pattern: dict[str, Json] = {
        "payeeWorkingPatternID": str(uuid4()),
        "effectiveFrom": _day(staff.employment_start_date),
        "workingWeeks": [{day: hours[day] for day in _WEEKDAYS}],
    }
    FakeWorkingPattern.from_wire(
        employee.tenant_id, pattern, updated_date_utc=stamp, employee=employee
    )


def _seed_pay_items(tenant_id: str) -> int:
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
        xero_tenant_id=tenant_id, xero_id__isnull=False
    ).iterator():
        item_id = str(item.xero_id)
        if item.uses_leave_api:
            FakeLeaveType.from_wire(
                tenant_id,
                {**leave_template, "leaveTypeID": item_id, "name": item.name},
                updated_date_utc=now_utc(),
            )
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
            FakeEarningsRate.from_wire(
                tenant_id,
                {
                    **rate_template,
                    "earningsRateID": item_id,
                    "name": item.name,
                    "rateType": rate_type,
                    "multipleOfOrdinaryEarningsRate": multiple,
                },
                updated_date_utc=now_utc(),
            )
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


def seed_everything(tenant_id: str, *, organisation_name: str) -> dict[str, int]:
    """Run the whole seed in dependency order: fixtures, then contacts, then what names them."""
    company = CompanyDefaults.get_solo()
    seed_organisation(tenant_id, organisation_name)
    seed_tax_rates(tenant_id)
    seed_branding_themes(
        tenant_id,
        str(company.xero_sales_branding_theme_id) if company.xero_sales_branding_theme_id else None,
    )
    counts = seed_accounting(tenant_id)
    calendar_id = company.xero_payroll_calendar_id
    if calendar_id is not None:
        seed_pay_run_calendar(tenant_id, str(calendar_id), company.xero_payroll_calendar_name)
        counts.update(seed_payroll(tenant_id, str(calendar_id)))
    return counts
