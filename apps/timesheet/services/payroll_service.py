"""Xero Payroll pay-run surface behind ``/api/timesheets/payroll/...``.

Everything that talks to Xero remains an explicit Phase 4 seam and raises
``NotImplementedError`` with a clear message. Reads from the local
``XeroPayRun`` mirror and ``CompanyDefaults`` are implemented:

- ``list_pay_runs`` — real, except the "no pay runs on this calendar yet"
  branch of the postable-week rule, which needs Xero's calendar anchor.
- ``create_pay_run`` / ``refresh_pay_runs`` — seams (Xero writes/sync).
- ``start_post_week_task`` validates and caches a task id; the SSE stream that
  performs posting remains a Phase 4 seam.

Layer contract: ``XeroPayRun`` lives in ``apps.xero``, above the domain apps,
so it is reached through Django's app registry behind a protocol — the pattern
``apps/core/models.py`` uses for ``_WageBearingStaff``.
"""

import logging
import uuid as uuid_module
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Protocol, TypedDict, cast
from uuid import UUID

from django.core.cache import cache

from apps.core.models import CompanyDefaults
from apps.core.xero_registry import xero_model_manager

logger = logging.getLogger(__name__)

# Keep posting task state long enough for the client to connect to its stream.
PAYROLL_TASK_TIMEOUT = 600
PAYROLL_TASK_CACHE_PREFIX = "payroll_task_"
PHASE_4 = (
    "Xero Payroll integration is not ported yet (Phase 4); "
    "no pay-run data was read from or written to Xero."
)


class PayRunRow(Protocol):
    """Structural view of ``xero.XeroPayRun`` used by the pay-run list."""

    @property
    def id(self) -> UUID:
        """The mirror row's primary key."""

    @property
    def xero_id(self) -> UUID:
        """Xero's id for the pay run."""

    @property
    def period_start_date(self) -> date:
        """First day of the pay period."""

    @property
    def period_end_date(self) -> date:
        """Last day of the pay period."""

    @property
    def payment_date(self) -> date:
        """The date staff are paid."""

    @property
    def pay_run_status(self) -> str:
        """Xero's pay-run status (Draft, Posted, ...)."""


class _PayRunQuery(Protocol):
    """The queryset surface the pay-run list needs (ordering + iteration)."""

    def order_by(self, *fields: str) -> "_PayRunQuery":
        """Return the rows re-ordered by the given fields."""

    def first(self) -> PayRunRow | None:
        """Return the first row, or None when empty."""

    def __iter__(self) -> Iterator[PayRunRow]:
        """Iterate the matched rows."""


class _PayRunMirror(Protocol):
    """The manager surface the pay-run list needs off the XeroPayRun model."""

    def filter(self, **kwargs: object) -> _PayRunQuery:
        """Return the mirror rows matching the given lookups."""


def _pay_run_mirror() -> _PayRunMirror:
    """Narrow the shared xero-registry seam to this module's protocol."""
    return cast("_PayRunMirror", xero_model_manager("XeroPayRun"))


class PayRunData(TypedDict):
    """Data contract for PayRunData."""

    id: UUID
    xero_id: UUID
    period_start_date: date
    period_end_date: date
    payment_date: date
    pay_run_status: str
    xero_url: str


class PayRunListData(TypedDict):
    """Data contract for PayRunListData."""

    pay_runs: list[PayRunData]
    next_postable_week_start_date: date | None
    next_postable_week_end_date: date | None


class PayRunSyncData(TypedDict):
    """Data contract for PayRunSyncData."""

    synced: bool
    fetched: int
    created: int
    updated: int


class CreatedPayRunData(TypedDict):
    """Data contract for CreatedPayRunData."""

    id: UUID
    xero_id: UUID
    status: str
    period_start_date: date
    period_end_date: date
    payment_date: date
    xero_url: str


class PostWeekStartData(TypedDict):
    """Data contract for PostWeekStartData."""

    task_id: UUID
    stream_url: str


class PayrollTaskData(TypedDict):
    """The cached payload the SSE stream endpoint consumes."""

    staff_ids: list[str]
    week_start_date: str
    status: str


def build_xero_payroll_url(pay_run_xero_id: UUID) -> str:
    """Deep link to a pay run in Xero (v1 ``apps/workflow/utils.py``).

    Pure string building from the configured shortcode — no Xero call — so it
    ports now rather than waiting for Phase 4.
    """
    shortcode = CompanyDefaults.get_solo().xero_shortcode
    if not shortcode:
        raise ValueError(
            "Xero shortcode not configured. Run 'python manage.py xero --setup' to fetch it."
        )
    return f"https://payroll.xero.com/PayRun?CID={shortcode}#payruns/{pay_run_xero_id}"


