import calendar
import datetime
import logging
from datetime import date, timedelta
from decimal import Decimal
from logging import getLogger
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import holidays
from django.db import models
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from apps.accounts.models import Staff
from apps.accounts.utils import get_displayable_staff, get_excluded_staff
from apps.client.models import Client
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error

logger = getLogger(__name__)


def _persist_and_raise(exception: Exception, **context) -> None:
    """Persist an exception and re-raise as AlreadyLoggedException."""
    app_error = persist_app_error(exception, **context)
    raise AlreadyLoggedException(exception, app_error.id)


class KPIService:
    """
    Service responsible for calculating and providing KPI metrics for reports.
    All business logic related to KPIs shall be implemented here.
    """

    nz_timezone = ZoneInfo("Pacific/Auckland")
    shop_client_id: Optional[str] = None  # Will be set on first access

    @classmethod
    def _ensure_shop_client_id(cls) -> None:
        """Ensure shop_client_id is set, initialize if needed"""
        if cls.shop_client_id is None:
            cls.shop_client_id = Client.get_shop_client_id()

    @staticmethod
    def get_company_thresholds() -> Dict[str, float]:
        """
        Gets KPI thresholds based on CompanyDefaults

        Returns:
            Dict containing thresholds for KPI metrics
        """
        logger.info("Retrieving company thresholds for KPI calculations")
        try:
            company_defaults: CompanyDefaults = CompanyDefaults.get_solo()
            if not company_defaults:
                raise ValueError("No company defaults found")
            thresholds = {
                "kpi_daily_billable_hours_green": float(
                    company_defaults.kpi_daily_billable_hours_green
                ),
                "kpi_daily_billable_hours_amber": float(
                    company_defaults.kpi_daily_billable_hours_amber
                ),
                "kpi_daily_gp_target": float(company_defaults.kpi_daily_gp_target),
                "kpi_daily_shop_hours_percentage": float(
                    company_defaults.kpi_daily_shop_hours_percentage
                ),
                "kpi_daily_gp_green": float(company_defaults.kpi_daily_gp_green),
                "kpi_daily_gp_amber": float(company_defaults.kpi_daily_gp_amber),
            }
            logger.debug(f"Retrieved thresholds: {thresholds}")
            return thresholds
        except Exception as e:
            logger.error(f"Error retrieving company defaults: {str(e)}")
            raise

    @staticmethod
    def _process_entries(
        entries: List[Dict[str, Any]],
        revenue_key: str = "revenue",
        cost_key: str = "cost",
    ) -> Dict[datetime.date, Dict[str, float]]:
        """
        Segregates entries by date based on the provided Dict
        """
        entries_by_date = {
            entry["local_date"]: {
                "revenue": entry.get(revenue_key) or 0,
                "cost": entry.get(cost_key) or 0,
            }
            for entry in entries
        }
        return entries_by_date

    @classmethod
    def _get_holidays(cls, year: int, month: Optional[int] = None) -> Dict[date, str]:
        """
        Gets New Zealand holidays for a specific year and month.

        Args:
            year: The year to get holidays for
            month: Optional month (1-12) to filter holidays

        Returns:
            Set of dates that are holidays
        """
        nz_holidays = holidays.country_holidays("NZ", years=year)

        if month:
            return {
                date: name for date, name in nz_holidays.items() if date.month == month
            }
        return dict(nz_holidays)

    @classmethod
    def get_month_days_range(cls, year: int, month: int) -> Tuple[date, date, int]:
        """
        Gets the daily range for a specific month.

        Args:
            year: calendar year
            month: calendar month (1-12)

        Returns:
            Tuple containing initial date, final date and number of days of the month
        """
        logger.info(f"Calculating date range for year={year}, month={month}")
        _, num_days = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)

        logger.debug(
            f"Date range: {start_date} to {end_date}, days in month: {num_days}"
        )
        return start_date, end_date, num_days

    @staticmethod
    def _get_color(
        value: float | Decimal, green_threshold: float, amber_threshold: float
    ) -> str:
        if value >= green_threshold:
            return "green"
        if value >= amber_threshold:
            return "amber"
        return "red"

    @classmethod
    def get_job_breakdown_for_date(cls, target_date: date) -> List[Dict[str, Any]]:
        """
        Get job-level profit breakdown for a specific date using CostLine data

        Args:
            target_date: The date to get job breakdown for

        Returns:
            List of job breakdowns with profit details
        """
        cls._ensure_shop_client_id()
        excluded_staff_ids = get_excluded_staff()

        # Get cost lines for the target date from 'actual' cost sets
        cost_lines = (
            CostLine.objects.annotate(
                # Extract staff_id and is_billable from meta JSONField
                staff_id=KeyTextTransform("staff_id", "meta"),
                is_billable=KeyTextTransform("is_billable", "meta"),
            )
            .filter(
                cost_set__kind="actual",
                accounting_date=target_date,
            )
            .select_related("cost_set__job")
        )

        # For time entries, exclude staff that shouldn't be included
        time_lines = cost_lines.filter(kind="time").exclude(
            staff_id__in=[str(sid) for sid in excluded_staff_ids]
        )

        # Material and adjustment lines don't need staff filtering
        material_lines = cost_lines.filter(kind="material")
        adjustment_lines = cost_lines.filter(kind="adjust")

        # Group by job
        job_data = {}

        # Process time entries
        for line in time_lines:
            job = line.cost_set.job
            job_number = job.job_number

            if job_number not in job_data:
                job_data[job_number] = {
                    "job_id": str(job.id),
                    "job_number": job_number,
                    "job_display_name": job.job_display_name,
                    "client_name": job.client.name,  # Add client name
                    "labour_revenue": 0,
                    "labour_cost": 0,
                    "material_revenue": 0,
                    "material_cost": 0,
                    "adjustment_revenue": 0,
                    "adjustment_cost": 0,
                }

            # Only count billable time revenue if not shop client
            if line.is_billable == "true" and str(job.client_id) != cls.shop_client_id:
                job_data[job_number]["labour_revenue"] += float(line.total_rev)

            job_data[job_number]["labour_cost"] += float(line.total_cost)

        # Process material entries
        for line in material_lines:
            job = line.cost_set.job
            job_number = job.job_number

            if job_number not in job_data:
                job_data[job_number] = {
                    "job_id": str(job.id),
                    "job_number": job_number,
                    "job_display_name": job.job_display_name,
                    "client_name": job.client.name,  # Add client name
                    "labour_revenue": 0,
                    "labour_cost": 0,
                    "material_revenue": 0,
                    "material_cost": 0,
                    "adjustment_revenue": 0,
                    "adjustment_cost": 0,
                }

            job_data[job_number]["material_revenue"] += float(line.total_rev)
            job_data[job_number]["material_cost"] += float(line.total_cost)

        # Process adjustment entries
        for line in adjustment_lines:
            job = line.cost_set.job
            job_number = job.job_number

            if job_number not in job_data:
                job_data[job_number] = {
                    "job_id": str(job.id),
                    "job_number": job_number,
                    "job_display_name": job.job_display_name,
                    "client_name": job.client.name,  # Add client name
                    "labour_revenue": 0,
                    "labour_cost": 0,
                    "material_revenue": 0,
                    "material_cost": 0,
                    "adjustment_revenue": 0,
                    "adjustment_cost": 0,
                }

            job_data[job_number]["adjustment_revenue"] += float(line.total_rev)
            job_data[job_number]["adjustment_cost"] += float(line.total_cost)

        # Calculate profits and return sorted list
        result = []
        for job_number, data in job_data.items():
            labour_profit = data["labour_revenue"] - data["labour_cost"]
            material_profit = data["material_revenue"] - data["material_cost"]
            adjustment_profit = data["adjustment_revenue"] - data["adjustment_cost"]
            total_profit = labour_profit + material_profit + adjustment_profit

            # Calculate billable hours for this job on this date
            billable_hours = 0
            for line in time_lines:
                if (
                    line.cost_set.job.job_number == job_number
                    and line.is_billable == "true"
                    and str(line.cost_set.job.client_id) != cls.shop_client_id
                ):
                    billable_hours += float(line.quantity)

            # Calculate total revenue and cost
            total_revenue = (
                data["labour_revenue"]
                + data["material_revenue"]
                + data["adjustment_revenue"]
            )
            total_cost = (
                data["labour_cost"] + data["material_cost"] + data["adjustment_cost"]
            )

            result.append(
                {
                    "job_id": data["job_id"],
                    "job_number": str(job_number),
                    "job_name": data["job_display_name"],
                    "client_name": data["client_name"],
                    "billable_hours": billable_hours,
                    "revenue": total_revenue,
                    "cost": total_cost,
                    "profit": total_profit,
                    "labour_profit": labour_profit,
                    "material_profit": material_profit,
                    "adjustment_profit": adjustment_profit,
                }
            )

        # Sort by profit descending
        result.sort(key=lambda x: x["profit"], reverse=True)
        return result

    @classmethod
    def get_calendar_data(cls, year: int, month: int) -> Dict[str, Any]:
        """
        Gets all KPI data for a specific month.

        Args:
            year: calendar year
            month: calendar month (1-12)

        Returns:
            Dict containing calendar data, monthly totals and threshold informations
        """
        print(f"🔍 KPIService.get_calendar_data called with year={year}, month={month}")
        logger.info(f"Generating KPI calendar data for {year}-{month}")

        cls._ensure_shop_client_id()
        thresholds = cls.get_company_thresholds()
        logger.debug(
            f"Using thresholds: green={thresholds['kpi_daily_billable_hours_green']}, "
            f"amber={thresholds['kpi_daily_billable_hours_amber']}"
        )

        start_date, end_date, _ = cls.get_month_days_range(year, month)
        print(f"📅 Date range calculated: {start_date} to {end_date}")
        excluded_staff_ids = get_excluded_staff()
        logger.debug(f"Excluded staff IDs: {excluded_staff_ids}")

        calendar_data = {}
        monthly_totals: Dict[str, float] = {
            "billable_hours": 0,
            "total_hours": 0,
            "shop_hours": 0,
            "gross_profit": 0,
            "days_green": 0,
            "days_amber": 0,
            "days_red": 0,
            "labour_green_days": 0,
            "labour_amber_days": 0,
            "labour_red_days": 0,
            "profit_green_days": 0,
            "profit_amber_days": 0,
            "profit_red_days": 0,
            "working_days": 0,
            "elapsed_workdays": 0,
            "active_workdays": 0,
            "remaining_workdays": 0,
            # The following are internal
            "time_revenue": 0,
            "material_revenue": 0,
            "adjustment_revenue": 0,
            "staff_cost": 0,
            "material_cost": 0,
            "adjustment_cost": 0,
            "material_profit": 0,
            "adjustment_profit": 0,
        }

        # Process data using CostLine from 'actual' cost sets
        # Get time entries aggregated by date
        time_entries_by_date = {}

        # Extract staff_id and is_billable from meta JSONField
        cost_lines_time = (
            CostLine.objects.annotate(
                staff_id=KeyTextTransform("staff_id", "meta"),
                is_billable=KeyTextTransform("is_billable", "meta"),
            )
            .filter(
                cost_set__kind="actual",
                kind="time",
                accounting_date__gte=start_date,
                accounting_date__lte=end_date,
            )
            .exclude(staff_id__in=[str(sid) for sid in excluded_staff_ids])
            .select_related("cost_set__job")
        )

        # Group time entries by date for aggregation
        for line in cost_lines_time:
            line_date = line.accounting_date

            if line_date not in time_entries_by_date:
                time_entries_by_date[line_date] = {
                    "total_hours": Decimal("0"),
                    "billable_hours": Decimal("0"),
                    "shop_hours": Decimal("0"),
                    "time_revenue": Decimal("0"),
                    "staff_cost": Decimal("0"),
                }

            hours = line.quantity
            time_entries_by_date[line_date]["total_hours"] += hours

            # Check if billable and not shop client
            if (
                line.is_billable == "true"
                and str(line.cost_set.job.client_id) != cls.shop_client_id
            ):
                time_entries_by_date[line_date]["billable_hours"] += hours
                time_entries_by_date[line_date]["time_revenue"] += line.total_rev

            # Check if shop hours
            if str(line.cost_set.job.client_id) == cls.shop_client_id:
                time_entries_by_date[line_date]["shop_hours"] += hours

            time_entries_by_date[line_date]["staff_cost"] += line.total_cost

        # Get material entries aggregated by date
        material_entries = {}
        cost_lines_material = CostLine.objects.filter(
            cost_set__kind="actual",
            kind="material",
            accounting_date__gte=start_date,
            accounting_date__lte=end_date,
        )

        for line in cost_lines_material:
            line_date = line.accounting_date
            if line_date not in material_entries:
                material_entries[line_date] = {
                    "revenue": Decimal("0"),
                    "cost": Decimal("0"),
                }

            material_entries[line_date]["revenue"] += line.total_rev
            material_entries[line_date]["cost"] += line.total_cost

        # Get adjustment entries aggregated by date
        adjustment_entries = {}
        cost_lines_adjustment = CostLine.objects.filter(
            cost_set__kind="actual",
            kind="adjust",
            accounting_date__gte=start_date,
            accounting_date__lte=end_date,
        )

        for line in cost_lines_adjustment:
            line_date = line.accounting_date
            if line_date not in adjustment_entries:
                adjustment_entries[line_date] = {
                    "revenue": Decimal("0"),
                    "cost": Decimal("0"),
                }

            adjustment_entries[line_date]["revenue"] += line.total_rev
            adjustment_entries[line_date]["cost"] += line.total_cost

        material_by_date = {
            date: {"revenue": data["revenue"], "cost": data["cost"]}
            for date, data in material_entries.items()
        }
        adjustment_by_date = {
            date: {"revenue": data["revenue"], "cost": data["cost"]}
            for date, data in adjustment_entries.items()
        }

        logger.debug(f"Retrieved data for {len(time_entries_by_date)} days")

        holiday_dates = cls._get_holidays(year, month)
        logger.debug(f"Holidays in {year}-{month}: {holiday_dates}")

        # For each day of the month
        current_date = start_date
        current_date_system = datetime.date.today()
        while current_date <= end_date:
            # Skip weekends (5=Saturday, 6=Sunday)
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            is_holiday = current_date in holiday_dates

            date_key = current_date.isoformat()
            base_data = {
                "date": date_key,
                "day": current_date.day,
                "holiday": is_holiday,
            }

            # Count all weekdays (including holidays) as working days
            monthly_totals["working_days"] += 1
            if current_date <= current_date_system:
                monthly_totals["elapsed_workdays"] += 1

            # Process holidays same as regular days - can have financial activity
            # (adjustments, material entries, etc.) but mark them as holidays

            logger.debug(f"Processing data for day: {current_date}")

            time_entry = time_entries_by_date.get(
                current_date,
                {
                    "total_hours": Decimal("0"),
                    "billable_hours": Decimal("0"),
                    "shop_hours": Decimal("0"),
                    "time_revenue": Decimal("0"),
                    "staff_cost": Decimal("0"),
                },
            )

            material_entry = material_by_date.get(
                current_date, {"revenue": Decimal("0"), "cost": Decimal("0")}
            )

            adjustment_entry = adjustment_by_date.get(
                current_date, {"revenue": Decimal("0"), "cost": Decimal("0")}
            )

            billable_hours = time_entry.get("billable_hours") or 0
            total_hours = time_entry.get("total_hours") or 0
            shop_hours = time_entry.get("shop_hours") or 0
            time_revenue = time_entry.get("time_revenue") or 0
            staff_cost = time_entry.get("staff_cost") or 0

            material_revenue = material_entry.get("revenue") or 0
            material_cost = material_entry.get("cost") or 0

            adjustment_revenue = adjustment_entry.get("revenue") or 0
            adjustment_cost = adjustment_entry.get("cost") or 0

            gross_profit = (time_revenue + material_revenue + adjustment_revenue) - (
                staff_cost + material_cost + adjustment_cost
            )
            shop_percentage = (
                (Decimal(shop_hours) / Decimal(total_hours) * 100)
                if total_hours > 0
                else Decimal("0")
            )

            # Increment status counters
            color = cls._get_color(
                billable_hours,
                thresholds["kpi_daily_billable_hours_green"],
                thresholds["kpi_daily_billable_hours_amber"],
            )

            match color:
                case "green":
                    monthly_totals["days_green"] += 1
                case "amber":
                    monthly_totals["days_amber"] += 1
                case _:
                    monthly_totals["days_red"] += 1

            # Only count performance for elapsed days (not future days)
            if current_date <= current_date_system:
                # Separate labour performance counting
                if billable_hours >= thresholds["kpi_daily_billable_hours_green"]:
                    monthly_totals["labour_green_days"] += 1
                elif billable_hours >= thresholds["kpi_daily_billable_hours_amber"]:
                    monthly_totals["labour_amber_days"] += 1
                else:
                    monthly_totals["labour_red_days"] += 1

                # Separate profit performance counting
                if gross_profit >= thresholds["kpi_daily_gp_target"]:
                    monthly_totals["profit_green_days"] += 1
                elif gross_profit >= thresholds["kpi_daily_gp_green"]:
                    monthly_totals["profit_amber_days"] += 1
                else:
                    monthly_totals["profit_red_days"] += 1

            full_data = base_data.copy()
            # Add holiday name if this is a holiday
            if is_holiday:
                full_data["holiday_name"] = holiday_dates[current_date]

            full_data.update(
                {
                    "billable_hours": billable_hours,
                    "total_hours": total_hours,
                    "shop_hours": shop_hours,
                    "shop_percentage": float(shop_percentage),
                    "gross_profit": float(gross_profit),
                    "color": color,
                    "gp_target_achievement": float(
                        (
                            Decimal(gross_profit)
                            / Decimal(thresholds["kpi_daily_gp_target"])
                            * 100
                        )
                        if thresholds["kpi_daily_gp_target"] > 0
                        else 0
                    ),
                    "details": {
                        "time_revenue": float(time_revenue),
                        "material_revenue": float(material_revenue),
                        "adjustment_revenue": float(adjustment_revenue),
                        "total_revenue": float(
                            time_revenue + material_revenue + adjustment_revenue
                        ),
                        "staff_cost": float(staff_cost),
                        "material_cost": float(material_cost),
                        "adjustment_cost": float(adjustment_cost),
                        "total_cost": float(
                            staff_cost + material_cost + adjustment_cost
                        ),
                        "profit_breakdown": {
                            "labor_profit": float(time_revenue - staff_cost),
                            "material_profit": float(material_revenue - material_cost),
                            "adjustment_profit": float(
                                adjustment_revenue - adjustment_cost
                            ),
                        },
                        "job_breakdown": cls.get_job_breakdown_for_date(current_date),
                    },
                }
            )
            calendar_data[date_key] = full_data

            if current_date <= current_date_system and total_hours > 0:
                monthly_totals["active_workdays"] += 1
            monthly_totals["billable_hours"] += billable_hours
            monthly_totals["total_hours"] += total_hours
            monthly_totals["shop_hours"] += shop_hours
            monthly_totals["gross_profit"] += gross_profit
            monthly_totals["material_revenue"] += material_revenue
            monthly_totals["adjustment_revenue"] += adjustment_revenue
            monthly_totals["time_revenue"] += time_revenue
            monthly_totals["staff_cost"] += staff_cost
            monthly_totals["material_cost"] += material_cost
            monthly_totals["adjustment_cost"] += adjustment_cost
            monthly_totals["material_profit"] += material_revenue - material_cost
            monthly_totals["adjustment_profit"] += adjustment_revenue - adjustment_cost

            # Advance to next day
            current_date += timedelta(days=1)

        monthly_totals["remaining_workdays"] = (
            monthly_totals["working_days"] - monthly_totals["elapsed_workdays"]
        )

        # Calculate total revenue and total cost for reference
        monthly_totals["total_revenue"] = (
            monthly_totals["time_revenue"]
            + monthly_totals["material_revenue"]
            + monthly_totals["adjustment_revenue"]
        )
        monthly_totals["total_cost"] = (
            monthly_totals["staff_cost"]
            + monthly_totals["material_cost"]
            + monthly_totals["adjustment_cost"]
        )

        # Calculate net profit: Gross Profit - (Daily Target × Elapsed Working Days)
        # This approximates operating expenses using daily GP target for elapsed days
        daily_target = Decimal(str(thresholds["kpi_daily_gp_target"]))
        elapsed_days = Decimal(str(monthly_totals["elapsed_workdays"]))
        elapsed_target = daily_target * elapsed_days
        monthly_totals["elapsed_target"] = float(elapsed_target)
        monthly_totals["net_profit"] = float(
            monthly_totals["gross_profit"] - elapsed_target
        )

        # Calculate percentages after all days processed
        cls._calculate_monthly_percentages(monthly_totals)

        billable_daily_avg = monthly_totals["avg_billable_hours_so_far"]
        monthly_totals["color_hours"] = cls._get_color(
            billable_daily_avg,
            thresholds["kpi_daily_billable_hours_green"],
            thresholds["kpi_daily_billable_hours_amber"],
        )

        gp_daily_avg = monthly_totals["avg_daily_gp_so_far"]
        monthly_totals["color_gp"] = cls._get_color(
            gp_daily_avg,
            thresholds["kpi_daily_gp_target"],
            (thresholds["kpi_daily_gp_target"] / 2),
        )

        shop_percentage = monthly_totals["shop_percentage"]
        monthly_totals["color_shop"] = cls._get_color(
            20.0,  # Target threshold (reverse logic - lower is better)
            shop_percentage,
            25.0,  # Warning threshold
        )

        logger.info(
            f"Monthly totals: billable: {monthly_totals['billable_hours']:.1f}h, "
            f"billable %: {monthly_totals['billable_percentage']:.1f}%"
        )
        logger.info(
            f"Performance: green days: {monthly_totals['days_green']}, "
            f"amber: {monthly_totals['days_amber']}, red: {monthly_totals['days_red']}"
        )
        response_data = {
            "calendar_data": calendar_data,
            "monthly_totals": monthly_totals,
            "thresholds": thresholds,
            "year": year,
            "month": month,
        }
        print(
            f"✅ KPIService returning data for year={response_data['year']}"
            f" month={response_data['month']}"
        )
        logger.debug(f"Calendar data generated with {len(calendar_data)} days")
        return response_data

    @staticmethod
    def _calculate_monthly_percentages(monthly_totals: Dict[str, float]) -> None:
        """
        Calculate percentages and medias for monthly totals

        Args:
            monthly_totals: Dict of monthly totals to be updated
        """
        logger.debug("Calculating monthly percentages")

        # Initialize default values
        monthly_totals["billable_percentage"] = 0
        monthly_totals["shop_percentage"] = 0
        monthly_totals["avg_daily_gp"] = 0
        monthly_totals["avg_daily_gp_so_far"] = 0
        monthly_totals["avg_billable_hours_so_far"] = 0

        # Calculate billable and shop percentages if we have hours
        if monthly_totals["total_hours"] > 0:
            monthly_totals["billable_percentage"] = round(
                Decimal(monthly_totals["billable_hours"])
                / Decimal(monthly_totals["total_hours"])
                * 100,
                1,
            )
            monthly_totals["shop_percentage"] = round(
                Decimal(monthly_totals["shop_hours"] / monthly_totals["total_hours"])
                * 100,
                1,
            )
            logger.debug(
                f"Calculated billable %: {monthly_totals['billable_percentage']}%, "
                f"shop percentage: {monthly_totals['shop_percentage']}%"
            )

        # Calculate average daily gross profit if we have working days
        if monthly_totals["working_days"] > 0:
            monthly_totals["avg_daily_gp"] = round(
                Decimal(
                    monthly_totals["gross_profit"] / monthly_totals["working_days"]
                ),
                2,
            )
            logger.debug(
                f"Calculated average daily gross profit: "
                f"${monthly_totals['avg_daily_gp']}"
            )
        else:
            logger.warning("No working days found for month - average GP will be zero")

        # Calculate averages based on days that actually have hours logged,
        # so days with no timesheets don't dilute the average
        if monthly_totals["active_workdays"] > 0:
            monthly_totals["avg_daily_gp_so_far"] = round(
                Decimal(monthly_totals["gross_profit"])
                / Decimal(monthly_totals["active_workdays"]),
                2,
            )
            monthly_totals["avg_billable_hours_so_far"] = round(
                Decimal(monthly_totals["billable_hours"])
                / Decimal(monthly_totals["active_workdays"]),
                1,
            )


