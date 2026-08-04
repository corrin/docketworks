"""The accounting domain's ninja router (thin translators over apps.accounting.services).

Paths and operationIds match v1's generated OpenAPI schema (frontend/schema.yml):
thirteen read-only report endpoints under ``/api/accounting/reports/``. Three of
them lived in v1's ``apps/workflow/api/reports`` (job-movement, payroll
reconciliation, profit-and-loss); they move here because the concept is an
accounting report and this app is its one home (sanctioned by the plan:
"reports move from workflow/api/ to accounting/").

Auth: every endpoint is plain ``CookieJWTAuth`` — v1 set no permission class on
any report view, so DRF's default IsAuthenticated applied; there is no office
or superuser gate on this surface.

Error bodies use the v2 envelope ``{"detail", "error_id"}``, not v1's
``StandardErrorSerializer`` ``{"error", "details"}`` shape (ledgered:
accounting-reports-wide).

Integration wiring (config/api.py): ``api.add_router("/accounting/", router)``.
"""

import datetime
from typing import Literal

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError
from ninja.errors import ValidationError as RequestValidationError

from apps.accounting.schemas import JobAgingResponse, RDTISpendResponse, WIPResponse
from apps.accounting.services import (
    job_aging_service,
    rdti_spend_service,
    wip_service,
)
from apps.core.auth import CookieJWTAuth

router = Router(tags=["accounting"], auth=CookieJWTAuth())


@router.get(
    "/reports/job-aging/",
    operation_id="accounting_reports_job_aging_retrieve",
    summary="Job aging report",
    response=JobAgingResponse,
)
def job_aging(
    request: HttpRequest, include_archived: bool = False
) -> job_aging_service.JobAgingData:
    """Every job with financial totals, timing data, and last activity."""
    return job_aging_service.get_job_aging_data(include_archived=include_archived)


@router.get(
    "/reports/wip/",
    operation_id="accounting_reports_wip_retrieve",
    summary="Work-in-progress report",
    response=WIPResponse,
)
def wip_report(
    request: HttpRequest,
    date: datetime.date | None = None,
    method: Literal["revenue", "cost"] = "revenue",
) -> wip_service.WIPData:
    """Uninvoiced WIP per job as at the given date (defaults to today)."""
    report_date = date if date is not None else timezone.localdate()
    return wip_service.get_wip_data(report_date, method)


@router.get(
    "/reports/rdti-spend/",
    operation_id="accounting_reports_rdti_spend_retrieve",
    summary="RDTI spend report",
    response=RDTISpendResponse,
)
def rdti_spend(
    request: HttpRequest, start_date: datetime.date, end_date: datetime.date
) -> rdti_spend_service.RDTISpendData:
    """Actual spend grouped by job and R&D classification for the period."""
    if start_date > end_date:
        raise RequestValidationError(errors=[{"msg": "start_date must not be after end_date."}])
    return rdti_spend_service.get_rdti_spend_data(start_date, end_date)


@router.get(
    "/reports/profit-and-loss/",
    operation_id="accounting_reports_profit_and_loss_retrieve",
    summary="Company profit and loss report",
    response={501: dict},
)
def profit_and_loss(request: HttpRequest) -> tuple[int, dict[str, str]]:
    """501 stub, exactly as v1 shipped: rebuilding against Xero is Phase 4."""
    raise HttpError(
        501,
        "Profit and Loss reporting is unavailable until it is rebuilt "
        "against the Xero Reports API.",
    )
