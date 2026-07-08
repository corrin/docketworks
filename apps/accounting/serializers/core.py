"""
Serializers for Accounting views.
"""

from typing import Any

from rest_framework import serializers


class KPICalendarErrorResponseSerializer(serializers.Serializer[Any]):
    """Serializer for KPI Calendar error responses."""

    error = serializers.CharField()


class KPIJobBreakdownSerializer(serializers.Serializer[Any]):
    """Serializer for job breakdown data in KPI calendar"""

    job_id = serializers.CharField()
    job_number = (
        serializers.CharField()
    )  # Changed to CharField to match frontend schema
    job_name = serializers.CharField()  # Changed from job_display_name
    company_name = serializers.CharField()  # Added company_name field
    billable_hours = serializers.FloatField()  # Added billable_hours field
    revenue = serializers.FloatField()
    cost = serializers.FloatField()
    profit = serializers.FloatField()
    labour_profit = serializers.FloatField()
    material_profit = serializers.FloatField()
    adjustment_profit = serializers.FloatField()


class KPIProfitBreakdownSerializer(serializers.Serializer[Any]):
    """Serializer for profit breakdown in KPI calendar details"""

    labor_profit = serializers.FloatField()
    material_profit = serializers.FloatField()
    adjustment_profit = serializers.FloatField()


class KPIDetailsSerializer(serializers.Serializer[Any]):
    """Serializer for detailed KPI data per day"""

    time_revenue = serializers.FloatField()
    material_revenue = serializers.FloatField()
    adjustment_revenue = serializers.FloatField()
    total_revenue = serializers.FloatField()
    staff_cost = serializers.FloatField()
    material_cost = serializers.FloatField()
    adjustment_cost = serializers.FloatField()
    total_cost = serializers.FloatField()
    profit_breakdown = KPIProfitBreakdownSerializer()
    job_breakdown = KPIJobBreakdownSerializer(many=True)


class KPIDayDataSerializer(serializers.Serializer[Any]):
    """Serializer for individual day data in KPI calendar"""

    date = serializers.DateField()
    day = serializers.IntegerField()
    holiday = serializers.BooleanField()
    holiday_name = serializers.CharField(required=False)
    billable_hours = serializers.FloatField()
    total_hours = serializers.FloatField()
    shop_hours = serializers.FloatField()
    shop_percentage = serializers.FloatField()
    gross_profit = serializers.FloatField()
    color = serializers.CharField()
    gp_target_achievement = serializers.FloatField()
    details = KPIDetailsSerializer()


class KPIMonthlyTotalsSerializer(serializers.Serializer[Any]):
    """Serializer for monthly totals in KPI calendar"""

    billable_hours = serializers.FloatField()
    total_hours = serializers.FloatField()
    shop_hours = serializers.FloatField()
    gross_profit = serializers.FloatField()
    days_green = serializers.IntegerField()
    days_amber = serializers.IntegerField()
    days_red = serializers.IntegerField()
    labour_green_days = serializers.IntegerField()
    labour_amber_days = serializers.IntegerField()
    labour_red_days = serializers.IntegerField()
    profit_green_days = serializers.IntegerField()
    profit_amber_days = serializers.IntegerField()
    profit_red_days = serializers.IntegerField()
    working_days = serializers.IntegerField()
    elapsed_workdays = serializers.IntegerField()
    active_workdays = serializers.IntegerField()
    remaining_workdays = serializers.IntegerField()
    time_revenue = serializers.FloatField()
    material_revenue = serializers.FloatField()
    adjustment_revenue = serializers.FloatField()
    staff_cost = serializers.FloatField()
    material_cost = serializers.FloatField()
    adjustment_cost = serializers.FloatField()
    material_profit = serializers.FloatField()
    adjustment_profit = serializers.FloatField()
    total_revenue = serializers.FloatField()
    total_cost = serializers.FloatField()
    elapsed_target = serializers.FloatField()
    net_profit = serializers.FloatField()
    billable_percentage = serializers.FloatField()
    shop_percentage = serializers.FloatField()
    avg_daily_gp = serializers.FloatField()
    avg_daily_gp_so_far = serializers.FloatField()
    avg_billable_hours_so_far = serializers.FloatField()
    color_hours = serializers.CharField()
    color_gp = serializers.CharField()
    color_shop = serializers.CharField()


class KPIThresholdsSerializer(serializers.Serializer[Any]):
    """Serializer for KPI thresholds"""

    kpi_daily_billable_hours_green = serializers.FloatField()
    kpi_daily_billable_hours_amber = serializers.FloatField()
    kpi_daily_gp_target = serializers.FloatField()
    kpi_daily_shop_hours_percentage = serializers.FloatField()
    kpi_daily_gp_green = serializers.FloatField()
    kpi_daily_gp_amber = serializers.FloatField()


