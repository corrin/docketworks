import logging
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.accounting.models import Invoice
from apps.job.models import CostLine, Job
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)

# Statuses excluded from WIP entirely — no real work should exist
NO_WORK_STATUSES = ["draft", "awaiting_approval"]

# Archived jobs are excluded from WIP but reported separately
ARCHIVED_STATUS = "archived"

# Invoice statuses that count as "real" invoices
VALID_INVOICE_STATUSES = ["DRAFT", "SUBMITTED", "AUTHORISED", "PAID"]


def _persist_and_raise(exception: Exception, **context: Any) -> None:
    """Persist an exception and re-raise as AlreadyLoggedException."""
    app_error = persist_app_error(exception, **context)
    raise AlreadyLoggedException(exception, app_error.id)


class WIPService:
    """
    Calculates Work In Progress as at a given date.

    WIP is the value of work performed on jobs that have not yet been fully
    invoiced.  For partially-invoiced jobs the invoiced amount is subtracted
    so the result shows only the *uninvoiced* WIP.

    Two valuation methods:
      revenue – charge-out value (quantity × unit_rev)
      cost    – internal cost (quantity × unit_cost)
    """

    @staticmethod
    def get_wip_data(report_date: date, method: str) -> dict[str, Any]:
        """
        Main entry point.

        Returns dict with:
          jobs           – active WIP rows sorted by net_wip descending
          archived_jobs  – excluded archived rows (data-quality warning)
          summary        – totals and breakdown by status
          report_date    – the date used
          method         – the valuation method used
        """
        logger.info("Generating WIP report: date=%s, method=%s", report_date, method)

        # Use end-of-day for history lookup so the full report_date is included
        report_datetime = timezone.make_aware(datetime.combine(report_date, time.max))

        try:
            # Bulk-fetch the historical state of every job as of report_date.
            # DISTINCT ON (id) + ORDER BY -history_date gives us the latest
            # history row per job in a single query.
            HistoricalJob = Job.history.model  # noqa: N806
            historical_qs = (
                HistoricalJob.objects.filter(history_date__lte=report_datetime)
                .order_by("id", "-history_date")
                .distinct("id")
            )
            # Build lookup: job_id -> historical status
            job_historical_status: dict[Any, str] = {}
            for rec in historical_qs:
                if rec.status in NO_WORK_STATUSES:
                    continue
                if rec.fully_invoiced:
                    continue
                if rec.rejected_flag:
                    continue
                job_historical_status[rec.id] = rec.status

            # Now fetch the actual Job objects only for qualifying jobs
            base_qs = (
                Job.objects.filter(
                    id__in=job_historical_status.keys(),
                )
                .exclude(latest_actual__isnull=True)
                .select_related("latest_actual", "client")
                .order_by("job_number")
            )
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            _persist_and_raise(
                exc,
                additional_context={
                    "operation": "wip_fetch_jobs",
                    "report_date": str(report_date),
                    "method": method,
                },
            )

        wip_jobs: list[dict[str, Any]] = []
        archived_jobs: list[dict[str, Any]] = []

        for job in base_qs:
            try:
                historical_status = job_historical_status[job.id]

                row = WIPService._aggregate_job(
                    job, report_date, method, historical_status
                )
                if row is None:
                    continue

                if historical_status == ARCHIVED_STATUS:
                    archived_jobs.append(row)
                else:
                    wip_jobs.append(row)
            except Exception as exc:
                logger.error("Error processing job %s for WIP: %s", job.job_number, exc)
                persist_app_error(
                    exc,
                    job_id=job.id,
                    additional_context={
                        "operation": "wip_aggregate_job",
                        "job_number": job.job_number,
                        "report_date": str(report_date),
                        "method": method,
                    },
                )
                # Continue processing other jobs

        wip_jobs.sort(key=lambda r: r["net_wip"], reverse=True)
        archived_jobs.sort(key=lambda r: r["net_wip"], reverse=True)

        summary = WIPService._build_summary(wip_jobs)

        return {
            "jobs": wip_jobs,
            "archived_jobs": archived_jobs,
            "summary": summary,
            "report_date": str(report_date),
            "method": method,
        }

    @staticmethod
    def _aggregate_job(
        job: Job, report_date: date, method: str, historical_status: str
    ) -> dict[str, Any] | None:
        """Build a WIP row for a single job, or None if zero revenue activity."""
        cost_lines = CostLine.objects.filter(
            cost_set=job.latest_actual,
            accounting_date__lte=report_date,
        )

        totals = cost_lines.aggregate(
            total_cost=Sum(F("quantity") * F("unit_cost")),
            total_rev=Sum(F("quantity") * F("unit_rev")),
            time_cost=Sum(F("quantity") * F("unit_cost"), filter=Q(kind="time")),
            time_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="time")),
            material_cost=Sum(
                F("quantity") * F("unit_cost"), filter=Q(kind="material")
            ),
            material_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="material")),
            adjust_cost=Sum(F("quantity") * F("unit_cost"), filter=Q(kind="adjust")),
            adjust_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="adjust")),
        )

        total_cost = totals["total_cost"] or Decimal("0")
        total_rev = totals["total_rev"] or Decimal("0")

        if total_rev == 0:
            return None

        invoiced = Invoice.objects.filter(
            job=job,
            status__in=VALID_INVOICE_STATUSES,
            date__lte=report_date,
        ).aggregate(total=Sum("total_excl_tax"))["total"] or Decimal("0")

        gross_wip = total_rev if method == "revenue" else total_cost
        net_wip = gross_wip - invoiced

        return {
            "job_number": job.job_number,
            "name": job.name,
            "client": str(job.client) if job.client else "N/A",
            "status": historical_status,
            "time_cost": float(totals["time_cost"] or Decimal("0")),
            "time_rev": float(totals["time_rev"] or Decimal("0")),
            "material_cost": float(totals["material_cost"] or Decimal("0")),
            "material_rev": float(totals["material_rev"] or Decimal("0")),
            "adjust_cost": float(totals["adjust_cost"] or Decimal("0")),
            "adjust_rev": float(totals["adjust_rev"] or Decimal("0")),
            "total_cost": float(total_cost),
            "total_rev": float(total_rev),
            "invoiced": float(invoiced),
            "gross_wip": float(gross_wip),
            "net_wip": float(net_wip),
        }

    @staticmethod
    def _build_summary(wip_jobs: list[dict[str, Any]]) -> dict[str, Any]:
        """Build summary totals and breakdown by status."""
        total_gross = 0.0
        total_invoiced = 0.0
        total_net = 0.0
        by_status: dict[str, dict[str, float]] = {}

        for row in wip_jobs:
            total_gross += row["gross_wip"]
            total_invoiced += row["invoiced"]
            total_net += row["net_wip"]

            s = row["status"]
            if s not in by_status:
                by_status[s] = {"count": 0, "net_wip": 0.0}
            by_status[s]["count"] += 1
            by_status[s]["net_wip"] += row["net_wip"]

        status_breakdown = sorted(
            [
                {"status": k, "count": int(v["count"]), "net_wip": v["net_wip"]}
                for k, v in by_status.items()
            ],
            key=lambda x: x["net_wip"],
            reverse=True,
        )

        return {
            "job_count": len(wip_jobs),
            "total_gross": total_gross,
            "total_invoiced": total_invoiced,
            "total_net": total_net,
            "by_status": status_breakdown,
        }