class JobAgingService:
    """
    Service responsible for providing job aging information including financial data,
    timing information, and current status.
    """

    @staticmethod
    def get_job_aging_data(include_archived: bool = False) -> Dict[str, Any]:
        """
        Main method to fetch and process all job aging data.

        Args:
            include_archived: Whether to include archived jobs in the results

        Returns:
            Dict containing job aging data
        """
        logger.info("Generating job aging data")

        try:
            # Get active jobs (exclude archived unless requested)
            jobs_query = Job.objects.select_related("client").prefetch_related(
                "events", "cost_sets__cost_lines"
            )

            if not include_archived:
                jobs_query = jobs_query.exclude(status="archived")

            jobs = jobs_query.order_by("-created_at")
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            logger.error(f"Database error fetching jobs: {str(exc)}")
            _persist_and_raise(
                exc,
                additional_context={
                    "operation": "fetch_jobs_for_aging_report",
                    "include_archived": include_archived,
                    "query_filters": "active_jobs_with_client_and_cost_data",
                },
            )

        job_data = []
        for job in jobs:
            try:
                # Get financial data
                financial_data = JobAgingService._get_financial_totals(job)

                # Get timing data
                timing_data = JobAgingService._get_timing_data(job)

                job_info = {
                    "id": str(job.id),
                    "job_number": job.job_number,
                    "name": job.name,
                    "client_name": job.client.name if job.client else "No Client",
                    "status": job.status,
                    "status_display": job.get_status_display(),
                    "price_cap": job.price_cap,
                    "financial_data": financial_data,
                    "timing_data": timing_data,
                }
                job_data.append(job_info)
            except Exception as exc:
                logger.error(f"Error processing job {job.job_number}: {str(exc)}")
                persist_app_error(
                    exc,
                    job_id=job.id,
                    additional_context={
                        "operation": "process_individual_job_for_aging",
                        "job_number": job.job_number,
                        "job_status": job.status,
                        "client_name": job.client.name if job.client else None,
                    },
                )
                # Continue processing other jobs

        # Sort by last activity (most recent first)
        try:
            job_data.sort(key=lambda x: x["timing_data"]["last_activity_days_ago"])
        except Exception as exc:
            logger.warning(f"Error sorting job data: {str(exc)}")
            persist_app_error(
                exc,
                severity=logging.WARNING,
                additional_context={
                    "operation": "sort_job_aging_data",
                    "jobs_count": len(job_data),
                    "sort_key": "timing_data.last_activity_days_ago",
                },
            )
            # Return unsorted data

        return {"jobs": job_data}

    @staticmethod
    def _get_financial_totals(job: Job) -> Dict[str, float]:
        """
        Extract estimate/quote/actual totals from CostSets.

        Args:
            job: Job instance

        Returns:
            Dict containing financial totals
        """
        financial_data = {
            "estimate_total": 0.0,
            "quote_total": 0.0,
            "actual_total": 0.0,
        }

        try:
            # Get latest estimate
            if job.latest_estimate:
                financial_data["estimate_total"] = float(
                    sum(line.total_rev for line in job.latest_estimate.cost_lines.all())
                )
        except Exception as exc:
            logger.warning(
                f"Error calculating estimate total for job {job.job_number}: {str(exc)}"
            )
            persist_app_error(
                exc,
                severity=logging.WARNING,
                job_id=job.id,
                additional_context={
                    "operation": "calculate_job_estimate_total",
                    "job_number": job.job_number,
                    "has_latest_estimate": job.latest_estimate is not None,
                    "business_process": "job_aging_financial_data",
                },
            )

        try:
            # Get latest quote
            if job.latest_quote:
                financial_data["quote_total"] = float(
                    sum(line.total_rev for line in job.latest_quote.cost_lines.all())
                )
        except Exception as exc:
            logger.warning(
                f"Error calculating quote total for job {job.job_number}: {str(exc)}"
            )
            persist_app_error(
                exc,
                severity=logging.WARNING,
                job_id=job.id,
                additional_context={
                    "operation": "calculate_job_quote_total",
                    "job_number": job.job_number,
                    "has_latest_quote": job.latest_quote is not None,
                    "business_process": "job_aging_financial_data",
                },
            )

        try:
            # Get latest actual
            if job.latest_actual:
                financial_data["actual_total"] = float(
                    sum(line.total_rev for line in job.latest_actual.cost_lines.all())
                )
        except Exception as exc:
            logger.warning(
                f"Error calculating actual total for job {job.job_number}: {str(exc)}"
            )
            persist_app_error(exc)

        return financial_data

    @staticmethod
    def _get_timing_data(job: Job) -> Dict[str, Any]:
        """
        Calculate timing information for a job.

        Args:
            job: Job instance

        Returns:
            Dict containing timing data
        """
        now = timezone.now()
        created_date = job.created_at.date()

        timing_data = {
            "created_date": created_date.isoformat(),
            "created_days_ago": (now.date() - created_date).days,
            "days_in_current_status": 0,
            "last_activity_date": None,
            "last_activity_days_ago": None,
            "last_activity_type": None,
            "last_activity_description": None,
        }

        try:
            timing_data["days_in_current_status"] = (
                JobAgingService._calculate_time_in_status(job)
            )
        except Exception as exc:
            logger.warning(
                f"Error calculating time in status for job {job.job_number}: {str(exc)}"
            )
            persist_app_error(exc)

        try:
            # Get last activity
            last_activity = JobAgingService._get_last_activity(job)
            if last_activity:
                timing_data.update(last_activity)
        except AlreadyLoggedException as exc:
            logger.warning(
                "Error getting last activity for job %s: %s",
                job.job_number,
                exc.original,
            )
        except Exception as exc:
            logger.warning(
                f"Error getting last activity for job {job.job_number}: {str(exc)}"
            )
            persist_app_error(exc)

        return timing_data

    @staticmethod
    def _calculate_time_in_status(job: Job) -> int:
        """
        Calculate days in current status using JobEvent model.

        Args:
            job: Job instance

        Returns:
            Number of days in current status
        """
        # Find the most recent status change event
        latest_status_change = job.events.filter(event_type="status_change").first()

        if latest_status_change:
            days_in_status = (timezone.now() - latest_status_change.timestamp).days
            return days_in_status
        else:
            # If no status change event, use job creation date
            return (timezone.now().date() - job.created_at.date()).days

    @staticmethod
    def _get_last_activity(job: Job) -> Dict[str, Any]:
        """
        Find most recent activity across ALL sources.

        Args:
            job: Job instance

        Returns:
            Dict containing last activity information or None if no activities found
        """
        activities = []

        try:
            # Check job events
            latest_event = job.events.first()  # Already ordered by -timestamp
            if latest_event:
                activities.append(
                    {
                        "date": latest_event.timestamp,
                        "type": "job_event",
                        "description": (
                            f"{latest_event.event_type}: {latest_event.description}"
                        ),
                    }
                )
        except Exception as exc:
            logger.warning(
                f"Error checking job events for job {job.job_number}: {str(exc)}"
            )
            persist_app_error(exc)

        try:
            # Check job model updates
            if job.updated_at:
                activities.append(
                    {
                        "date": job.updated_at,
                        "type": "job_update",
                        "description": "Job record updated",
                    }
                )
        except Exception as exc:
            logger.warning(
                f"Error checking job updates for job {job.job_number}: {str(exc)}"
            )
            persist_app_error(exc)

        try:
            # Check cost lines across all job cost sets
            for cost_set in job.cost_sets.all():
                for cost_line in cost_set.cost_lines.all():
                    # Use the accounting_date field (not legacy meta.date)
                    line_datetime = datetime.datetime.combine(
                        cost_line.accounting_date,
                        datetime.time.min,
                        tzinfo=timezone.get_current_timezone(),
                    )

                    description = (
                        f"{cost_line.get_kind_display()} entry: {cost_line.desc}"
                    )
                    # Only actual time entries have staff - estimates/quotes are planning entries
                    if cost_line.kind == "time" and cost_set.kind == "actual":
                        try:
                            staff_id = cost_line.meta.get("staff_id")
                            staff = Staff.objects.get(id=staff_id)
                            description = (
                                f"Time added by {staff.get_display_full_name()}"
                            )
                        except (Staff.DoesNotExist, ValueError, TypeError) as exc:
                            message = (
                                "Corrupted cost line staff reference detected "
                                f"(job_id={job.id}, cost_line_id={cost_line.id}, "
                                f"staff_id={staff_id})"
                            )
                            logger.error(message)
                            logged_exc = ValueError(message)
                            app_error = persist_app_error(
                                logged_exc,
                                job_id=job.id,
                                additional_context={
                                    "operation": "cost_line_staff_resolution",
                                    "cost_line_id": cost_line.id,
                                    "staff_id": staff_id,
                                },
                            )
                            raise AlreadyLoggedException(
                                logged_exc, app_error.id
                            ) from exc

                    activities.append(
                        {
                            "date": line_datetime,
                            "type": f"cost_line_{cost_line.kind}",
                            "description": description,
                        }
                    )
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            logger.error(
                (
                    f"Error checking cost line activities for job "
                    f"{job.job_number}: {str(exc)}"
                )
            )
            _persist_and_raise(
                exc,
                job_id=job.id,
                additional_context={
                    "operation": "gather_cost_line_activities",
                    "job_number": job.job_number,
                },
            )

        # Find the most recent activity
        if activities:
            try:
                latest_activity = max(activities, key=lambda x: x["date"])
                activity_date = latest_activity["date"]

                # Handle both date and datetime objects
                if hasattr(activity_date, "date"):
                    activity_date_obj = activity_date.date()
                else:
                    activity_date_obj = activity_date

                days_ago = (timezone.now().date() - activity_date_obj).days

                return {
                    "last_activity_date": activity_date_obj.isoformat(),
                    "last_activity_days_ago": days_ago,
                    "last_activity_type": latest_activity["type"],
                    "last_activity_description": latest_activity["description"],
                }
            except Exception as exc:
                logger.warning(
                    f"Error processing latest activity for job "
                    f"{job.job_number}: {str(exc)}"
                )
                persist_app_error(exc)

        return None


