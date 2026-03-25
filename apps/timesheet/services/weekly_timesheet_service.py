"""
Weekly Timesheet Service

Service layer for handling weekly timesheet business logic including:
- Weekly data aggregation
- Payroll export functionality
- Staff summary calculations
- Job metrics

Refactored to use CostSet/CostLine system only
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List

from django.db.models.fields.json import KeyTextTransform

from apps.accounts.models import Staff
from apps.accounts.utils import get_displayable_staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)


class WeeklyTimesheetService:
    """Service for weekly timesheet operations (Monday to Sunday)."""

    @classmethod
    def get_weekly_overview(cls, start_date: date) -> Dict[str, Any]:
        """
        Get comprehensive weekly timesheet overview with payroll data.

        Args:
            start_date: Monday of the target week

        Returns:
            Dict containing weekly overview data with payroll fields
        """
        try:
            # Calculate week range
            week_days = cls._get_week_days(start_date)
            end_date = start_date + timedelta(days=6)

            # Get staff data
            staff_data = cls._get_staff_data(week_days)

            # Get weekly totals
            weekly_totals = cls._calculate_weekly_totals(staff_data)

            # Get job metrics
            job_metrics = cls._get_job_metrics(start_date, end_date)

            # Get summary stats
            summary_stats = cls._calculate_summary_stats(staff_data)

            return {
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "week_days": [day.strftime("%Y-%m-%d") for day in week_days],
                "staff_data": staff_data,
                "weekly_summary": weekly_totals,
                "job_metrics": job_metrics,
                "summary_stats": summary_stats,
                "export_mode": "payroll",
                "is_current_week": cls._is_current_week(start_date),
            }

        except Exception as e:
            logger.error(f"Error getting weekly overview: {e}")
            raise

    @classmethod
    def _get_week_days(cls, start_date: date) -> List[date]:
        """Get list of days for the week (Monday to Sunday)."""
        return [start_date + timedelta(days=i) for i in range(7)]

    @classmethod
    def _get_staff_data(cls, week_days: List[date]) -> List[Dict[str, Any]]:
        """Get comprehensive staff data for the week with payroll fields.

        Optimized to bulk-fetch all CostLines for the week in ONE query,
        then process in Python. This reduces ~100 queries to 1-2.
        """
        staff_members = list(
            get_displayable_staff(date_range=(week_days[0], week_days[-1]))
        )

        # Get annual leave loading multiplier for base cost calculation
        loading = CompanyDefaults.get_solo().annual_leave_loading
        loading_multiplier = Decimal("1") + loading / Decimal("100")

        # ONE query for ALL time entries for ALL staff for the entire week
        all_cost_lines = list(
            CostLine.objects.annotate(
                staff_id_meta=KeyTextTransform("staff_id", "meta"),
                wage_rate_multiplier=KeyTextTransform("wage_rate_multiplier", "meta"),
                is_billable=KeyTextTransform("is_billable", "meta"),
            )
            .filter(
                cost_set__kind="actual",
                kind="time",
                accounting_date__gte=week_days[0],
                accounting_date__lte=week_days[-1],
            )
            .select_related("cost_set__job", "cost_set__job__default_xero_pay_item")
        )

        # Group by staff_id and day
        lines_by_staff_day = {}
        for line in all_cost_lines:
            key = (line.staff_id_meta, line.accounting_date)
            if key not in lines_by_staff_day:
                lines_by_staff_day[key] = []
            lines_by_staff_day[key].append(line)

        staff_data = []
        for staff_member in staff_members:
            staff_id = str(staff_member.id)
            weekly_hours = []
            total_hours = 0
            total_billable_hours = 0
            total_scheduled_hours = 0
            total_billed_hours = 0
            total_unbilled_hours = 0
            total_overtime_1_5x_hours = 0
            total_overtime_2x_hours = 0
            total_sick_leave_hours = 0
            total_annual_leave_hours = 0
            total_bereavement_leave_hours = 0

            for day in week_days:
                cost_lines = lines_by_staff_day.get((staff_id, day), [])
                daily_data = cls._process_daily_lines(staff_member, day, cost_lines)

                daily_cost = round(
                    sum(float(line.total_cost) for line in cost_lines), 2
                )
                daily_data["daily_cost"] = daily_cost
                daily_data["daily_base_cost"] = round(
                    daily_cost / float(loading_multiplier), 2
                )

                weekly_hours.append(daily_data)
                total_hours += daily_data["hours"]
                total_billable_hours += daily_data.get("billable_hours", 0)
                total_scheduled_hours += daily_data.get("scheduled_hours", 0)
                total_billed_hours += daily_data.get("billed_hours", 0)
                total_unbilled_hours += daily_data.get("unbilled_hours", 0)
                total_overtime_1_5x_hours += daily_data.get("overtime_1_5x_hours", 0)
                total_overtime_2x_hours += daily_data.get("overtime_2x_hours", 0)
                total_sick_leave_hours += daily_data.get("sick_leave_hours", 0)
                total_annual_leave_hours += daily_data.get("annual_leave_hours", 0)
                total_bereavement_leave_hours += daily_data.get(
                    "bereavement_leave_hours", 0
                )

            weekly_cost = sum(day["daily_cost"] for day in weekly_hours)
            weekly_base_cost = sum(day["daily_base_cost"] for day in weekly_hours)
            billable_percentage = (
                (total_billable_hours / total_hours * 100) if total_hours > 0 else 0
            )

            staff_entry = {
                "staff_id": staff_id,
                "name": staff_member.get_display_full_name(),
                "weekly_hours": weekly_hours,
                "total_hours": float(total_hours),
                "total_billable_hours": float(total_billable_hours),
                "total_scheduled_hours": float(total_scheduled_hours),
                "billable_percentage": round(billable_percentage, 1),
                "status": cls._get_staff_status(total_hours, staff_member),
                "total_billed_hours": float(total_billed_hours),
                "total_unbilled_hours": float(total_unbilled_hours),
                "total_overtime_hours": float(
                    total_overtime_1_5x_hours + total_overtime_2x_hours
                ),
                "total_overtime_1_5x_hours": float(total_overtime_1_5x_hours),
                "total_overtime_2x_hours": float(total_overtime_2x_hours),
                "total_sick_leave_hours": float(total_sick_leave_hours),
                "total_annual_leave_hours": float(total_annual_leave_hours),
                "total_bereavement_leave_hours": float(total_bereavement_leave_hours),
                "weekly_cost": round(weekly_cost, 2),
                "weekly_base_cost": round(weekly_base_cost, 2),
            }
            staff_data.append(staff_entry)

        return staff_data

    @classmethod
    def _process_daily_lines(
        cls, staff_member: Staff, day: date, cost_lines: list
    ) -> Dict[str, Any]:
        """Process pre-fetched cost lines for a single staff/day."""
        scheduled_hours = staff_member.get_scheduled_hours(day)

        # Split into work and leave
        work_lines = []
        leave_lines = []
        for line in cost_lines:
            job_name = (
                line.cost_set.job.name if line.cost_set and line.cost_set.job else ""
            )
            if "Leave" in job_name:
                leave_lines.append(line)
            else:
                work_lines.append(line)

        daily_hours = sum(Decimal(line.quantity) for line in cost_lines)
        billable_hours = sum(
            Decimal(line.quantity) for line in cost_lines if line.is_billable == "true"
        )
        has_leave = len(leave_lines) > 0
        leave_type = (
            leave_lines[0].cost_set.job.name
            if has_leave and leave_lines[0].cost_set and leave_lines[0].cost_set.job
            else None
        )

        base_data = {
            "day": day.strftime("%Y-%m-%d"),
            "hours": float(daily_hours),
            "billable_hours": float(billable_hours),
            "scheduled_hours": float(scheduled_hours),
            "status": cls._get_day_status(
                float(daily_hours), scheduled_hours, has_leave
            ),
            "leave_type": leave_type,
            "has_leave": has_leave,
        }

        billed_hours = unbilled_hours = overtime_1_5x_hours = overtime_2x_hours = 0
        daily_weighted_hours = Decimal(0)

        for line in work_lines:
            multiplier = (
                Decimal(line.wage_rate_multiplier)
                if line.wage_rate_multiplier is not None
                else Decimal("1.0")
            )
            hours = line.quantity
            daily_weighted_hours += hours * multiplier
            if multiplier == Decimal("0.0"):
                continue
            if line.is_billable == "true":
                billed_hours += hours
            else:
                unbilled_hours += hours
            if multiplier == Decimal("1.5"):
                overtime_1_5x_hours += hours
            elif multiplier == Decimal("2.0"):
                overtime_2x_hours += hours

        sick_leave_hours = annual_leave_hours = bereavement_leave_hours = 0
        for line in leave_lines:
            pay_item = (
                line.cost_set.job.default_xero_pay_item
                if line.cost_set and line.cost_set.job
                else None
            )
            hours = line.quantity
            if pay_item and pay_item.name == "Sick Leave":
                sick_leave_hours += hours
                daily_weighted_hours += hours
            elif pay_item and pay_item.name == "Annual Leave":
                annual_leave_hours += hours
                daily_weighted_hours += hours
            elif pay_item and pay_item.name == "Bereavement Leave":
                bereavement_leave_hours += hours
                daily_weighted_hours += hours

        base_data.update(
            {
                "billed_hours": float(billed_hours),
                "unbilled_hours": float(unbilled_hours),
                "overtime_1_5x_hours": float(overtime_1_5x_hours),
                "overtime_2x_hours": float(overtime_2x_hours),
                "sick_leave_hours": float(sick_leave_hours),
                "annual_leave_hours": float(annual_leave_hours),
                "bereavement_leave_hours": float(bereavement_leave_hours),
                "daily_weighted_hours": float(daily_weighted_hours),
            }
        )
        return base_data

    @classmethod
    def _get_day_status(
        cls, daily_hours: float, scheduled_hours: float, has_leave: bool
    ) -> str:
        """Determine status for a day."""
        if has_leave:
            return "Leave"
        elif scheduled_hours == 0:
            return "Off"
        elif daily_hours == 0:
            return "⚠"
        elif daily_hours >= scheduled_hours:
            return "✓"
        else:
            return "⚠"

    @classmethod
    def _get_staff_status(cls, total_hours: float, staff_member: Staff) -> str:
        """Determine overall status for staff member."""
        if total_hours >= 35:
            return "Complete"
        elif total_hours >= 20:
            return "Partial"
        elif total_hours > 0:
            return "Minimal"
        else:
            return "Missing"

    @classmethod
    def _calculate_weekly_totals(
        cls, staff_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate weekly totals from staff data."""
        total_hours = sum(staff["total_hours"] for staff in staff_data)
        total_billable_hours = sum(
            staff["total_billable_hours"] for staff in staff_data
        )

        billable_percentage = (
            (total_billable_hours / total_hours * 100) if total_hours > 0 else 0
        )

        return {
            "total_hours": round(total_hours, 1),
            "total_billable_hours": round(total_billable_hours, 1),
            "billable_percentage": round(billable_percentage, 1),
            "staff_count": len(staff_data),
        }

    @classmethod
    def _get_job_metrics(cls, start_date: date, end_date: date) -> Dict[str, Any]:
        """Get job-related metrics for the week using CostLine system."""
        try:
            # Get active jobs
            active_jobs = Job.objects.filter(
                status__in=["accepted_quote", "in_progress", "quoting"]
            ).count()

            # Get all cost lines for the week (not just time)
            # Prefetch latest_estimate to avoid N+1 when accessing job.latest_estimate
            cost_lines_week = CostLine.objects.filter(
                cost_set__kind="actual",
                accounting_date__gte=start_date,
                accounting_date__lte=end_date,
            ).select_related("cost_set__job", "cost_set__job__latest_estimate")

            jobs_with_entries = (
                cost_lines_week.values("cost_set__job").distinct().count()
            )
            logger.info(f"Query result: {cost_lines_week}")

            # Calculate totals
            total_actual_hours = Decimal(0)
            total_estimated_hours = Decimal(0)
            total_estimated_profit = Decimal(0)
            total_actual_profit = Decimal(0)

            # Use a set to track jobs we've already processed for estimates
            processed_jobs = set()

            for line in cost_lines_week:
                if line.kind == "time":
                    total_actual_hours += line.quantity

                # Calculate actual profit for each line
                total_actual_profit += line.total_rev - line.total_cost

                # Calculate estimated profit for the job (once per job)
                job = line.cost_set.job
                if job and job.id not in processed_jobs:
                    processed_jobs.add(job.id)
                    if job.latest_estimate:
                        est_cost = job.latest_estimate.summary["cost"]
                        est_rev = job.latest_estimate.summary["rev"]
                        total_estimated_hours += Decimal(
                            job.latest_estimate.summary.get("total_hours", 0)
                        )
                        total_estimated_profit += Decimal(est_rev - est_cost)

            job_metrics = {
                "job_count": active_jobs,
                "jobs_worked_this_week": jobs_with_entries,
                "total_estimated_hours": float(total_estimated_hours),
                "total_actual_hours": float(total_actual_hours),
                "total_estimated_profit": float(total_estimated_profit),
                "total_actual_profit": float(total_actual_profit),
                "total_profit": float(
                    total_actual_profit
                ),  # For now, total_profit is actual
            }

            logger.info(f"Job metrics: {job_metrics}")

            return job_metrics

        except Exception as e:
            logger.error(f"Error getting job metrics: {e}")
            return {
                "job_count": 0,
                "jobs_worked_this_week": 0,
                "total_estimated_hours": 0,
                "total_actual_hours": 0,
                "total_estimated_profit": 0,
                "total_actual_profit": 0,
                "total_profit": 0,
            }

    @classmethod
    def _calculate_summary_stats(
        cls, staff_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate summary statistics."""
        total_staff = len(staff_data)
        complete_staff = len([s for s in staff_data if s["status"] == "Complete"])
        partial_staff = len([s for s in staff_data if s["status"] == "Partial"])
        missing_staff = len([s for s in staff_data if s["status"] == "Missing"])

        completion_rate = (complete_staff / total_staff * 100) if total_staff > 0 else 0

        return {
            "total_staff": total_staff,
            "complete_staff": complete_staff,
            "partial_staff": partial_staff,
            "missing_staff": missing_staff,
            "completion_rate": round(completion_rate, 1),
        }

    @classmethod
    def _is_current_week(cls, start_date: date) -> bool:
        """Check if the given start date is the current week."""
        today = date.today()
        current_week_start = today - timedelta(days=today.weekday())
        return start_date == current_week_start
