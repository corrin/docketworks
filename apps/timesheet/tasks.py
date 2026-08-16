"""Background work for the timesheet domain.

Posting a week to payroll runs here rather than inside the SSE stream that
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
from apps.core.errors import AppErrorContext, persist_app_error
from apps.timesheet.services import payroll_progress

logger = logging.getLogger(__name__)


@shared_task(name="apps.timesheet.tasks.post_payroll_week_task")
def post_payroll_week_task(task_id: str, staff_ids: list[str], week_start_date: str) -> None:
    """Post a week of hours to payroll, publishing progress for the stream to read.

    Every exit path publishes a terminal event. A task that died silently would
    leave the page's progress bar spinning forever with no way to tell a slow
    post from a dead one.
    """
    week = date.fromisoformat(week_start_date)
    ids = [UUID(staff_id) for staff_id in staff_ids]
    payroll_progress.publish(task_id, {"event": "start", "total": len(ids)})

    successful = failed = 0
    try:
        provider = get_provider()
        if not provider.supports_payroll:
            raise ValueError(
                f"The configured accounting backend ({provider.provider_name}) "
                "does not support payroll posting."
            )
        for index, result in enumerate(provider.post_payroll_week(ids, week), start=1):
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
    except Exception as exc:
        # The preflight refuses the whole batch (unlinked pay items, a blocking
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

    payroll_progress.publish(task_id, {"event": "done", "successful": successful, "failed": failed})