class StaffPerformanceService:
    """
    Service responsible for calculating staff performance metrics.
    All business logic related to staff utilisation and performance.
    """

    @staticmethod
    def get_staff_performance_data(
        start_date: date, end_date: date, staff_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get staff performance data for the specified period.

        Args:
            start_date: Period start date
            end_date: Period end date
            staff_id: Optional staff ID filter for individual report

        Returns:
            Dict containing team averages and staff performance data
        """
        try:
            # Get time entries from CostLine
            cost_lines = (
                CostLine.objects.annotate(
                    staff_id_meta=KeyTextTransform("staff_id", "meta"),
                    is_billable_meta=KeyTextTransform("is_billable", "meta"),
                )
                .filter(
                    cost_set__kind="actual",
                    kind="time",
                    accounting_date__gte=start_date,
                    accounting_date__lte=end_date,
                )
                .select_related("cost_set__job__client")
            )

            # Get all active staff
            all_staff = get_displayable_staff(date_range=(start_date, end_date))

            # Filter to specific staff if requested
            if staff_id:
                all_staff = all_staff.filter(id=staff_id)

            staff_data = []
            include_job_breakdown = staff_id is not None

            for staff in all_staff:
                staff_cost_lines = cost_lines.filter(staff_id_meta=str(staff.id))
                staff_metrics = StaffPerformanceService._calculate_staff_metrics(
                    staff, staff_cost_lines, include_job_breakdown
                )
                # Only include staff with recorded hours in the period
                if staff_metrics["total_hours"] > 0:
                    staff_data.append(staff_metrics)

            # Calculate team averages
            team_averages = StaffPerformanceService._calculate_team_averages(staff_data)

            # Create period summary
            period_summary = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_staff": len(staff_data),
                "period_description": (
                    f"{start_date.strftime('%B %d')} - "
                    f"{end_date.strftime('%B %d, %Y')}"
                ),
            }

            return {
                "team_averages": team_averages,
                "staff": staff_data,
                "period_summary": period_summary,
            }

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            logger.error(f"Error getting staff performance data: {str(exc)}")
            _persist_and_raise(
                exc,
                additional_context={
                    "operation": "staff_performance_data",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "staff_id": staff_id,
                },
            )

    @staticmethod
    def _calculate_staff_metrics(
        staff: Staff, cost_lines: models.QuerySet, include_job_breakdown: bool = False
    ) -> Dict[str, Any]:
        """
        Calculate performance metrics for a single staff member.

        Args:
            staff: Staff instance
            cost_lines: QuerySet of CostLine entries for this staff
            include_job_breakdown: Whether to include detailed job breakdown

        Returns:
            Dict containing staff performance metrics
        """
        total_hours = float(sum(line.quantity for line in cost_lines))
        # Get shop client ID for filtering
        shop_client_id = Client.get_shop_client_id()

        billable_hours = float(
            sum(
                line.quantity
                for line in cost_lines
                if line.is_billable_meta == "true"
                and str(line.cost_set.job.client_id) != shop_client_id
            )
        )

        total_revenue = float(sum(line.total_rev for line in cost_lines))
        total_cost = float(sum(line.total_cost for line in cost_lines))
        profit = total_revenue - total_cost

        # Calculate percentages and rates
        billable_percentage = (
            (billable_hours / total_hours * 100) if total_hours > 0 else 0
        )
        revenue_per_hour = (total_revenue / total_hours) if total_hours > 0 else 0
        profit_per_hour = (profit / total_hours) if total_hours > 0 else 0

        # Count unique jobs
        unique_jobs = set(line.cost_set.job.id for line in cost_lines)
        jobs_worked = len(unique_jobs)

        staff_metrics = {
            "staff_id": str(staff.id),
            "name": staff.get_display_full_name(),
            "total_hours": total_hours,
            "billable_hours": billable_hours,
            "billable_percentage": billable_percentage,
            "total_revenue": total_revenue,
            "total_cost": total_cost,
            "profit": profit,
            "revenue_per_hour": revenue_per_hour,
            "profit_per_hour": profit_per_hour,
            "jobs_worked": jobs_worked,
        }

        # Add job breakdown if requested
        if include_job_breakdown:
            job_breakdown = StaffPerformanceService._calculate_job_breakdown(cost_lines)
            staff_metrics["job_breakdown"] = job_breakdown

        return staff_metrics

    @staticmethod
    def _calculate_job_breakdown(cost_lines: models.QuerySet) -> List[Dict[str, Any]]:
        """
        Calculate job-level breakdown for cost lines.

        Args:
            cost_lines: QuerySet of CostLine entries

        Returns:
            List of job breakdown dictionaries
        """
        job_data = {}

        for line in cost_lines:
            job = line.cost_set.job
            job_id = str(job.id)

            if job_id not in job_data:
                job_data[job_id] = {
                    "job_id": job_id,
                    "job_number": job.job_number or "",
                    "job_name": job.name or "",
                    "client_name": job.client.name if job.client else "",
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "revenue": 0.0,
                    "cost": 0.0,
                }

            hours = float(line.quantity)
            # Shop jobs are always non-billable regardless of the is_billable flag
            shop_client_id = Client.get_shop_client_id()
            is_shop_job = str(line.cost_set.job.client_id) == shop_client_id
            is_billable = line.is_billable_meta == "true" and not is_shop_job

            if is_billable:
                job_data[job_id]["billable_hours"] += hours
            else:
                job_data[job_id]["non_billable_hours"] += hours

            job_data[job_id]["revenue"] += float(line.total_rev)
            job_data[job_id]["cost"] += float(line.total_cost)

        # Calculate derived fields
        for job in job_data.values():
            job["total_hours"] = job["billable_hours"] + job["non_billable_hours"]
            job["profit"] = job["revenue"] - job["cost"]
            job["revenue_per_hour"] = (
                job["revenue"] / job["total_hours"] if job["total_hours"] > 0 else 0
            )

        return list(job_data.values())

    @staticmethod
    def _calculate_team_averages(staff_data: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Calculate team average metrics.

        Args:
            staff_data: List of staff performance dictionaries

        Returns:
            Dict containing team average metrics
        """
        if not staff_data:
            return {
                "billable_percentage": 0.0,
                "revenue_per_hour": 0.0,
                "profit_per_hour": 0.0,
                "jobs_per_person": 0.0,
            }

        staff_count = len(staff_data)
        total_billable_percentage = sum(
            staff["billable_percentage"] for staff in staff_data
        )
        total_revenue_per_hour = sum(staff["revenue_per_hour"] for staff in staff_data)
        total_profit_per_hour = sum(staff["profit_per_hour"] for staff in staff_data)
        total_jobs = sum(staff["jobs_worked"] for staff in staff_data)

        # Calculate totals across all staff
        total_hours = sum(staff["total_hours"] for staff in staff_data)
        total_billable_hours = sum(staff["billable_hours"] for staff in staff_data)
        total_revenue = sum(staff["total_revenue"] for staff in staff_data)
        total_profit = sum(staff["profit"] for staff in staff_data)

        return {
            "billable_percentage": total_billable_percentage / staff_count,
            "revenue_per_hour": total_revenue_per_hour / staff_count,
            "profit_per_hour": total_profit_per_hour / staff_count,
            "jobs_per_person": total_jobs / staff_count,
            "total_hours": total_hours,
            "billable_hours": total_billable_hours,
            "total_revenue": total_revenue,
            "total_profit": total_profit,
        }