def get_payroll_calendar_id() -> UUID:
    """Read the configured payroll calendar id."""
    calendar_id = CompanyDefaults.get_solo().xero_payroll_calendar_id
    if not calendar_id:
        raise ValueError(
            "xero_payroll_calendar_id not configured in CompanyDefaults. "
            "Run: python manage.py xero --setup"
        )
    return calendar_id


def next_postable_payroll_week(calendar_id: UUID) -> tuple[date, date] | None:
    """Compute the only week that can currently be posted to the payroll calendar (v1).

    Xero processes pay runs in sequence, so it is: the open Draft pay run's
    period if there is one; otherwise the week after the latest pay run.

    v1's third case — no pay runs on the calendar at all, where the calendar's
    own anchor period applies — needs Xero's ``get_payroll_calendars``, which is
    Phase 4. It returns ``None`` rather than raising: this is a READ endpoint and
    must not die because a Xero-side capability is unported. ``None`` is already
    part of the v1 contract for this field (the schema tells the client to fall
    back to the current week), and the gap is logged and recorded in the parity
    ledger. Creating and refreshing pay runs stay loud seams.
    """
    mirror = _pay_run_mirror()
    open_draft = (
        mirror.filter(payroll_calendar_id=calendar_id, pay_run_status="Draft")
        .order_by("-period_start_date")
        .first()
    )
    if open_draft is not None:
        return open_draft.period_start_date, open_draft.period_end_date

    latest = mirror.filter(payroll_calendar_id=calendar_id).order_by("-period_end_date").first()
    if latest is not None:
        start = latest.period_end_date + timedelta(days=1)
        return start, start + timedelta(days=6)

    logger.warning(
        "Payroll calendar %s has no pay runs; the anchor week comes from the Xero "
        "calendar, which is Phase 4. Reporting no postable week.",
        calendar_id,
    )
    return None


def list_pay_runs() -> PayRunListData:
    """All pay runs on the configured calendar, newest first."""
    calendar_id = get_payroll_calendar_id()
    pay_runs = (
        _pay_run_mirror().filter(payroll_calendar_id=calendar_id).order_by("-period_end_date")
    )
    postable = next_postable_payroll_week(calendar_id)
    return {
        "pay_runs": [
            {
                "id": pay_run.id,
                "xero_id": pay_run.xero_id,
                "period_start_date": pay_run.period_start_date,
                "period_end_date": pay_run.period_end_date,
                "payment_date": pay_run.payment_date,
                "pay_run_status": pay_run.pay_run_status,
                "xero_url": build_xero_payroll_url(pay_run.xero_id),
            }
            for pay_run in pay_runs
        ],
        "next_postable_week_start_date": postable[0] if postable else None,
        "next_postable_week_end_date": postable[1] if postable else None,
    }


def create_pay_run(week_start_date: date) -> CreatedPayRunData:
    """Create a pay run in Xero and mirror it locally (v1 CreatePayRunAPIView).

    Phase 4 seam: the pay run must exist in Xero before the local mirror row
    means anything, so nothing is written locally either.
    """
    if week_start_date.weekday() != 0:
        raise ValueError("week_start_date must be a Monday")
    raise NotImplementedError(
        f"{PHASE_4} Creating the pay run for week {week_start_date.isoformat()} "
        "requires the Xero Payroll API."
    )


def refresh_pay_runs() -> PayRunSyncData:
    """Re-sync the local pay-run mirror from Xero (v1 RefreshPayRunsAPIView).

    Phase 4 seam: the whole operation is a Xero sync.
    """
    raise NotImplementedError(f"{PHASE_4} Refreshing the pay-run mirror is a Xero sync.")


def start_post_week_task(staff_ids: list[UUID], week_start_date: date) -> PostWeekStartData:
    """Register a payroll-posting task and hand back its SSE stream URL (v1).

    v1's POST did exactly this — validation plus a cache entry — and the work
    happened in the SSE stream endpoint. That stream is pure Xero Payroll
    posting and is deferred to Phase 4, so the endpoint it points at does not
    exist yet; the contract of this call is unchanged.
    """
    if not staff_ids:
        raise ValueError("staff_ids is required")
    if week_start_date.weekday() != 0:
        raise ValueError("week_start_date must be a Monday")

    task_id = uuid_module.uuid4()
    task_data: PayrollTaskData = {
        "staff_ids": [str(staff_id) for staff_id in staff_ids],
        "week_start_date": week_start_date.isoformat(),
        "status": "pending",
    }
    cache.set(f"{PAYROLL_TASK_CACHE_PREFIX}{task_id}", task_data, timeout=PAYROLL_TASK_TIMEOUT)
    logger.info(
        "Registered payroll posting task %s for %d staff, week %s",
        task_id,
        len(staff_ids),
        week_start_date,
    )
    return {
        "task_id": task_id,
        "stream_url": f"/api/timesheets/payroll/post-staff-week/stream/{task_id}/",
    }
