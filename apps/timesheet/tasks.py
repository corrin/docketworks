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
from uuid import UUID

from celery import shared_task

from apps.accounting.registry import get_provider
from apps.accounting.types import PayrollMirrorScope
from apps.core.errors import AppErrorContext, persist_app_error
from apps.timesheet.services import payroll_progress

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
    task_id: str,
    connection_id: str,
    staff_ids: list[str],
    week_start_date: str,
) -> None:
    """Post a week of hours to payroll, publishing progress for the stream to read.

    Opus: Every exit path publishes a terminal event. A task that died silently would
    leave the page's progress bar spinning forever with no way to tell a slow
    post from a dead one.
    """
    week = date.fromisoformat(week_start_date)
    ids = [UUID(staff_id) for staff_id in staff_ids]

    successful = failed = 0
    try:
        # Claimed before anything is published, so a refused duplicate leaves no
        # trace in the live run's log. CELERY_TASK_ACKS_LATE is on, so a worker
        # that dies or loses the broker mid-batch has this message redelivered
        # (ADR 0024) — and a second operator click produces a second task id,
        # which no task-scoped guard would catch. Both land here.
        holder = payroll_progress.acquire_run_claim(connection_id, task_id)
        if holder is not None:
            _report_already_running(task_id, holder, len(ids))
            return

        payroll_progress.publish(task_id, {"event": "start", "total": len(ids)})
        provider = get_provider()
        if not provider.supports_payroll:
            raise ValueError(
                f"The configured accounting backend ({provider.provider_name}) "
                "does not support payroll posting."
            )
        provider.sync_payroll_mirror(connection_id, PayrollMirrorScope.BEFORE_POST)
        for index, result in enumerate(
            provider.post_payroll_week(connection_id, ids, week), start=1
        ):
            payroll_progress.renew_run_claim(connection_id, task_id)
            payroll_progress.publish(
                task_id,
                {
                    "event": "progress",
                    "staff_id": result.staff_id,
                    "staff_name": result.staff_name,
                    "current": index,
                    "total": len(ids),
                },
            )
            payroll_progress.publish(task_id, payroll_progress.completion_event(result))
            if result.success:
                successful += 1
            else:
                failed += 1
        provider.sync_payroll_mirror(connection_id, PayrollMirrorScope.AFTER_POST)
        refresh_payroll_after_settle_task.apply_async(
            args=(connection_id, week_start_date), countdown=PAYSLIP_SETTLE_DELAY_SECONDS
        )
        payroll_progress.publish(
            task_id, {"event": "done", "successful": successful, "failed": failed}
        )
    except Exception as exc:
        # Opus: The preflight refuses the whole batch (unlinked pay items, a blocking
        # draft pay run), so this is a batch-level failure, not one staff
        # member's. It is reported verbatim because the message names the fix
        # (ADR 0038) — and re-raised so the task is recorded as failed.
        #
        # Persisted as well as logged, because the log line cannot answer the
        # question asked after a failed payroll run: WHICH week and WHICH staff
        # were left unposted. Progress events expire with the cache entry, so
        # without this row the batch's scope is gone by the time anyone looks.
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "task_id": task_id,
                    "staff_ids": staff_ids,
                    "week_start_date": week_start_date,
                    "successful": successful,
                    "failed": failed,
                }
            ),
        )
        logger.exception("Payroll posting task %s failed", task_id)
        payroll_progress.publish(task_id, {"event": "error", "message": str(exc)})
        payroll_progress.publish(
            task_id,
            {"event": "done", "successful": successful, "failed": len(ids) - successful},
        )
        raise
    finally:
        # Released after the terminal event, so the claim covers everything a
        # second run could collide with. It only deletes a claim this run owns,
        # so the refused path above and a claim already expired are both no-ops.
        payroll_progress.release_run_claim(connection_id, task_id)


def _report_already_running(task_id: str, holder: str, total: int) -> None:
    """Tell the operator which run holds the calendar, and end this one quietly.

    Not an exception: a refused duplicate is the guard working, not the task
    failing, and raising would retry it against the same held claim.
    """
    logger.warning("Payroll posting task %s refused: run %s holds the calendar", task_id, holder)
    payroll_progress.publish(
        task_id,
        {
            "event": "error",
            "message": (
                f"A payroll posting run ({holder}) is already in progress. Nothing was "
                "posted. Wait for it to finish, then check what Xero holds before "
                "posting again."
            ),
        },
    )
    payroll_progress.publish(task_id, {"event": "done", "successful": 0, "failed": total})


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
