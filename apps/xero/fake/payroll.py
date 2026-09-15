"""The Payroll NZ reads, answered from the model (ADR 0060).

Employees, their pay records and patterns, the pay items, calendars, pay
runs and slips. The payroll writes (employees, timesheets, leave, pay runs)
and their state machines are the next slice; until they land, a payroll
write is an unrouted call and the run says so.
"""

import re
from datetime import UTC

from django.db.models import QuerySet
from xero_python.rest import RESTResponse

from apps.xero.fake import defaults, query
from apps.xero.fake.http import FakeRequest, json_response
from apps.xero.fake.limits import quota_headers
from apps.xero.fake.minting import new_id, now_utc
from apps.xero.fake.models import (
    FakeEarningsRate,
    FakeEmployee,
    FakeLeaveBalance,
    FakeLeaveType,
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
