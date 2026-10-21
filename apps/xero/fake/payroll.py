"""The Payroll NZ routes, answered from the model (ADR 0060).

Employees, their pay records and patterns, the pay items, calendars, pay
runs and slips; and the writes of the seed's employees phase, which creates
an employee with everything a pay run needs and renames a matched one. The
other payroll writes (timesheets, leave, pay runs) and their state machines
are the next slice; until they land, such a write is an unrouted call and the
run says so.
"""

import re
from collections.abc import Mapping
from datetime import UTC
from uuid import UUID, uuid4

from django.db.models import QuerySet
from xero_python.rest import RESTResponse

from apps.xero.fake import defaults, query
from apps.xero.fake.dates import payroll_datetime
from apps.xero.fake.http import FakeRequest, json_response
from apps.xero.fake.limits import quota_headers
from apps.xero.fake.minting import MintingError, as_list, as_mapping, new_id, now_utc, text
from apps.xero.fake.models import (
    FakeEarningsRate,
    FakeEmployee,
    FakeEmployeeLeaveType,
    FakeEmployeeTax,
    FakeLeaveBalance,
    FakeLeaveType,
    FakePaymentMethod,
    FakePayRun,
    FakePayRunCalendar,
    FakePaySlip,
    FakeSalaryAndWage,
    FakeWorkingPattern,
    XeroRecord,
)
from apps.xero.fake.wire import Json


def _stamp() -> str:
    # recordings/employee.json: naive UTC with seven fractional digits.
    return now_utc().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f0")


def payroll_envelope(key: str, value: Json, *, pagination: Json = None) -> Json:
    """Wrap a value the way the Payroll API does (recordings/employees_page.json)."""
    return {
        "id": new_id(),
        "providerName": defaults.PROVIDER_NAME,
        "dateTimeUTC": _stamp(),
        "httpStatusCode": "OK",
        "pagination": pagination,
        "problem": None,
        key: value,
    }


def _problem(status: int, code: str, title: str, detail: str, key: str | None) -> RESTResponse:
    body: dict[str, Json] = {
        "id": new_id(),
        "providerName": defaults.PROVIDER_NAME,
        "dateTimeUTC": _stamp(),
        "httpStatusCode": code,
        "pagination": None,
        "problem": {
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": None,
            "invalidFields": None,
            "invalidObjects": None,
        },
    }
    if key is not None:
        body[key] = []
    return json_response(status, body, quota_headers())


def _past_the_end(key: str) -> RESTResponse:
    """Xero's answer to a page beyond the last (recordings/employees_past_end.json)."""
    return _problem(400, "BadRequest", "InvalidRequest", "Requested page does not exist", key)


def _not_found() -> RESTResponse:
    # Payroll answers an unknown id with 404 and a problem block; the
    # application reads only the status.
    return _problem(404, "NotFound", "NotFound", "The resource was not found", None)


def _listing(request: FakeRequest, key: str, rows: QuerySet[XeroRecord]) -> RESTResponse:
    try:
        page, pagination = query.page(request, rows)
    # deliberate-swallow: a page past the end is Payroll's own 400, not an error
    except query.PastTheEnd:
        return _past_the_end(key)
    if pagination is None:
        # Payroll pages every listing, asked or not (recordings/pay_runs.json).
        pagination = {
            "page": 1,
            "pageSize": query.PAGE_SIZE,
            "pageCount": 1,
            "itemCount": len(page),
        }
    return json_response(
        200,
        payroll_envelope(key, [row.to_wire() for row in page], pagination=pagination),
        quota_headers(),
    )


_LISTINGS: dict[str, tuple[type[XeroRecord], str]] = {
    "Employees": (FakeEmployee, "employees"),
    "LeaveTypes": (FakeLeaveType, "leaveTypes"),
    "EarningsRates": (FakeEarningsRate, "earningsRates"),
    "PayRuns": (FakePayRun, "payRuns"),
    "PayRunCalendars": (FakePayRunCalendar, "payRunCalendars"),
}