class KPICalendarDataSerializer(serializers.Serializer[Any]):
    """Serializer for KPI Calendar data response."""

    calendar_data = serializers.DictField(child=KPIDayDataSerializer())
    monthly_totals = KPIMonthlyTotalsSerializer()
    thresholds = KPIThresholdsSerializer()
    year = serializers.IntegerField()
    month = serializers.IntegerField()


class JobAgingFinancialDataSerializer(serializers.Serializer[Any]):
    """Serialiser for job aging financial data"""

    estimate_total = serializers.FloatField()
    quote_total = serializers.FloatField()
    actual_total = serializers.FloatField()


class JobAgingTimingDataSerializer(serializers.Serializer[Any]):
    """Serialiser for job aging timing data"""

    created_date = serializers.DateField()
    created_days_ago = serializers.IntegerField()
    days_in_current_status = serializers.IntegerField()
    last_activity_date = serializers.DateTimeField(allow_null=True)
    last_activity_days_ago = serializers.IntegerField(allow_null=True)
    last_activity_type = serializers.CharField(allow_null=True, required=False)
    last_activity_description = serializers.CharField(allow_null=True, required=False)


class JobAgingJobDataSerializer(serializers.Serializer[Any]):
    """Serialiser for individual job aging data"""

    id = serializers.CharField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    company_name = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    financial_data = JobAgingFinancialDataSerializer()
    timing_data = JobAgingTimingDataSerializer()


class JobAgingResponseSerializer(serializers.Serializer[Any]):
    """Serialiser for job aging API response"""

    jobs = JobAgingJobDataSerializer(many=True)


class JobAgingQuerySerializer(serializers.Serializer[Any]):
    """Serialiser for job aging API query parameters"""

    include_archived = serializers.BooleanField(default=False, required=False)

    def validate_include_archived(self, value: Any) -> bool:
        """Validates and converts the include_archived parameter"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                return True
            elif value.lower() in ("false", "0", "no"):
                return False
            else:
                raise serializers.ValidationError(
                    "Invalid value for 'include_archived' parameter. "
                    "Expected: true, false, 1, 0, yes, or no."
                )
        return bool(value)


class StandardErrorSerializer(serializers.Serializer[Any]):
    """Standard serialiser for error responses"""

    error = serializers.CharField()
    details = serializers.JSONField(required=False)


class StaffPerformanceJobBreakdownSerializer(serializers.Serializer[Any]):
    """Serializer for job breakdown data in staff performance"""

    job_id = serializers.CharField()
    job_number = serializers.IntegerField()
    job_name = serializers.CharField()
    company_name = serializers.CharField()
    billable_hours = serializers.FloatField()
    non_billable_hours = serializers.FloatField()
    total_hours = serializers.FloatField()
    revenue = serializers.FloatField()
    cost = serializers.FloatField()
    profit = serializers.FloatField()
    revenue_per_hour = serializers.FloatField()


class StaffPerformanceTeamAveragesSerializer(serializers.Serializer[Any]):
    """Serializer for team average metrics"""

    billable_percentage = serializers.FloatField()
    revenue_per_hour = serializers.FloatField()
    profit_per_hour = serializers.FloatField()
    jobs_per_person = serializers.FloatField()
    total_hours = serializers.FloatField()
    billable_hours = serializers.FloatField()
    total_revenue = serializers.FloatField()
    total_profit = serializers.FloatField()


class StaffPerformanceStaffDataSerializer(serializers.Serializer[Any]):
    """Serializer for individual staff performance data"""

    staff_id = serializers.CharField()
    name = serializers.CharField()
    total_hours = serializers.FloatField()
    billable_hours = serializers.FloatField()
    billable_percentage = serializers.FloatField()
    total_revenue = serializers.FloatField()
    total_cost = serializers.FloatField()
    profit = serializers.FloatField()
    revenue_per_hour = serializers.FloatField()
    profit_per_hour = serializers.FloatField()
    jobs_worked = serializers.IntegerField()
    job_breakdown = StaffPerformanceJobBreakdownSerializer(many=True, required=False)


class StaffPerformancePeriodSummarySerializer(serializers.Serializer[Any]):
    """Serializer for period summary in staff performance report"""

    start_date = serializers.DateField()
    end_date = serializers.DateField()
    total_staff = serializers.IntegerField()
    period_description = serializers.CharField()


class StaffPerformanceResponseSerializer(serializers.Serializer[Any]):
    """Unified serializer for staff performance report responses"""

    team_averages = StaffPerformanceTeamAveragesSerializer()
    staff = StaffPerformanceStaffDataSerializer(many=True)
    period_summary = StaffPerformancePeriodSummarySerializer()


class StaffPerformanceErrorResponseSerializer(serializers.Serializer[Any]):
    """Serializer for staff performance error responses"""

    error = serializers.CharField()
    details = serializers.JSONField(required=False)
