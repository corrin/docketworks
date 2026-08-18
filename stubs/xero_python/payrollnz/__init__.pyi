from datetime import date, datetime
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

class EarningsLine:
    earnings_rate_id: str | None
    number_of_units: float | None
    def __init__(self, **kwargs: Any) -> None: ...

class PaySlip:
    pay_slip_id: str | None
    employee_id: str | None
    pay_run_id: str | None
    first_name: str | None
    last_name: str | None
    gross_earnings: float | None
    # Xero splits its own computed earnings by the API the hours arrived
    # through, which is what makes a pay slip an independent check on the
    # uses_leave_api routing rather than a second reading of our own write.
    timesheet_earnings_lines: list[EarningsLine] | None
    leave_earnings_lines: list[EarningsLine] | None
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

class Address:
    address_line1: str | None
    address_line2: str | None
    city: str | None
    suburb: str | None
    country_name: str | None
    post_code: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class Employee:
    employee_id: str | None
    first_name: str | None
    last_name: str | None
    email: str | None
    job_title: str | None
    gender: str | None
    # Nullable only because payroll_employees._sdk_null_tolerance relaxes the SDK's
    # setter: Xero's demo organisation ships contractors without one.
    date_of_birth: date | None
    start_date: date | datetime | None
    end_date: date | datetime | None
    updated_date_utc: datetime | None
    def __init__(self, **kwargs: Any) -> None: ...

class Pagination:
    page: int | None
    page_size: int | None
    page_count: int | None
    item_count: int | None
    def __init__(self, **kwargs: Any) -> None: ...

class Employees:
    employees: list[Employee] | None
    pagination: Pagination | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeObject:
    employee: Employee | None
    def __init__(self, **kwargs: Any) -> None: ...

class Employment:
    payroll_calendar_id: str | None
    start_date: date | None
    # Nullable only because payroll_employees._sdk_null_tolerance relaxes the SDK's
    # setter: the demo organisation rejects one on create.
    engagement_type: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class SalaryAndWage:
    salary_and_wages_id: str | None
    earnings_rate_id: str | None
    rate_per_unit: float | None
    effective_from: date | None
    payment_type: str | None
    # Both nullable only because payroll_employees._sdk_null_tolerance relaxes the
    # SDK's setters: an hourly employee has neither.
    status: str | None
    annual_salary: float | None
    number_of_units_per_week: float | None
    number_of_units_per_day: float | None
    days_per_week: float | None
    def __init__(self, **kwargs: Any) -> None: ...

class SalaryAndWages:
    pagination: Pagination | None
    salary_and_wages: list[SalaryAndWage] | None
    def __init__(self, **kwargs: Any) -> None: ...

class WorkingWeek:
    monday: float | None
    tuesday: float | None
    wednesday: float | None
    thursday: float | None
    friday: float | None
    saturday: float | None
    sunday: float | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeWorkingPatternWithWorkingWeeksRequest:
    effective_from: date | None
    working_weeks: list[WorkingWeek] | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeWorkingPattern:
    payee_working_pattern_id: str | None
    effective_from: date | None

class EmployeeWorkingPatternWithWorkingWeeks:
    payee_working_pattern_id: str | None
    effective_from: date | None
    working_weeks: list[WorkingWeek] | None

class EmployeeWorkingPatternsObject:
    payee_working_patterns: list[EmployeeWorkingPattern] | None

class EmployeeWorkingPatternWithWorkingWeeksObject:
    payee_working_pattern: EmployeeWorkingPatternWithWorkingWeeks | None

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

class EmployeeLeaveType:
    leave_type_id: str | None
    schedule_of_accrual: str | None
    opening_balance: float | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeLeaveTypes:
    leave_types: list[EmployeeLeaveType] | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeLeaveTypeObject:
    leave_type: EmployeeLeaveType | None
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

class EmployeeLeaveBalance:
    leave_type_id: str | None
    name: str | None
    balance: float | None
    type_of_units: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeLeaveBalances:
    leave_balances: list[EmployeeLeaveBalance] | None
    def __init__(self, **kwargs: Any) -> None: ...

class EmployeeLeaveObject:
    leave: EmployeeLeave | None
    def __init__(self, **kwargs: Any) -> None: ...

class PayrollNzApi:
    def __init__(self, api_client: ApiClient) -> None: ...
    def get_employees(self, xero_tenant_id: str, **kwargs: Any) -> Employees: ...
    def get_employee(
        self, xero_tenant_id: str, employee_id: str, **kwargs: Any
    ) -> EmployeeObject: ...
    def create_employee(
        self, xero_tenant_id: str, employee: Employee, **kwargs: Any
    ) -> EmployeeObject: ...
    def update_employee(
        self, xero_tenant_id: str, employee_id: str, employee: Employee, **kwargs: Any
    ) -> EmployeeObject: ...
    def create_employment(
        self, xero_tenant_id: str, employee_id: str, employment: Employment, **kwargs: Any
    ) -> Any: ...
    def create_employee_salary_and_wage(
        self, xero_tenant_id: str, employee_id: str, salary_and_wage: SalaryAndWage, **kwargs: Any
    ) -> Any: ...
    def get_employee_salary_and_wages(
        self, xero_tenant_id: str, employee_id: str, **kwargs: Any
    ) -> SalaryAndWages: ...
    def create_employee_working_pattern(
        self,
        xero_tenant_id: str,
        employee_id: str,
        employee_working_pattern_with_working_weeks_request: (
            EmployeeWorkingPatternWithWorkingWeeksRequest
        ),
        **kwargs: Any,
    ) -> Any: ...
    def get_employee_working_patterns(
        self, xero_tenant_id: str, employee_id: str, **kwargs: Any
    ) -> EmployeeWorkingPatternsObject: ...
    def get_employee_working_pattern(
        self, xero_tenant_id: str, employee_id: str, employee_working_pattern_id: str, **kwargs: Any
    ) -> EmployeeWorkingPatternWithWorkingWeeksObject: ...
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
    def get_employee_leave_types(
        self, xero_tenant_id: str, employee_id: str, **kwargs: Any
    ) -> EmployeeLeaveTypes: ...
    def get_employee_leave_balances(
        self, xero_tenant_id: str, employee_id: str, **kwargs: Any
    ) -> EmployeeLeaveBalances: ...
    def create_employee_leave_type(
        self,
        xero_tenant_id: str,
        employee_id: str,
        employee_leave_type: EmployeeLeaveType,
        **kwargs: Any,
    ) -> EmployeeLeaveTypeObject: ...
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
    def get_timesheet(
        self, xero_tenant_id: str, timesheet_id: str, **kwargs: Any
    ) -> TimesheetObject: ...
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
