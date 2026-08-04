"""Response schemas for the accounting report surface.

Shapes mirror v1's DRF serializers (apps/accounting/serializers/) — the wire
contract, which is narrower than what the services compute (v1's serializers
silently dropped extra keys; ninja schemas do the same by omission). Fields the
v1 serializer dropped (e.g. job-aging ``price_cap``) stay dropped.
"""

from datetime import date

from ninja import Schema


class JobAgingFinancialData(Schema):
    """v1 JobAgingFinancialDataSerializer."""

    estimate_total: float
    quote_total: float
    actual_total: float


class JobAgingTimingData(Schema):
    """v1 JobAgingTimingDataSerializer."""

    created_date: date
    created_days_ago: int
    days_in_current_status: int
    # v1 declared last_activity_date a DateTimeField but the service always
    # supplied a bare date; v2 types what is actually sent.
    last_activity_date: date | None
    last_activity_days_ago: int | None
    last_activity_type: str | None
    last_activity_description: str | None


class JobAgingJobData(Schema):
    """v1 JobAgingJobDataSerializer (price_cap intentionally absent, as in v1)."""

    id: str
    job_number: int
    name: str
    company_name: str
    status: str
    status_display: str
    financial_data: JobAgingFinancialData
    timing_data: JobAgingTimingData


class JobAgingResponse(Schema):
    """v1 JobAgingResponseSerializer."""

    jobs: list[JobAgingJobData]
