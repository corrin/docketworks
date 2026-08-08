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
    # Not an SDK field: the sync fetcher attaches the parent pay run so the
    # transform can reach it without a second API call.
    _pay_run: PayRun
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

class PayrollNzApi:
    def __init__(self, api_client: ApiClient) -> None: ...
    def get_pay_runs(self, xero_tenant_id: str, **kwargs: Any) -> PayRuns: ...
    def get_pay_slips(self, xero_tenant_id: str, pay_run_id: str, **kwargs: Any) -> PaySlips: ...
    def get_leave_types(self, xero_tenant_id: str, **kwargs: Any) -> LeaveTypes: ...
    def get_earnings_rates(self, xero_tenant_id: str, **kwargs: Any) -> EarningsRates: ...