def list_payroll_resource(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /{Employees|LeaveTypes|EarningsRates|PayRuns|PayRunCalendars}, paged."""
    model, key = _LISTINGS[match["resource"]]
    return _listing(request, key, query.listing(model, request))


def get_employee(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}: one employee under ``employee`` (recordings/employee.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    return json_response(200, payroll_envelope("employee", employee.to_wire()), quota_headers())


def list_salary_and_wages(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}/SalaryAndWages: the employee's pay records, paged."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    rows = query.listing(FakeSalaryAndWage, request).filter(employee=employee)
    return _listing(request, "salaryAndWages", rows)


def list_leave_balances(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}/LeaveBalances: one balance per leave type, paged."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    rows = query.listing(FakeLeaveBalance, request).filter(employee=employee)
    return _listing(request, "leaveBalances", rows)


def list_working_patterns(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}/Working-Patterns: id and date only (recordings/working_patterns.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    rows = query.listing(FakeWorkingPattern, request).filter(employee=employee)
    try:
        page, pagination = query.page(request, rows)
    # deliberate-swallow: as _listing
    except query.PastTheEnd:
        return _past_the_end("payeeWorkingPatterns")
    summaries: list[Json] = [
        {
            "payeeWorkingPatternID": str(pattern.id),
            "effectiveFrom": pattern.to_wire()["effectiveFrom"],
        }
        for pattern in page
    ]
    if pagination is None:
        pagination = {
            "page": 1,
            "pageSize": query.PAGE_SIZE,
            "pageCount": 1,
            "itemCount": len(summaries),
        }
    return json_response(
        200,
        payroll_envelope("payeeWorkingPatterns", summaries, pagination=pagination),
        quota_headers(),
    )


def get_working_pattern(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}/Working-Patterns/{pattern}: the weeks (working_pattern.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    pattern = FakeWorkingPattern.held(request.tenant_id, match["pattern"])
    if employee is None or pattern is None or pattern.employee_id != employee.id:
        return _not_found()
    return json_response(
        200, payroll_envelope("payeeWorkingPattern", pattern.to_wire()), quota_headers()
    )


def list_pay_slips(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /PaySlips?PayRunID=…: the slips of one pay run, paged."""
    del match
    pay_run_id = request.query.get("PayRunID")
    if pay_run_id is None:
        return _past_the_end("paySlips")
    pay_run = FakePayRun.held(request.tenant_id, pay_run_id)
    if pay_run is None:
        return _not_found()
    rows = query.listing(FakePaySlip, request, extra=("PayRunID",)).filter(pay_run=pay_run)
    return _listing(request, "paySlips", rows)


# ---- the employees phase's writes ------------------------------------------------


def _answer(key: str, value: Json) -> RESTResponse:
    return json_response(200, payroll_envelope(key, value), quota_headers())


def _sent(request: FakeRequest) -> dict[str, Json]:
    return as_mapping(request.json_body, f"{request.method} {request.path}")


def create_employee(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Employees: a new person on no calendar (recordings/employee_create.json)."""
    del match
    sent = _sent(request)
    stamp = now_utc()
    # Xero ignores a start date sent here; the employment sets it.
    body = {key: value for key, value in sent.items() if key != "startDate"}
    address = as_mapping(sent["address"], "address")
    employee = FakeEmployee.write(
        request.tenant_id,
        uuid4(),
        {
            **defaults.EMPLOYEE,
            **body,
            "address": {**defaults.EMPLOYEE_ADDRESS, **address},
            "createdDateUTC": payroll_datetime(stamp),
        },
        updated_date_utc=stamp,
    )
    return _answer("employee", employee.to_wire())


def update_employee(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """PUT /Employees/{id}: the whole employee replaced (recordings/employee_update.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    created = employee.to_wire()["createdDateUTC"]
    written = FakeEmployee.write(
        request.tenant_id,
        employee.id,
        {**defaults.EMPLOYEE, **_sent(request), "createdDateUTC": created},
        updated_date_utc=now_utc(),
    )
    return _answer("employee", written.to_wire())


def create_employment(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Employees/{id}/Employment: the employee's calendar and start date."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    sent = _sent(request)
    written = FakeEmployee.write(
        request.tenant_id,
        employee.id,
        {
            **employee.to_wire(),
            "payrollCalendarID": sent["payrollCalendarID"],
            "startDate": sent["startDate"],
        },
        updated_date_utc=now_utc(),
    )
    wire = written.to_wire()
    # recordings/employment_create.json: the employment is these four of the employee's fields.
    keys = ("payrollCalendarID", "startDate", "engagementType", "fixedTermEndDate")
    return _answer("employment", {key: wire[key] for key in keys})


def create_salary_and_wage(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Employees/{id}/SalaryAndWages: a pay record (salary_and_wage_create.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    body: dict[str, Json] = {**defaults.SALARY_AND_WAGE, **_sent(request)}
    if body["paymentType"] == "Hourly":
        # Sent as 0 because the SDK requires it; Xero holds no salary for an hourly rate.
        body["annualSalary"] = None
    row = FakeSalaryAndWage.write(
        request.tenant_id, uuid4(), body, updated_date_utc=now_utc(), employee=employee
    )
    return _answer("salaryAndWages", row.to_wire())


def create_working_pattern(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Employees/{id}/Working-Patterns: the weeks (working_pattern_create.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    row = FakeWorkingPattern.write(
        request.tenant_id, uuid4(), _sent(request), updated_date_utc=now_utc(), employee=employee
    )
    return _answer("payeeWorkingPattern", row.to_wire())


def update_employee_tax(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Employees/{id}/Tax: the one tax record, replaced (employee_tax_update.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    row = FakeEmployeeTax.write(
        request.tenant_id,
        employee.id,
        {**defaults.EMPLOYEE_TAX, **_sent(request)},
        updated_date_utc=now_utc(),
        employee=employee,
    )
    return _answer("employeeTax", row.to_wire())


def create_payment_method(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Employees/{id}/PaymentMethods: the bank accounts (payment_method_create.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    accounts: list[Json] = [
        {**defaults.BANK_ACCOUNT, **as_mapping(account, "bankAccounts[]")}
        for account in as_list(_sent(request)["bankAccounts"], "bankAccounts")
    ]
    # Xero answers with the accounts alone; the method sent beside them is not echoed.
    row = FakePaymentMethod.write(
        request.tenant_id,
        employee.id,
        {"bankAccounts": accounts},
        updated_date_utc=now_utc(),
        employee=employee,
    )
    return _answer("paymentMethod", row.to_wire())


def _leave_type_named(tenant_id: str, name: str) -> FakeLeaveType:
    leave_type = FakeLeaveType.objects.filter(tenant_id=tenant_id, name=name).first()
    if leave_type is None:
        raise MintingError(
            f"the organisation holds no {name!r} leave type, which Xero's leave setup assigns"
        )
    return leave_type


def _assign(
    employee: FakeEmployee, leave_type: FakeLeaveType, sent: Mapping[str, Json]
) -> FakeEmployeeLeaveType:
    """Make the employee eligible for one leave type, its balance opening at what was sent."""
    stamp = now_utc()
    body: dict[str, Json] = {
        **defaults.EMPLOYEE_LEAVE_TYPE,
        "openingBalanceTypeOfUnits": leave_type.type_of_units,
        "typeOfUnitsToAccrue": leave_type.type_of_units,
        **sent,
        "leaveTypeID": str(leave_type.id),
    }
    held = FakeEmployeeLeaveType.objects.filter(employee=employee, leave_type_id=leave_type.id)
    assigned = FakeEmployeeLeaveType.write(
        employee.tenant_id,
        _existing_id(held.first()),
        body,
        updated_date_utc=stamp,
        employee=employee,
    )
    balance = FakeLeaveBalance.objects.filter(employee=employee, leave_type_id=leave_type.id)
    FakeLeaveBalance.write(
        employee.tenant_id,
        _existing_id(balance.first()),
        {
            "leaveTypeID": str(leave_type.id),
            "name": leave_type.name,
            "balance": body["openingBalance"],
            "typeOfUnits": leave_type.type_of_units,
        },
        updated_date_utc=stamp,
        employee=employee,
    )
    return assigned


def _existing_id(row: FakeEmployeeLeaveType | FakeLeaveBalance | None) -> UUID:
    return uuid4() if row is None else row.id


def _first_lower(key: str) -> str:
    return key[:1].lower() + key[1:]


def create_leave_setup(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Employees/{id}/LeaveSetup: holiday pay, annual and sick leave assigned.

    recordings/employee_leave_types.json is the employee's leave types read
    straight after this call: those three, opening at the balances sent.
    """
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    # The SDK spells two keys with a capital (SickLeaveToAccrueAnnually);
    # Xero reads them regardless and answers in camelCase (leave_setup_create.json).
    setup: dict[str, Json] = {
        **defaults.LEAVE_SETUP,
        **{_first_lower(key): value for key, value in _sent(request).items()},
    }
    sick_accrual = setup["sickLeaveToAccrueAnnually"]
    rules: dict[str, dict[str, Json]] = {
        defaults.HOLIDAY_PAY: {
            "openingBalance": setup["holidayPayOpeningBalance"],
            "includeHolidayPayEveryPay": setup["includeHolidayPay"],
        },
        defaults.ANNUAL_LEAVE: {"openingBalance": setup["annualLeaveOpeningBalance"]},
        defaults.SICK_LEAVE: {
            "openingBalance": setup["sickLeaveOpeningBalance"],
            "hoursAccruedAnnually": sick_accrual,
            "unitsAccruedAnnually": sick_accrual,
            "maximumToAccrue": setup["sickLeaveMaximumToAccrue"],
        },
    }
    for name, rule in defaults.LEAVE_SETUP_ASSIGNS.items():
        _assign(employee, _leave_type_named(request.tenant_id, name), {**rule, **rules[name]})
    return _answer("leaveSetup", setup)


def list_employee_leave_types(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}/LeaveTypes: every leave type assigned, unpaged."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    rows = employee.leave_types.order_by("updated_date_utc", "id")
    return _answer("leaveTypes", [row.to_wire() for row in rows])


def create_employee_leave_type(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Employees/{id}/LeaveTypes: one more leave type (employee_leave_type_create.json)."""
    employee = FakeEmployee.held(request.tenant_id, match["id"])
    if employee is None:
        return _not_found()
    sent = _sent(request)
    leave_type_id = text(sent, "leaveTypeID")
    if leave_type_id is None:
        raise MintingError("an employee leave type must name its leaveTypeID")
    leave_type = FakeLeaveType.held(request.tenant_id, leave_type_id)
    if leave_type is None:
        raise MintingError(f"no leave type {leave_type_id} in the organisation to assign")
    return _answer("leaveType", _assign(employee, leave_type, sent).to_wire())
