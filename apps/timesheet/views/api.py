"""
REST API views for timesheet functionality.
Provides endpoints for the Vue.js frontend to interact with timesheet data.
"""

import json
import logging
import os
import uuid as uuid_module
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.accounts.utils import get_displayable_staff
from apps.client.serializers import ClientErrorResponseSerializer
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.serializers import (
    DailyTimesheetSummarySerializer,
    JobsListResponseSerializer,
    ModernTimesheetJobSerializer,
    StaffListResponseSerializer,
    WeeklyTimesheetDataSerializer,
)
from apps.timesheet.serializers.payroll_serializers import (
    CreatePayRunResponseSerializer,
    CreatePayRunSerializer,
    PayRunListResponseSerializer,
    PayRunSyncResponseSerializer,
    PostWeekToXeroSerializer,
)
from apps.timesheet.services.daily_timesheet_service import DailyTimesheetService
from apps.timesheet.services.weekly_timesheet_service import WeeklyTimesheetService
from apps.workflow.api.xero.payroll import (
    get_all_timesheets_for_week,
    get_payroll_calendar_id,
    post_staff_week_to_xero,
    validate_pay_items_for_week,
)
from apps.workflow.api.xero.sync import sync_all_xero_data
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults, XeroPayRun
from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.utils import build_xero_payroll_url

logger = logging.getLogger(__name__)


def _require_authenticated_api(request) -> JsonResponse | None:
    """
    Authentication guard for API endpoints.
    Returns 401 JSON if not authenticated, None if OK.
    """
    if not request.user.is_authenticated:
        logger.warning(f"API guard rejected unauthenticated request to {request.path}")
        return JsonResponse(
            {"detail": "Authentication credentials were not provided."},
            status=401,
        )
    return None


def build_internal_error_response(
    *,
    request,
    message: str,
    exc: Exception,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    staff_only_details: bool = False,
):
    """
    Construct a consistent error response while ensuring exceptions are persisted once.
    """
    if isinstance(exc, AlreadyLoggedException):
        root_exception = exc.original
        error_id = exc.app_error_id
    else:
        app_error = persist_app_error(exc)
        error_id = getattr(app_error, "id", None)
        root_exception = exc

    logger.error(f"{message}: {root_exception}", exc_info=True)

    payload = {"error": message}
    details_text = str(root_exception)
    if staff_only_details and request is not None:
        payload["details"] = (
            details_text if request.user.is_office_staff else "Internal server error"
        )
    else:
        payload["details"] = details_text

    if error_id:
        payload["error_id"] = str(error_id)

    return Response(payload, status=status_code)


