"""Background work for the timesheet domain.

Opus: Posting a week to payroll runs here rather than inside the SSE stream that
reports it. v1 did the posting inside the stream's GET handler, which made
reading a URL write to payroll — the rule this repo states first is that a GET
never writes — and meant a client that disconnected mid-batch left no record of
which staff had succeeded. The task owns the work and publishes progress; the
stream only reads what the task published (ADR 0024, ADR 0047).

The Xero specifics stay behind ``get_provider()``: ``apps.xero`` sits above the
domain apps in the import contract, so this module never imports it (ADR 0012).
"""

import logging
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from celery import shared_task

from apps.accounting.registry import get_provider
from apps.accounting.types import PayrollMirrorScope
from apps.core.errors import AppErrorContext, persist_app_error
from apps.timesheet.services import payroll_runs

if TYPE_CHECKING:
    from collections.abc import Callable

    from apps.accounting.provider import AccountingProvider
    from apps.timesheet.schemas import PayrollPostRunOut

logger = logging.getLogger(__name__)

#: How long to wait before mirroring pay slips after a post.
#:
#: Xero recomputes a Draft pay run's pay slips ASYNCHRONOUSLY and exposes no
#: flag for when it has finished, so this is a measured delay rather than a
#: handshake. ADR 0007 records the measurement: a slip read 59 seconds after a
#: re-post still carried the PREVIOUS figures, and the same slip at 2m17s
#: carried the new ones. Anything shorter than that mirrors the pre-post
#: numbers and, because this fires once, leaves them there.
#:
#: The mirror is best-effort even so, and nothing may depend on it being
#: settled: a bigger pay run may take longer than any fixed delay. Certainty
#: comes from reading Xero live and polling to a deadline, which is what the
#: payroll reconciliation does — this only keeps the mirror roughly current for
#: the date-range report.
PAYSLIP_SETTLE_DELAY_SECONDS = 180


@shared_task(name="apps.timesheet.tasks.post_payroll_week_task")
def post_payroll_week_task(
    run_id: str,
    connection_id: str,
    staff_ids: list[str],
    week_start_date: str,
) -> None:
    """Post a week of hours to payroll, keeping the run document current.

    Opus: Every exit path that OWNS the claim writes a TERMINAL document —
    `succeeded` or `failed`. A task that died silently would leave the panel's
    progress bar spinning with no way to tell a slow post from a dead one, and
    the shape this replaces had a subtler version of the same fault: it
    published `error` then `done`, the stream treated `error` as terminal and
    closed before the `done` the client keys "finished" off, so a real failure
    carrying an actionable message read as "the run ended without reporting an
    outcome". One `status` field cannot disagree with itself that way.

    Fable: Every document write happens under a proven claim, terminal writes
    included — a slow batch can outlive the claim TTL, and an unguarded
    obituary would land on whichever run took the calendar over. A claim-loss
    exit goes through ``_close_run_if_owned``: an EXPIRED claim nobody took is
    re-taken so the run still closes honestly (a dangling "running" document
    disables the panel's controls for its whole TTL), while a claim another
    run holds means that run owns the connection-keyed document and this one
    writes nothing over it.
    """
    week = date.fromisoformat(week_start_date)
    ids = [UUID(staff_id) for staff_id in staff_ids]

    # Fable: Redelivery guard, in the task body as ADR 0024 asks, and BEFORE the
    # first document write, not merely before the first Xero call. The claim was
    # taken by the request handler so a duplicate click is a synchronous 409;
    # what reaches here is CELERY_TASK_ACKS_LATE redelivering a message whose
    # worker died — by which time another run may hold the calendar.
    try:
        payroll_runs.renew_run_claim(connection_id, run_id)
    except payroll_runs.PayrollRunClaimLostError as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={"run_id": run_id, "week_start_date": week_start_date}
            ),
        )
        logger.exception("Refused stale payroll posting run %s before it wrote anything", run_id)
        _close_run_if_owned(
            connection_id,
            run_id,
            lambda: payroll_runs.finished(
                payroll_runs.running(connection_id, run_id, week, total=len(ids)),
                "failed",
                message=(
                    "This posting run was queued for too long and never started. "
                    "Nothing was posted. Post again."
                ),
            ),
        )
        payroll_runs.release_run_claim(connection_id, run_id)
        raise

    run = payroll_runs.running(connection_id, run_id, week, total=len(ids))
    successful = failed = 0
    try:
        provider = get_provider()
        if not provider.supports_payroll:
            raise ValueError(
                f"The configured accounting backend ({provider.provider_name}) "
                "does not support payroll posting."
            )
        for index, result in enumerate(
            provider.post_payroll_week(connection_id, ids, week), start=1
        ):
            payroll_runs.renew_run_claim(connection_id, run_id)
            if result.success:
                successful += 1
            else:
                failed += 1
            run = payroll_runs.with_result(
                run, result, completed=index, successful=successful, failed=failed
            )
            payroll_runs.write(connection_id, run)
        # Fable: The outcome is decided by the POSTING loop alone, and written
        # before the mirror refresh — a run whose every staff member posted
        # must not be reported "failed" because a best-effort follow-up
        # tripped.
        final_run = run
        _close_run_if_owned(
            connection_id, run_id, lambda: payroll_runs.finished(final_run, "succeeded")
        )
        _after_post_mirror_refresh(provider, connection_id, run_id, week_start_date)
    except payroll_runs.PayrollRunClaimLostError as exc:
        # Fable: Claim lost MID-run: the TTL expired without renewal (a hung
        # provider call). Close with the results that completed — or write
        # nothing if another run owns the panel now.
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "run_id": run_id,
                    "week_start_date": week_start_date,
                    "successful": successful,
                    "failed": failed,
                }
            ),
        )
        logger.exception("Payroll posting task %s lost its claim mid-run", run_id)
        lost_run = run
        _close_run_if_owned(
            connection_id,
            run_id,
            lambda: payroll_runs.finished(
                lost_run,
                "failed",
                message=(
                    "The posting run lost its claim mid-run; the results above are "
                    'what completed. Use "Check against Xero" before posting again.'
                ),
            ),
        )
        raise
    except Exception as exc:
        # Opus: The preflight refuses the whole batch (unlinked pay items, a blocking
        # draft pay run), so this is a batch-level failure, not one staff
        # member's. The message is carried verbatim because it names the fix
        # (ADR 0038) — "delete the draft pay run for 2026-07-13, then post again"
        # is the whole of what an operator needs, and it is the sentence that
        # used to be published and never delivered.
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "run_id": run_id,
                    "week_start_date": week_start_date,
                    "staff_ids": staff_ids,
                    "successful": successful,
                    "failed": failed,
                }
            ),
        )
        logger.exception("Payroll posting task %s failed", run_id)
        failed_run, cause = run, exc
        _close_run_if_owned(
            connection_id,
            run_id,
            lambda: payroll_runs.finished(failed_run, "failed", message=str(cause)),
        )
        raise
    finally:
        # Opus: Released after the terminal document, so the claim covers everything
        # a second run could collide with. It only deletes a claim this run owns,
        # so an already-expired claim is a no-op.
        payroll_runs.release_run_claim(connection_id, run_id)


