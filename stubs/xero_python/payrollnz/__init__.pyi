from datetime import date
from enum import Enum
from typing import Any

from xero_python.api_client import ApiClient

class PayRun:
    pay_run_id: str | None
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

class PayrollNzApi:
    def __init__(self, api_client: ApiClient) -> None: ...
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