class StaffListAPIView(APIView):
    """API endpoint to get filtered list of staff members for timesheet operations.

    Returns staff members excluding those with invalid Xero payroll IDs
    (admin/system users), formatted for timesheet entry forms and interfaces.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = StaffListResponseSerializer

    @extend_schema(
        summary="Returns staff members excluding system and users for a specific date",
        parameters=[
            OpenApiParameter(
                "date",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Date parameter in format YYYY-MM-DD",
            )
        ],
    )
    def get(self, request):
        """Get filtered list of staff members for a specific date."""
        try:
            # Add required date parameter
            date_param = request.query_params.get("date") or datetime.now().strftime(
                "%Y-%m-%d"
            )
            if not date_param:
                logger.error("Date parameter not received in StaffListAPIView")
                return Response(
                    {"error": "date parameter is required (YYYY-MM-DD format)"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                target_date = datetime.strptime(date_param, "%Y-%m-%d").date()
            except ValueError:
                logger.info(f"Invalid date format received: {date_param}")
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Use date-based filtering
            staff = get_displayable_staff(target_date=target_date)

            staff_data = []
            for member in staff:
                staff_data.append(
                    {
                        "id": str(member.id),
                        "name": member.get_display_name() or "Unknown",
                        "firstName": member.first_name or "",
                        "lastName": member.last_name or "",
                        "email": member.email or "",
                        "wageRate": (
                            Decimal(member.wage_rate)
                            if member.wage_rate
                            else Decimal(0)
                        ),
                        # Provide canonical icon URL for avatar rendering
                        "iconUrl": member.icon.url if member.icon else None,
                    }
                )

            return Response({"staff": staff_data, "total_count": len(staff_data)})

        except Exception as exc:
            return build_internal_error_response(
                request=request,
                message="Failed to fetch staff list",
                exc=exc,
            )


class JobsAPIView(APIView):
    """API endpoint to get available jobs for timesheet entries."""

    permission_classes = [IsAuthenticated]
    serializer_class = JobsListResponseSerializer

    def get(self, request):
        """Get list of active jobs for timesheet entries using CostSet system."""
        try:
            # Get active jobs - exclude archived only
            jobs = (
                Job.objects.filter(
                    status__in=[
                        "draft",
                        "awaiting_approval",
                        "approved",
                        "in_progress",
                        "unusual",
                        "recently_completed",
                        "special",
                    ]
                )
                .select_related("client")
                .prefetch_related("cost_sets")  # Prefetch cost sets for efficiency
                .order_by("job_number")
            )

            # Filter jobs that have actual CostSet (for timesheet entries)
            # We create actual CostSet on-demand when needed
            jobs_with_actual_costset = []
            for job in jobs:
                # Temporarily include all jobs to debug the issue
                jobs_with_actual_costset.append(job)

            if not jobs_with_actual_costset:
                return Response({"jobs": [], "total_count": 0})

            serializer = ModernTimesheetJobSerializer(
                jobs_with_actual_costset, many=True
            )
            return Response(
                {"jobs": serializer.data, "total_count": len(serializer.data)}
            )

        except Exception as exc:
            return build_internal_error_response(
                request=request,
                message="Failed to fetch jobs",
                exc=exc,
            )


class DailyTimesheetAPIView(APIView):
    """
    API endpoint for daily timesheet overview.
    Provides comprehensive daily summary using modern CostLine system.
    Supports weekend functionality when feature flag is enabled.

    Supports multiple URL patterns:
    - GET /timesheets/api/daily/ (today's data)
    - GET /timesheets/api/daily/{date}/ (specific date)
    - GET /timesheets/api/staff/{staff_id}/daily/ (staff detail today)
    - GET /timesheets/api/staff/{staff_id}/daily/?date={date} (specific)
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DailyTimesheetSummarySerializer

    def get(self, request, date=None, staff_id=None):
        """
        Get daily timesheet overview.

        Args:
            date: Optional date from URL path
            staff_id: Optional staff ID from URL path

        Query Parameters:
            date (optional): Date in YYYY-MM-DD format. Defaults to today.

        Returns:
            JSON response with daily timesheet data
        """
        try:
            # Determine target date - from URL path, query param, or today
            date_param = date or request.query_params.get("date")

            if date_param:
                try:
                    target_date = datetime.strptime(date_param, "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"error": "Invalid date format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                target_date = date.today()

            # If staff_id is provided, return staff-specific data
            if staff_id:
                return self._get_staff_daily_detail(staff_id, target_date, request)

            # Otherwise return full daily summary
            logger.info(f"Getting daily timesheet overview for {target_date}")

            # Delegate to service layer for business logic
            summary_data = DailyTimesheetService.get_daily_summary(target_date)

            # Add weekend information to response
            weekend_enabled = self._is_weekend_enabled()
            is_weekend = target_date.weekday() >= 5
            summary_data["weekend_enabled"] = weekend_enabled
            summary_data["is_weekend"] = is_weekend
            summary_data["day_type"] = "weekend" if is_weekend else "weekday"

            # Serialize and return response
            serializer = DailyTimesheetSummarySerializer(summary_data)

            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as exc:
            return build_internal_error_response(
                request=request,
                message="Failed to get daily timesheet overview",
                exc=exc,
                staff_only_details=True,
            )

    def _get_staff_daily_detail(self, staff_id, target_date, request):
        """Get detailed daily data for a specific staff member."""
        try:
            # Validate staff exists
            try:
                staff = Staff.objects.get(id=staff_id)
            except Staff.DoesNotExist:
                return Response(
                    {"error": "Staff member not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            logger.info(f"Getting daily detail for staff {staff_id} on {target_date}")

            # Get summary data and extract specific staff
            summary_data = DailyTimesheetService.get_daily_summary(target_date)

            # Find the staff member in the summary data
            staff_data = None
            for staff_info in summary_data.get("staff_data", []):
                if staff_info.get("staff_id") == str(staff_id):
                    staff_data = staff_info
                    break

            if not staff_data:
                # Staff exists but has no timesheet data for this date
                weekend_enabled = self._is_weekend_enabled()
                is_weekend = target_date.weekday() >= 5

                # Adjust scheduled hours based on weekend feature flag
                if is_weekend and not weekend_enabled:
                    scheduled_hours = 0.0
                else:
                    scheduled_hours = float(staff.get_scheduled_hours(target_date))

                initials = f"{staff.first_name[0]}{staff.last_name[0]}".upper()
                staff_data = {
                    "staff_id": str(staff_id),
                    "staff_name": f"{staff.first_name} {staff.last_name}",
                    "staff_initials": initials,
                    "icon": None,
                    "scheduled_hours": scheduled_hours,
                    "actual_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "total_revenue": 0.0,
                    "total_cost": 0.0,
                    "status": (
                        "Weekend" if is_weekend and not weekend_enabled else "No Entry"
                    ),
                    "status_class": (
                        "secondary" if is_weekend and not weekend_enabled else "danger"
                    ),
                    "billable_percentage": 0.0,
                    "completion_percentage": 0.0,
                    "job_breakdown": [],
                    "entry_count": 0,
                    "alerts": ["No timesheet entries for this date"],
                    "is_weekend": is_weekend,
                    "weekend_enabled": weekend_enabled,
                }
            else:
                # Add weekend information to existing staff data
                weekend_enabled = self._is_weekend_enabled()
                is_weekend = target_date.weekday() >= 5
                staff_data["is_weekend"] = is_weekend
                staff_data["weekend_enabled"] = weekend_enabled

            return Response(staff_data, status=status.HTTP_200_OK)

        except Exception as exc:
            return build_internal_error_response(
                request=request,
                message="Failed to get staff daily detail",
                exc=exc,
                staff_only_details=True,
            )


class TimesheetResponseMixin:
    def build_timesheet_response(self, request):
        """Builds the weekly timesheet response data with payroll fields."""
        try:
            start_str = request.query_params.get("start_date")
            if start_str:
                try:
                    start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"error": "Invalid start_date format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                # Default to current week
                today = datetime.today().date()
                start_date = today - timedelta(days=today.weekday())

            # Check weekend feature flag
            weekend_enabled = self._is_weekend_enabled()

            weekly_data = WeeklyTimesheetService.get_weekly_overview(start_date)

            prev_week = start_date - timedelta(days=7)
            next_week = start_date + timedelta(days=7)
            weekly_data["navigation"] = {
                "prev_week_date": prev_week.isoformat(),
                "next_week_date": next_week.isoformat(),
                "current_week_date": start_date.isoformat(),
            }

            # Add feature flag info to response
            weekly_data["weekend_enabled"] = weekend_enabled
            weekly_data["week_type"] = "7-day" if weekend_enabled else "5-day"

            return Response(
                WeeklyTimesheetDataSerializer(weekly_data).data,
                status=status.HTTP_200_OK,
            )

        except Exception as exc:
            return build_internal_error_response(
                request=request,
                message="Failed to build weekly timesheet response",
                exc=exc,
                staff_only_details=True,
            )

    def _is_weekend_enabled(self):
        """Check if weekend timesheet functionality is enabled"""
        return os.getenv("WEEKEND_TIMESHEETS_ENABLED", "false").lower() == "true"


class WeeklyTimesheetAPIView(TimesheetResponseMixin, APIView):
    """
    Comprehensive weekly timesheet API endpoint using WeeklyTimesheetService.
    Provides weekly overview with payroll fields for Vue.js frontend.
    Supports both 5-day (Mon-Fri) and 7-day (Mon-Sun) modes via flag.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = WeeklyTimesheetDataSerializer

    @extend_schema(
        summary="Weekly overview with payroll data (Mon–Sun/Mon–Fri)",
        parameters=[
            OpenApiParameter(
                "start_date",
                OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="Monday of target week in YYYY-MM-DD format. "
                "Defaults to current week.",
            ),
        ],
        responses={
            200: WeeklyTimesheetDataSerializer,
            400: ClientErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
    )
    def get(self, request):
        """Return weekly timesheet data with payroll fields (5/7 days)."""
        return self.build_timesheet_response(request)


class CreatePayRunAPIView(APIView):
    """API endpoint to create a pay run in Xero Payroll."""

    permission_classes = [IsAuthenticated]
    serializer_class = CreatePayRunSerializer

    @extend_schema(
        summary="Create pay run for a week",
        request=CreatePayRunSerializer,
        responses={
            201: CreatePayRunResponseSerializer,
            400: ClientErrorResponseSerializer,
            409: ClientErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
    )
    def post(self, request):
        """Create a new pay run for the specified week."""
        from django.utils import timezone

        from apps.workflow.api.xero.payroll import create_pay_run

        data = request.data
        week_start_date_str = data.get("week_start_date")

        if not week_start_date_str:
            return Response(
                {"error": "week_start_date is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Parse date
        try:
            week_start_date = datetime.strptime(week_start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Create pay run in Xero (validates Monday)
            result = create_pay_run(week_start_date)
            xero_pay_run_id = result["pay_run_id"]
            payroll_calendar_id = result["payroll_calendar_id"]

            # Calculate dates
            week_end_date = week_start_date + timedelta(days=6)
            payment_date = week_end_date + timedelta(days=3)

            # Get tenant ID and shortcode from company defaults
            company_defaults = CompanyDefaults.get_solo()
            tenant_id = company_defaults.xero_tenant_id
            if not tenant_id:
                raise ValueError("Xero tenant ID not configured in CompanyDefaults")
            if not company_defaults.xero_shortcode:
                raise ValueError(
                    "Xero shortcode not configured. Run 'python manage.py xero --setup' to fetch it."
                )

            # Create local record immediately
            now = timezone.now()
            pay_run = XeroPayRun.objects.create(
                xero_id=xero_pay_run_id,
                xero_tenant_id=tenant_id,
                payroll_calendar_id=payroll_calendar_id,
                period_start_date=week_start_date,
                period_end_date=week_end_date,
                payment_date=payment_date,
                pay_run_status="Draft",
                pay_run_type="Scheduled",
                raw_json={"created_locally": True, "xero_id": str(xero_pay_run_id)},
                xero_last_modified=now,
                xero_last_synced=now,
            )

            xero_url = build_xero_payroll_url(str(xero_pay_run_id))

            return Response(
                {
                    "id": str(pay_run.id),
                    "xero_id": str(xero_pay_run_id),
                    "status": "Draft",
                    "period_start_date": week_start_date.isoformat(),
                    "period_end_date": week_end_date.isoformat(),
                    "payment_date": payment_date.isoformat(),
                    "xero_url": xero_url,
                },
                status=status.HTTP_201_CREATED,
            )

        except ValueError as exc:
            # Client errors (bad date, not Monday)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            error_msg = str(exc)
            if "only be one draft pay run" in error_msg.lower():
                logger.warning("Draft pay run already exists: %s", error_msg)
                return Response({"error": error_msg}, status=status.HTTP_409_CONFLICT)

            return build_internal_error_response(
                request=request,
                message="Failed to create pay run",
                exc=exc,
            )


class PayRunListAPIView(APIView):
    """API endpoint to list all pay runs for the configured payroll calendar."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="List pay runs",
        responses={
            200: PayRunListResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
    )
    def get(self, request):
        """Return all pay runs for the configured payroll calendar."""
        calendar_id = get_payroll_calendar_id()

        pay_runs = XeroPayRun.objects.filter(payroll_calendar_id=calendar_id).order_by(
            "-period_end_date"
        )

        return Response(
            {
                "pay_runs": [
                    {
                        "id": str(pr.id),
                        "xero_id": str(pr.xero_id),
                        "period_start_date": pr.period_start_date,
                        "period_end_date": pr.period_end_date,
                        "payment_date": pr.payment_date,
                        "pay_run_status": pr.pay_run_status,
                        "xero_url": build_xero_payroll_url(str(pr.xero_id)),
                    }
                    for pr in pay_runs
                ]
            },
            status=status.HTTP_200_OK,
        )


class RefreshPayRunsAPIView(APIView):
    """API endpoint to refresh cached pay runs from Xero."""

    permission_classes = [IsAuthenticated]
    serializer_class = PayRunSyncResponseSerializer

    @extend_schema(
        summary="Refresh cached pay runs from Xero",
        responses={
            200: PayRunSyncResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
    )
    def post(self, request):
        """Synchronize local pay run cache with Xero."""
        try:
            # sync_all_xero_data is a generator - must consume it to run the sync
            fetched = 0
            for event in sync_all_xero_data(entities=["pay_runs"]):
                # Count records from sync events
                if "recordsUpdated" in event:
                    fetched += event["recordsUpdated"]

            return Response(
                {"synced": True, "fetched": fetched, "created": 0, "updated": fetched},
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            return build_internal_error_response(
                request=request,
                message="Failed to refresh pay runs",
                exc=exc,
            )


# Cache timeout for payroll task data (10 minutes)
PAYROLL_TASK_TIMEOUT = 600


class PostWeekToXeroPayrollAPIView(APIView):
    """API endpoint to start posting weekly timesheets to Xero Payroll."""

    permission_classes = [IsAuthenticated]
    serializer_class = PostWeekToXeroSerializer

    @extend_schema(
        summary="Start posting weekly timesheets to Xero Payroll",
        request=PostWeekToXeroSerializer,
        responses={200: None},
    )
    def post(self, request):
        """
        Start posting timesheets. Returns a task_id to use with the stream endpoint.

        Use GET /api/payroll/post-staff-week/stream/{task_id}/ to receive SSE progress.
        """
        data = request.data
        staff_ids = data.get("staff_ids", [])
        week_start_date_str = data.get("week_start_date")

        if not staff_ids:
            return Response(
                {"error": "staff_ids is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not week_start_date_str:
            return Response(
                {"error": "week_start_date is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Parse date
        try:
            week_start_date = datetime.strptime(week_start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate Monday
        if week_start_date.weekday() != 0:
            return Response(
                {"error": "week_start_date must be a Monday"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Generate task ID and store task data in cache
        task_id = str(uuid_module.uuid4())
        task_data = {
            "staff_ids": [str(sid) for sid in staff_ids],
            "week_start_date": week_start_date_str,
            "status": "pending",
        }
        cache.set(f"payroll_task_{task_id}", task_data, timeout=PAYROLL_TASK_TIMEOUT)

        return Response(
            {
                "task_id": task_id,
                "stream_url": f"/api/timesheets/payroll/post-staff-week/stream/{task_id}/",
            }
        )


@csrf_exempt
@require_GET
def stream_payroll_post(request, task_id):
    """
    SSE endpoint to stream payroll posting progress.

    Connect with: new EventSource('/api/timesheets/payroll/post-staff-week/stream/{task_id}/')
    """
    # Check authentication - return 401 JSON instead of redirect for API endpoints
    guard = _require_authenticated_api(request)
    if guard:
        return guard

    # Retrieve task data from cache
    task_data = cache.get(f"payroll_task_{task_id}")

    if not task_data:
        return StreamingHttpResponse(
            f"data: {json.dumps({'event': 'error', 'message': 'Task not found or expired'})}\n\n",
            content_type="text/event-stream",
        )

    staff_ids = task_data["staff_ids"]
    week_start_date = datetime.strptime(task_data["week_start_date"], "%Y-%m-%d").date()

    def generate_payroll_events():
        """SSE generator yielding progress as each employee is processed."""
        total = len(staff_ids)
        successful = 0
        failed = 0

        # Starting event
        yield f"data: {json.dumps({'event': 'start', 'total': total, 'datetime': timezone.now().isoformat()})}\n\n"

        # FAIL EARLY: Validate ALL required pay items exist for ALL staff
        # before making any modifying API calls
        try:
            staff_uuids = [uuid_module.UUID(sid) for sid in staff_ids]
            validate_pay_items_for_week(staff_uuids, week_start_date)
        except ValueError as exc:
            logger.error("Pay item validation failed: %s", exc)
            persist_app_error(exc)
            yield f"data: {json.dumps({'event': 'error', 'message': str(exc), 'datetime': timezone.now().isoformat()})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'successful': 0, 'failed': total, 'datetime': timezone.now().isoformat()})}\n\n"
            return

        # Fetch all existing timesheets for the week in ONE API call
        try:
            existing_timesheets = get_all_timesheets_for_week(week_start_date)
        except Exception as exc:
            logger.exception("Failed to fetch existing timesheets")
            persist_app_error(exc)
            yield f"data: {json.dumps({'event': 'error', 'message': str(exc), 'datetime': timezone.now().isoformat()})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'successful': 0, 'failed': total, 'datetime': timezone.now().isoformat()})}\n\n"
            return

        # Process each employee
        for i, staff_id in enumerate(staff_ids):
            staff_name = "Unknown"
            try:
                staff = Staff.objects.get(id=staff_id)
                staff_name = staff.get_display_full_name()

                # Skip inactive staff - Xero payroll API rejects them
                if staff.date_left is not None:
                    # Only warn if they actually have entries we're skipping
                    week_end_date = week_start_date + timedelta(days=6)
                    has_entries = CostLine.objects.filter(
                        kind="time",
                        accounting_date__gte=week_start_date,
                        accounting_date__lte=week_end_date,
                        meta__staff_id=str(staff_id),
                    ).exists()
                    if has_entries:
                        logger.warning(
                            f"Skipping inactive staff {staff_name} (left {staff.date_left}) "
                            "who has time entries - handle manually in Xero"
                        )
                    yield f"data: {json.dumps({'event': 'complete', 'staff_id': str(staff_id), 'staff_name': staff_name, 'success': True, 'skipped': True, 'reason': 'Staff no longer active', 'has_entries': has_entries, 'datetime': timezone.now().isoformat()})}\n\n"
                    continue

                # Progress event
                yield f"data: {json.dumps({'event': 'progress', 'staff_id': str(staff_id), 'staff_name': staff_name, 'current': i + 1, 'total': total, 'datetime': timezone.now().isoformat()})}\n\n"

                # Get pre-fetched existing timesheet for this employee
                xero_employee_id = staff.xero_user_id
                existing = (
                    existing_timesheets.get(str(xero_employee_id))
                    if xero_employee_id
                    else None
                )

                # Post to Xero
                result = post_staff_week_to_xero(
                    staff_id=staff_id,
                    week_start_date=week_start_date,
                    existing_timesheet=existing,
                )

                if result["success"]:
                    successful += 1
                    yield f"data: {json.dumps({'event': 'complete', 'staff_id': str(staff_id), 'staff_name': staff_name, 'success': True, 'work_hours': str(result.get('work_hours', 0)), 'datetime': timezone.now().isoformat()})}\n\n"
                else:
                    failed += 1
                    yield f"data: {json.dumps({'event': 'complete', 'staff_id': str(staff_id), 'staff_name': staff_name, 'success': False, 'errors': result.get('errors', []), 'datetime': timezone.now().isoformat()})}\n\n"

            except Staff.DoesNotExist:
                failed += 1
                yield f"data: {json.dumps({'event': 'complete', 'staff_id': str(staff_id), 'staff_name': 'Unknown', 'success': False, 'errors': ['Staff not found'], 'datetime': timezone.now().isoformat()})}\n\n"

            except Exception as exc:
                persist_app_error(exc)
                failed += 1
                yield f"data: {json.dumps({'event': 'complete', 'staff_id': str(staff_id), 'staff_name': staff_name, 'success': False, 'errors': [str(exc)], 'datetime': timezone.now().isoformat()})}\n\n"

        # Final event
        yield f"data: {json.dumps({'event': 'done', 'successful': successful, 'failed': failed, 'total': total, 'datetime': timezone.now().isoformat()})}\n\n"

        # Clean up task data
        cache.delete(f"payroll_task_{task_id}")

    response = StreamingHttpResponse(
        generate_payroll_events(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    response["Content-Encoding"] = "identity"
    return response
