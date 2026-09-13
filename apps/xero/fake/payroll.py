"""The Payroll NZ routes an E2E run reaches: employees, their terms, pay items, pay runs, slips.

All reads. The writes the payroll screens make (timesheets, pay runs,
employee creation) are deliberately not here: those specs are opt-in against
the real tenant (ADR 0050's irreversibility exception), and a fake that
accepted them would be the fake-provider coverage that ADR forbids.
"""

import re
from datetime import UTC

from xero_python.rest import RESTResponse

from apps.xero.fake import defaults
from apps.xero.fake.accounting import QUOTA_HEADERS
from apps.xero.fake.http import FakeRequest, json_response
from apps.xero.fake.minting import new_id, now_utc
from apps.xero.fake.store import FakeXeroNotFoundError, FakeXeroStore, Kind
from apps.xero.fake.wire import Json

PAGE_SIZE = 100


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


def _page_of(request: FakeRequest, rows: list[Json]) -> tuple[list[Json], Json]:
    """Slice a listing as Xero pages it, with the block the sync loops on.

    A page past the last is a 400 (recordings/employees_past_end.json), which
    ``payroll_employees._raw_employees`` relies on never meeting because it
    stops at ``pageCount``.
    """
    page = int(request.query.get("page", 1))
    page_count = max(1, -(-len(rows) // PAGE_SIZE))
    if page > page_count:
        raise _PastTheEnd
    offset = (page - 1) * PAGE_SIZE
    pagination: Json = {
        "page": page,
        "pageSize": PAGE_SIZE,
        "pageCount": page_count,
        "itemCount": len(rows),
    }
    return rows[offset : offset + PAGE_SIZE], pagination


class _PastTheEnd(Exception):  # noqa: N818 -- a routed outcome, not a defect
    """Xero's answer to a page beyond the last: 400 InvalidRequest."""


def _past_the_end(key: str) -> RESTResponse:
    body: Json = {
        "id": new_id(),
        "providerName": defaults.PROVIDER_NAME,
        "dateTimeUTC": _stamp(),
        "httpStatusCode": "BadRequest",
        "pagination": None,
        "problem": {
            "type": "about:blank",
            "title": "InvalidRequest",
            "status": 400,
            "detail": "Requested page does not exist",
            "instance": None,
            "invalidFields": None,
            "invalidObjects": None,
        },
        key: [],
    }
    return json_response(400, body, QUOTA_HEADERS)


def _listing(request: FakeRequest, key: str, rows: list[Json]) -> RESTResponse:
    try:
        page, pagination = _page_of(request, rows)
    # deliberate-swallow: a page past the end is Payroll's empty answer, not an error
    except _PastTheEnd:
        return _past_the_end(key)
    return json_response(200, payroll_envelope(key, page, pagination=pagination), QUOTA_HEADERS)


def _not_found() -> RESTResponse:
    # Payroll answers an unknown id with 404 and a problem block; the
    # application reads only the status.
    body: Json = {
        "id": new_id(),
        "providerName": defaults.PROVIDER_NAME,
        "dateTimeUTC": _stamp(),
        "httpStatusCode": "NotFound",
        "pagination": None,
        "problem": {
            "type": "about:blank",
            "title": "NotFound",
            "status": 404,
            "detail": "The resource was not found",
            "instance": None,
            "invalidFields": None,
            "invalidObjects": None,
        },
    }
    return json_response(404, body, QUOTA_HEADERS)


_LISTINGS: dict[str, Kind] = {
    "Employees": Kind.EMPLOYEE,
    "LeaveTypes": Kind.LEAVE_TYPE,
    "EarningsRates": Kind.EARNINGS_RATE,
    "PayRuns": Kind.PAY_RUN,
}
_KEYS: dict[str, str] = {
    "Employees": "employees",
    "LeaveTypes": "leaveTypes",
    "EarningsRates": "earningsRates",
    "PayRuns": "payRuns",
}


def list_payroll_resource(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /{Employees|LeaveTypes|EarningsRates|PayRuns}, paged."""
    resource = match["resource"]
    rows = FakeXeroStore(request.tenant_id).listing(_LISTINGS[resource])
    return _listing(request, _KEYS[resource], [row.body for row in rows])


def get_employee(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}: one employee under ``employee`` (recordings/employee.json)."""
    try:
        row = FakeXeroStore(request.tenant_id).require(Kind.EMPLOYEE, match["id"])
    # deliberate-swallow: an employee id Payroll never issued answers 404 with its problem block
    except FakeXeroNotFoundError:
        return _not_found()
    return json_response(200, payroll_envelope("employee", row.body), QUOTA_HEADERS)


def list_salary_and_wages(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}/SalaryAndWages: the employee's pay records, paged."""
    store = FakeXeroStore(request.tenant_id)
    try:
        employee = store.require(Kind.EMPLOYEE, match["id"])
    # deliberate-swallow: pay records of an employee Payroll does not hold answer 404
    except FakeXeroNotFoundError:
        return _not_found()
    rows = store.listing(Kind.SALARY_AND_WAGE, parent_id=str(employee.id))
    return _listing(request, "salaryAndWages", [row.body for row in rows])


def list_working_patterns(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}/Working-Patterns: id and date only (recordings/working_patterns.json)."""
    store = FakeXeroStore(request.tenant_id)
    try:
        employee = store.require(Kind.EMPLOYEE, match["id"])
    # deliberate-swallow: working patterns of an employee Payroll does not hold answer 404
    except FakeXeroNotFoundError:
        return _not_found()
    summaries: list[Json] = [
        {
            "payeeWorkingPatternID": row.body["payeeWorkingPatternID"],
            "effectiveFrom": row.body["effectiveFrom"],
        }
        for row in store.listing(Kind.WORKING_PATTERN, parent_id=str(employee.id))
    ]
    return _listing(request, "payeeWorkingPatterns", summaries)


def get_working_pattern(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Employees/{id}/Working-Patterns/{pattern}: the weeks (working_pattern.json)."""
    store = FakeXeroStore(request.tenant_id)
    try:
        employee = store.require(Kind.EMPLOYEE, match["id"])
        pattern = store.require(Kind.WORKING_PATTERN, match["pattern"])
    # deliberate-swallow: an unknown employee or an unknown pattern id is Payroll's 404
    except FakeXeroNotFoundError:
        return _not_found()
    if pattern.parent_id != employee.id:
        return _not_found()
    return json_response(200, payroll_envelope("payeeWorkingPattern", pattern.body), QUOTA_HEADERS)


def list_pay_slips(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /PaySlips?PayRunID=…: the slips of one pay run, paged."""
    del match
    store = FakeXeroStore(request.tenant_id)
    pay_run_id = request.query.get("PayRunID")
    if pay_run_id is None:
        return _past_the_end("paySlips")
    try:
        pay_run = store.require(Kind.PAY_RUN, pay_run_id)
    # deliberate-swallow: slips of a pay run Payroll never issued answer 404
    except FakeXeroNotFoundError:
        return _not_found()
    rows = store.listing(Kind.PAY_SLIP, parent_id=str(pay_run.id))
    return _listing(request, "paySlips", [row.body for row in rows])
