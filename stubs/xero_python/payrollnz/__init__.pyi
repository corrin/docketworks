from datetime import date
from enum import Enum
from typing import Any

from xero_python.api_client import ApiClient

class PayRun:
    pay_run_id: str | None
    payroll_calendar_id: str | None
    period_start_date: date | None
    period_end_date: date | None
    payment_date: date | None
    pay_run_status: str | None
    pay_run_type: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class PayRuns:
    pay_runs: list[PayRun] | None
    def __init__(self, **kwargs: Any) -> None: ...

class PaySlip:
    pay_slip_id: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class PaySlips:
    pay_slips: list[PaySlip] | None
    def __init__(self, **kwargs: Any) -> None: ...

class LeaveType:
    leave_type_id: str | None
    name: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class LeaveTypes:
    leave_types: list[LeaveType] | None
    def __init__(self, **kwargs: Any) -> None: ...

class EarningsRate:
    earnings_rate_id: str | None
    name: str | None
    earnings_type: str | None
    rate_type: str | None
    type_of_units: str | None
    multiple_of_ordinary_earnings_rate: float | None
    expense_account_id: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class EarningsRates:
    earnings_rates: list[EarningsRate] | None
    def __init__(self, **kwargs: Any) -> None: ...

class PayRunObject:
    pay_run: PayRun | None
    def __init__(self, **kwargs: Any) -> None: ...

class CalendarType(Enum):
    WEEKLY = "Weekly"
    FORTNIGHTLY = "Fortnightly"
    FOURWEEKLY = "FourWeekly"
    MONTHLY = "Monthly"
    TWICEMONTHLY = "TwiceMonthly"
    QUARTERLY = "Quarterly"
    ANNUAL = "Annual"

class PayRunCalendar:
    payroll_calendar_id: str | None
    name: str | None
    calendar_type: CalendarType | None
    period_start_date: date | None
    period_end_date: date | None
    payment_date: date | None
    def __init__(self, **kwargs: Any) -> None: ...

class PayRunCalendars:
    pay_run_calendars: list[PayRunCalendar] | None
    def __init__(self, **kwargs: Any) -> None: ...

class Employee:
    employee_id: str | None
    first_name: str | None
    last_name: str | None
    job_title: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class Employees:
    employees: list[Employee] | None
    def __init__(self, **kwargs: Any) -> None: ...

class TaxCode(Enum):
    M = "M"
    ME = "ME"
    ND = "ND"
    NSW = "NSW"
    SB = "SB"

class EmployeeTax:
    ird_number: str | None
    tax_code: TaxCode | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeLeaveSetup:
    def __init__(self, **kwargs: Any) -> None: ...

class BankAccount:
    account_name: str | None
    account_number: str | None
    sort_code: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class PaymentMethod:
    payment_method: str | None
    bank_accounts: list[BankAccount] | None
    def __init__(self, **kwargs: Any) -> None: ...

class TimesheetLine:
    timesheet_line_id: str | None
    date: date | None
    earnings_rate_id: str | None
    tracking_item_id: str | None
    number_of_units: float | None
    def __init__(self, **kwargs: Any) -> None: ...

class Timesheet:
    timesheet_id: str | None
    payroll_calendar_id: str | None
    employee_id: str | None
    start_date: date | None
    end_date: date | None
    status: str | None
    total_hours: float | None
    timesheet_lines: list[TimesheetLine] | None
    def __init__(self, **kwargs: Any) -> None: ...

class TimesheetObject:
    timesheet: Timesheet | None
    def __init__(self, **kwargs: Any) -> None: ...

class Timesheets:
    timesheets: list[Timesheet] | None
    def __init__(self, **kwargs: Any) -> None: ...

class LeavePeriod:
    period_start_date: date | None
    period_end_date: date | None
    number_of_units: float | None
    number_of_units_taken: float | None
    period_status: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeLeave:
    leave_id: str | None
    leave_type_id: str | None
    description: str | None
    start_date: date | None
    end_date: date | None
    periods: list[LeavePeriod] | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeLeaves:
    leave: list[EmployeeLeave] | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeLeaveObject:
    leave: EmployeeLeave | None
    def __init__(self, **kwargs: Any) -> None: ...

class PayrollNzApi:
    def __init__(self, api_client: ApiClient) -> None: ...
    def get_employees(self, xero_tenant_id: str, **kwargs: Any) -> Employees: ...
    def update_employee_tax(
        self, xero_tenant_id: str, employee_id: str, employee_tax: EmployeeTax, **kwargs: Any
    ) -> Any: ...
    def create_employee_leave_setup(
        self,
        xero_tenant_id: str,
        employee_id: str,
        employee_leave_setup: EmployeeLeaveSetup,
        **kwargs: Any,
    ) -> Any: ...
    def create_employee_payment_method(
        self, xero_tenant_id: str, employee_id: str, payment_method: PaymentMethod, **kwargs: Any
    ) -> Any: ...
    def get_pay_runs(self, xero_tenant_id: str, **kwargs: Any) -> PayRuns: ...
    def get_pay_run(self, xero_tenant_id: str, pay_run_id: str, **kwargs: Any) -> PayRunObject: ...
    def get_pay_slips(self, xero_tenant_id: str, pay_run_id: str, **kwargs: Any) -> PaySlips: ...
    def get_leave_types(self, xero_tenant_id: str, **kwargs: Any) -> LeaveTypes: ...
    def get_earnings_rates(self, xero_tenant_id: str, **kwargs: Any) -> EarningsRates: ...
    def get_pay_run_calendars(self, xero_tenant_id: str, **kwargs: Any) -> PayRunCalendars: ...
    def create_pay_run_calendar(
        self, xero_tenant_id: str, pay_run_calendar: PayRunCalendar, **kwargs: Any
    ) -> PayRunCalendars: ...
    def create_leave_type(
        self, xero_tenant_id: str, leave_type: LeaveType, **kwargs: Any
    ) -> LeaveTypes: ...
    def create_earnings_rate(
        self, xero_tenant_id: str, earnings_rate: EarningsRate, **kwargs: Any
    ) -> EarningsRates: ...
    def get_timesheets(self, xero_tenant_id: str, **kwargs: Any) -> Timesheets: ...
    def create_timesheet(
        self, xero_tenant_id: str, timesheet: Timesheet, **kwargs: Any
    ) -> TimesheetObject: ...
    def delete_timesheet(self, xero_tenant_id: str, timesheet_id: str, **kwargs: Any) -> Any: ...
    def approve_timesheet(self, xero_tenant_id: str, timesheet_id: str, **kwargs: Any) -> Any: ...
    def revert_timesheet(self, xero_tenant_id: str, timesheet_id: str, **kwargs: Any) -> Any: ...
    def create_pay_run(
        self, xero_tenant_id: str, pay_run: PayRun, **kwargs: Any
    ) -> PayRunObject: ...
    def get_employee_leaves(
        self, xero_tenant_id: str, employee_id: str, **kwargs: Any
    ) -> EmployeeLeaves: ...
    def create_employee_leave(
        self, xero_tenant_id: str, employee_id: str, employee_leave: EmployeeLeave, **kwargs: Any
    ) -> EmployeeLeaveObject: ...
    def update_employee_leave(
        self,
        xero_tenant_id: str,
        employee_id: str,
        leave_id: str,
        employee_leave: EmployeeLeave,
        **kwargs: Any,
    ) -> EmployeeLeaveObject: ...
    def delete_employee_leave(
        self, xero_tenant_id: str, employee_id: str, leave_id: str, **kwargs: Any
    ) -> Any: ...
