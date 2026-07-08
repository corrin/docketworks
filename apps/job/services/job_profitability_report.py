"""Service for job profitability reporting."""

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from apps.job.models import Job
from apps.job.services.job_service import get_job_total_value
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)

_ZERO = Decimal("0.00")
_EMPTY_SUMMARY = {"cost": 0.0, "rev": 0.0, "hours": 0.0}


def _safe_decimal(value: Any) -> Decimal:
    """Convert a JSON float to Decimal safely."""
    if value is None:
        return _ZERO
    return Decimal(str(value))


class JobProfitabilityReportService:
    """Generate profitability reports for completed/archived jobs."""

    def __init__(
        self,
        start_date: date,
        end_date: date,
        min_value: Optional[Decimal] = None,
        max_value: Optional[Decimal] = None,
        pricing_type: Optional[str] = None,
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.min_value = min_value
        self.max_value = max_value
        self.pricing_type = pricing_type

    def generate_report(self) -> Dict[str, Any]:
        """Generate the profitability report."""
        jobs_qs = self._get_queryset()
        job_rows = self._build_job_rows(jobs_qs)
        summary = self._build_summary(job_rows)

        return {
            "jobs": job_rows,
            "summary": summary,
            "filters_applied": {
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "min_value": (
                    str(self.min_value) if self.min_value is not None else None
                ),
                "max_value": (
                    str(self.max_value) if self.max_value is not None else None
                ),
                "pricing_type": self.pricing_type,
            },
        }

    def _get_queryset(self):
        """Build the base queryset for completed/archived jobs."""
        qs = Job.objects.filter(
            status__in=["recently_completed", "archived"],
            rejected_flag=False,
            completed_at__date__range=(self.start_date, self.end_date),
        )

        shop_company_id = CompanyDefaults.get_solo().shop_company_id
        qs = qs.exclude(company_id=shop_company_id)

        if self.pricing_type:
            qs = qs.filter(pricing_methodology=self.pricing_type)

        return qs.select_related(
            "company", "latest_estimate", "latest_quote", "latest_actual"
        )

    def _build_job_rows(self, jobs_qs) -> List[Dict[str, Any]]:
        """Build per-job profitability rows, applying value filters in Python."""
        rows: List[Dict[str, Any]] = []

        for job in jobs_qs:
            revenue = get_job_total_value(job).quantize(Decimal("0.01"))

            if self.min_value is not None and revenue < self.min_value:
                continue
            if self.max_value is not None and revenue > self.max_value:
                continue

            row = self._compute_job_row(job, revenue)
            rows.append(row)

        return rows

    @staticmethod
    def _extract_metrics(summary: dict) -> Dict[str, Decimal]:
        """Extract rev/cost/profit/margin/hours from a CostSet summary dict."""
        rev = _safe_decimal(summary.get("rev", 0))
        cost = _safe_decimal(summary.get("cost", 0))
        profit = rev - cost
        margin = ((profit / rev * 100) if rev != 0 else _ZERO).quantize(Decimal("0.01"))
        hours = _safe_decimal(summary.get("hours", 0))
        return {
            "revenue": rev.quantize(Decimal("0.01")),
            "cost": cost.quantize(Decimal("0.01")),
            "profit": profit.quantize(Decimal("0.01")),
            "margin": margin,
            "hours": hours.quantize(Decimal("0.01")),
        }

    @staticmethod
    def _metrics_to_str(m: Dict[str, Decimal]) -> Dict[str, str]:
        return {k: str(v) for k, v in m.items()}

    def _compute_job_row(self, job: Job, revenue: Decimal) -> Dict[str, Any]:
        """Compute profitability metrics for a single job."""
        est_summary = (
            job.latest_estimate.summary
            if job.latest_estimate and job.latest_estimate.summary
            else _EMPTY_SUMMARY
        )
        quote_summary = (
            job.latest_quote.summary
            if job.latest_quote and job.latest_quote.summary
            else _EMPTY_SUMMARY
        )
        act_summary = (
            job.latest_actual.summary
            if job.latest_actual and job.latest_actual.summary
            else _EMPTY_SUMMARY
        )

        estimate = self._extract_metrics(est_summary)
        quote = self._extract_metrics(quote_summary)
        actual = self._extract_metrics(act_summary)

        # Override actual revenue with invoice-based revenue
        actual["revenue"] = revenue
        actual["profit"] = (revenue - actual["cost"]).quantize(Decimal("0.01"))
        actual["margin"] = (
            (actual["profit"] / revenue * 100) if revenue != 0 else _ZERO
        ).quantize(Decimal("0.01"))

        # Variance is against the relevant baseline: quote for FP, estimate for T&M
        if job.pricing_methodology == "fixed_price":
            baseline_profit = quote["profit"]
        else:
            baseline_profit = estimate["profit"]

        profit_variance = actual["profit"] - baseline_profit
        profit_variance_pct = (
            (profit_variance / abs(baseline_profit) * 100)
            if baseline_profit != 0
            else _ZERO
        ).quantize(Decimal("0.01"))

        return {
            "job_id": str(job.id),
            "job_number": job.job_number,
            "job_name": job.description or "",
            "company_name": job.company.name if job.company else "Unknown",
            "pricing_type": job.pricing_methodology,
            "pricing_type_display": job.get_pricing_methodology_display(),
            "completion_date": (
                job.completed_at.date().isoformat() if job.completed_at else None
            ),
            "revenue": str(revenue),
            "estimate": self._metrics_to_str(estimate),
            "quote": self._metrics_to_str(quote),
            "actual": self._metrics_to_str(actual),
            "profit_variance": str(profit_variance.quantize(Decimal("0.01"))),
            "profit_variance_pct": str(profit_variance_pct),
        }

    def _build_summary(self, job_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate summary statistics across all job rows."""
        total_jobs = len(job_rows)
        if total_jobs == 0:
            return {
                "total_jobs": 0,
                "total_revenue": "0.00",
                "total_cost": "0.00",
                "total_profit": "0.00",
                "overall_margin": "0.00",
                "avg_profit_per_job": "0.00",
                "total_baseline_profit": "0.00",
                "total_variance": "0.00",
                "tm_jobs": 0,
                "fp_jobs": 0,
                "profitable_jobs": 0,
                "unprofitable_jobs": 0,
            }

        total_revenue = sum(Decimal(r["revenue"]) for r in job_rows)
        total_cost = sum(Decimal(r["actual"]["cost"]) for r in job_rows)
        total_profit = total_revenue - total_cost
        overall_margin = (
            (total_profit / total_revenue * 100) if total_revenue != 0 else _ZERO
        ).quantize(Decimal("0.01"))
        avg_profit = (total_profit / total_jobs).quantize(Decimal("0.01"))

        # Variance uses quote profit for FP, estimate profit for T&M
        total_baseline_profit = sum(
            (
                Decimal(r["quote"]["profit"])
                if r["pricing_type"] == "fixed_price"
                else Decimal(r["estimate"]["profit"])
            )
            for r in job_rows
        )
        total_variance = total_profit - total_baseline_profit

        tm_jobs = sum(1 for r in job_rows if r["pricing_type"] == "time_materials")
        fp_jobs = sum(1 for r in job_rows if r["pricing_type"] == "fixed_price")
        profitable = sum(1 for r in job_rows if Decimal(r["actual"]["profit"]) > 0)
        unprofitable = total_jobs - profitable

        return {
            "total_jobs": total_jobs,
            "total_revenue": str(total_revenue.quantize(Decimal("0.01"))),
            "total_cost": str(total_cost.quantize(Decimal("0.01"))),
            "total_profit": str(total_profit.quantize(Decimal("0.01"))),
            "overall_margin": str(overall_margin),
            "avg_profit_per_job": str(avg_profit),
            "total_baseline_profit": str(
                total_baseline_profit.quantize(Decimal("0.01"))
            ),
            "total_variance": str(total_variance.quantize(Decimal("0.01"))),
            "tm_jobs": tm_jobs,
            "fp_jobs": fp_jobs,
            "profitable_jobs": profitable,
            "unprofitable_jobs": unprofitable,
        }