def _close_run_if_owned(
    connection_id: str, run_id: str, build_document: "Callable[[], PayrollPostRunOut]"
) -> None:
    """Write a terminal document only under a proven (or safely re-taken) claim.

    Fable: The document is keyed by connection. ``reclaim_or_refuse`` renews a
    live claim, re-takes an expired one nobody claimed (so the run can still
    close instead of leaving a dangling "running" bar), and answers False when
    another run holds it — in which case that run owns the panel and nothing
    is written. The document is built lazily so the refused case constructs
    (and publishes) nothing.
    """
    if payroll_runs.reclaim_or_refuse(connection_id, run_id):
        payroll_runs.write(connection_id, build_document())
    else:
        logger.warning(
            "Payroll run %s no longer holds the posting claim; not writing its "
            "outcome over the live run's document.",
            run_id,
        )


def _after_post_mirror_refresh(
    provider: "AccountingProvider", connection_id: str, run_id: str, week_start_date: str
) -> None:
    """Best-effort follow-ups after a successful post: mirror now, slips later.

    Fable: Failures here persist as AppErrors and never become the run's
    outcome — the posting already succeeded, and the mirror converges on the
    next hourly sync anyway.
    """
    try:
        provider.sync_payroll_mirror(connection_id, PayrollMirrorScope.AFTER_POST)
        refresh_payroll_after_settle_task.apply_async(
            args=(connection_id, week_start_date), countdown=PAYSLIP_SETTLE_DELAY_SECONDS
        )
    except Exception as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "run_id": run_id,
                    "week_start_date": week_start_date,
                    "stage": "after_post_mirror_refresh",
                }
            ),
        )
        logger.exception("After-post mirror refresh failed for payroll run %s", run_id)


@shared_task(name="apps.timesheet.tasks.refresh_payroll_after_settle_task")
def refresh_payroll_after_settle_task(connection_id: str, week_start_date: str) -> None:
    """Run one best-effort mirror refresh after Xero has had time to recalculate."""
    try:
        get_provider().sync_payroll_mirror(connection_id, PayrollMirrorScope.AFTER_SETTLE)
    except Exception as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "operation": "refresh_payroll_after_settle",
                    "connection_id": connection_id,
                    "week_start_date": week_start_date,
                }
            ),
        )
        raise
