"""
Modern Timesheet REST Views

REST views for the modern timesheet system using CostLine architecture.
Works directly with CostSet/CostLine models using JSONField queries.
"""

import logging
import traceback
from decimal import Decimal

from django.db import models, transaction
from django.db.models.fields.json import KeyTextTransform
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.job.models.costing import CostLine, CostSet
from apps.job.models.job import Job
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.costing_serializer import TimesheetCostLineSerializer
from apps.job.serializers.job_serializer import (
    ModernTimesheetDayGetResponseSerializer,
    ModernTimesheetEntryGetResponseSerializer,
    ModernTimesheetEntryPostResponseSerializer,
    ModernTimesheetEntryPostSerializer,
    ModernTimesheetErrorResponseSerializer,
    ModernTimesheetJobGetResponseSerializer,
)
from apps.workflow.models import XeroPayItem
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class ModernTimesheetEntryView(APIView):
    """
    Modern timesheet entry management using CostLine architecture

    GET /job/rest/timesheet/entries/?staff_id=<uuid>&date=<date>
    POST /job/rest/timesheet/entries/
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = ModernTimesheetEntryGetResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        match self.request.method:
            case "GET":
                return ModernTimesheetEntryGetResponseSerializer
            case "POST":
                return ModernTimesheetEntryPostResponseSerializer
            case _:
                return ModernTimesheetEntryGetResponseSerializer

    def get_serializer(self, *args, **kwargs):
        """Get the serializer instance for the current request for OpenAPI compatibility"""
        serializer_class = self.get_serializer_class()
        return serializer_class(*args, **kwargs)

    @extend_schema(
        summary="Get timesheet entries for a staff member on a specific date",
        description="Fetches all timesheet entries (CostLines) for a specific staff member and date.",
        parameters=[
            OpenApiParameter(
                name="staff_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="UUID of the staff member",
            ),
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Date in YYYY-MM-DD format",
            ),
        ],
        responses={
            status.HTTP_200_OK: ModernTimesheetEntryGetResponseSerializer,
            status.HTTP_400_BAD_REQUEST: ModernTimesheetErrorResponseSerializer,
            status.HTTP_404_NOT_FOUND: ModernTimesheetErrorResponseSerializer,
            status.HTTP_500_INTERNAL_SERVER_ERROR: ModernTimesheetErrorResponseSerializer,
        },
    )
    def get(self, request):
        """Get timesheet entries (CostLines) for a specific staff member and date"""
        staff_id = request.query_params.get("staff_id")
        entry_date = request.query_params.get("date")

        # Guard clauses for validation
        if not staff_id:
            error_response = {"error": "staff_id is required"}
            error_serializer = ModernTimesheetErrorResponseSerializer(
                data=error_response
            )
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)

        if not entry_date:
            error_response = {"error": "date is required"}
            error_serializer = ModernTimesheetErrorResponseSerializer(
                data=error_response
            )
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)

        # Validate staff exists
        try:
            staff = Staff.objects.get(id=staff_id)
        except Staff.DoesNotExist:
            error_response = {"error": "Staff member not found"}
            error_serializer = ModernTimesheetErrorResponseSerializer(
                data=error_response
            )
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

        # Validate date format
        parsed_date = parse_date(entry_date)
        if not parsed_date:
            error_response = {"error": "Invalid date format. Use YYYY-MM-DD"}
            error_serializer = ModernTimesheetErrorResponseSerializer(
                data=error_response
            )
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)

        try:
            logger.debug(
                f"Starting timesheet entries fetch for staff {staff_id}, date {entry_date}"
            )

            # Query CostLines with kind='time' for the staff/date
            cost_lines = (
                CostLine.objects.annotate(
                    staff_id_meta=KeyTextTransform("staff_id", "meta"),
                    calculated_total_cost=models.F("quantity") * models.F("unit_cost"),
                    calculated_total_rev=models.F("quantity") * models.F("unit_rev"),
                )
                .filter(
                    cost_set__kind="actual",
                    kind="time",
                    staff_id_meta=str(staff_id),
                    accounting_date=parsed_date,
                )
                .select_related("cost_set__job")
                .order_by("id")
            )

            logger.debug(f"Query SQL: {cost_lines.query}")
            entry_count = cost_lines.count()
            logger.debug(f"Found {entry_count} cost lines")

            # Debug first cost line
            if cost_lines.exists():
                first_line = cost_lines.first()
                logger.debug(f"First line type: {type(first_line)}")
                logger.debug(f"First line ID: {first_line.id}")
                logger.debug(f"First line meta: {first_line.meta}")
                logger.debug(f"First line quantity: {first_line.quantity}")
                logger.debug(f"First line unit_cost: {first_line.unit_cost}")
                logger.debug(
                    f"First line calculated_total_cost: {first_line.calculated_total_cost}"
                )
            else:
                logger.debug("No cost lines found!")
                # Let's check why - debug the filter conditions
                all_cost_lines = CostLine.objects.filter(
                    cost_set__kind="actual", kind="time"
                )
                logger.debug(
                    f"Total time cost lines in actual cost sets: {all_cost_lines.count()}"
                )

                for line in all_cost_lines[:5]:  # Check first 5
                    logger.debug(f"Line {line.id} meta: {line.meta}")
                    logger.debug(
                        f"Line {line.id} staff_id in meta: {line.meta.get('staff_id')}"
                    )
                    logger.debug(
                        f"Line {line.id} accounting_date: {line.accounting_date}"
                    )
                    logger.debug(f"Looking for staff_id={staff_id}, date={entry_date}")

            # Calculate totals
            logger.debug("Calculating totals...")
            try:
                total_hours = sum(Decimal(line.quantity) for line in cost_lines)
                logger.debug(f"Total hours calculated: {total_hours}")
            except Exception as e:
                logger.error(f"Error calculating total hours: {e}")
                raise

            try:
                billable_hours = sum(
                    Decimal(line.quantity)
                    for line in cost_lines
                    if line.meta.get("is_billable", True)
                )
                logger.debug(f"Billable hours calculated: {billable_hours}")
            except Exception as e:
                logger.error(f"Error calculating billable hours: {e}")
                raise

            try:
                total_cost = sum(line.calculated_total_cost for line in cost_lines)
                logger.debug(f"Total cost calculated: {total_cost}")
            except Exception as e:
                logger.error(f"Error calculating total cost: {e}")
                logger.error(f"First line type: {type(cost_lines.first())}")
                if cost_lines.exists():
                    first_line = cost_lines.first()
                    logger.error(
                        f"First line has calculated_total_cost: {hasattr(first_line, 'calculated_total_cost')}"
                    )
                    logger.error(
                        f"First line has total_cost: {hasattr(first_line, 'total_cost')}"
                    )
                raise

            try:
                total_revenue = sum(line.calculated_total_rev for line in cost_lines)
                logger.debug(f"Total revenue calculated: {total_revenue}")
            except Exception as e:
                logger.error(f"Error calculating total revenue: {e}")
                raise
            response_data = {
                "cost_lines": cost_lines,
                "staff": {
                    "id": str(staff.id),
                    "name": f"{staff.first_name} {staff.last_name}",
                    "firstName": staff.first_name,
                    "lastName": staff.last_name,
                },
                "date": parsed_date,
                "summary": {
                    "total_hours": float(total_hours),
                    "billable_hours": float(billable_hours),
                    "non_billable_hours": float(total_hours - billable_hours),
                    "total_cost": float(total_cost),
                    "total_revenue": float(total_revenue),
                    "entry_count": len(cost_lines),
                    "scheduled_hours": float(staff.get_scheduled_hours(parsed_date)),
                },
            }

            response_serializer = ModernTimesheetEntryGetResponseSerializer(
                response_data
            )
            logger.info(
                f"Fetched {entry_count} timesheet entries for staff {staff_id}, date {entry_date}"
            )
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(
                f"Error fetching timesheet entries for staff {staff_id}, date {entry_date}: {e}"
            )
            error_response = {"error": "Failed to fetch timesheet entries"}
            error_serializer = ModernTimesheetErrorResponseSerializer(
                data=error_response
            )
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        summary="Create a timesheet entry as a CostLine",
        description="Creates a new timesheet entry for a staff member on a specific date.",
        request=ModernTimesheetEntryPostSerializer,
        responses={
            status.HTTP_201_CREATED: ModernTimesheetEntryPostResponseSerializer,
            status.HTTP_400_BAD_REQUEST: ModernTimesheetErrorResponseSerializer,
            status.HTTP_404_NOT_FOUND: ModernTimesheetErrorResponseSerializer,
            status.HTTP_500_INTERNAL_SERVER_ERROR: ModernTimesheetErrorResponseSerializer,
        },
    )
    def post(self, request):
        """Create a timesheet entry as a CostLine in the actual CostSet"""
        try:
            # Validate input data using serializer
            input_serializer = ModernTimesheetEntryPostSerializer(data=request.data)
            if not input_serializer.is_valid():
                error_response = {"error": f"Invalid input: {input_serializer.errors}"}
                error_serializer = ModernTimesheetErrorResponseSerializer(
                    data=error_response
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            # Extract validated data
            validated_data = input_serializer.validated_data
            job_id = validated_data["job_id"]
            staff_id = validated_data["staff_id"]
            hours = validated_data["hours"]
            entry_date = validated_data["date"]
            description = validated_data["description"]
            is_billable = validated_data.get("is_billable", True)
            hourly_rate = validated_data.get("hourly_rate")
            xero_pay_item_id = validated_data["xero_pay_item_id"]
            if not entry_date:
                return Response(
                    {"error": "entry_date must be in YYYY-MM-DD format"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get job and staff with error handling
            try:
                job = Job.objects.get(id=job_id)
            except Job.DoesNotExist:
                return Response(
                    {"error": f"Job {job_id} not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Get job
            try:
                job = Job.objects.get(id=job_id)
            except Job.DoesNotExist:
                error_response = {"error": f"Job {job_id} not found"}
                error_serializer = ModernTimesheetErrorResponseSerializer(
                    data=error_response
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

            # Get staff
            try:
                staff = Staff.objects.get(id=staff_id)
            except Staff.DoesNotExist:
                error_response = {"error": f"Staff {staff_id} not found"}
                error_serializer = ModernTimesheetErrorResponseSerializer(
                    data=error_response
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

            # Get rate multiplier from the selected XeroPayItem
            xero_pay_item = XeroPayItem.objects.get(id=xero_pay_item_id)
            rate_multiplier = xero_pay_item.multiplier
            if rate_multiplier is None:
                raise ValueError(
                    f"XeroPayItem '{xero_pay_item.name}' has NULL multiplier — "
                    f"re-run Xero pay item sync to fix"
                )

            # Get rates from staff and job
            wage_rate = hourly_rate if hourly_rate else staff.wage_rate
            charge_out_rate = job.charge_out_rate

            # Create CostLine directly
            with transaction.atomic():
                # Get or create actual cost set for the job
                cost_set, created = CostSet.objects.get_or_create(
                    job=job, kind="actual", defaults={"rev": 1, "summary": {}}
                )

                if not created:
                    # If cost set exists, increment revision if needed
                    latest_rev = (
                        CostSet.objects.filter(job=job, kind="actual")
                        .order_by("-rev")
                        .first()
                        .rev
                    )
                    cost_set.rev = latest_rev

                # Calculate costs
                hours_decimal = Decimal(str(hours))
                unit_cost = wage_rate * rate_multiplier
                unit_rev = (
                    charge_out_rate * rate_multiplier if is_billable else Decimal("0")
                )

                # Create the cost line
                cost_line = CostLine.objects.create(
                    cost_set=cost_set,
                    kind="time",
                    desc=description
                    or f"Timesheet entry for {staff.get_display_name()}",
                    quantity=hours_decimal,
                    unit_cost=unit_cost,
                    unit_rev=unit_rev,
                    accounting_date=entry_date,
                    xero_pay_item_id=xero_pay_item_id,
                    ext_refs={},
                    meta={
                        "staff_id": str(staff_id),
                        "date": entry_date.isoformat(),
                        "is_billable": is_billable,
                        "wage_rate": float(wage_rate),
                        "charge_out_rate": float(charge_out_rate),
                        "wage_rate_multiplier": float(rate_multiplier),
                        "created_from_timesheet": True,
                    },
                )

                # Update job's latest_actual pointer if this is the most recent
                if not job.latest_actual or cost_set.rev >= job.latest_actual.rev:
                    job.latest_actual = cost_set
                    job.save(update_fields=["latest_actual"])

            # Return success response
            response_data = {
                "success": True,
                "cost_line_id": str(cost_line.id),
                "message": "Timesheet entry created successfully",
            }
            response_serializer = ModernTimesheetEntryPostResponseSerializer(
                data=response_data
            )
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            persist_app_error(e)
            logger.error(f"Error creating timesheet entry: {e}")
            error_response = {"error": "Failed to create timesheet entry"}
            error_serializer = ModernTimesheetErrorResponseSerializer(
                data=error_response
            )
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ModernTimesheetDayView(APIView):
    """
    Get timesheet entries for a specific day and staff

    GET /job/rest/timesheet/staff/<staff_id>/date/<date>/
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = ModernTimesheetDayGetResponseSerializer

    def get(self, request, staff_id, entry_date):
        """Get all cost lines for a staff member on a specific date"""
        try:
            # Parse date
            parsed_date = parse_date(entry_date)
            if not parsed_date:
                return Response(
                    {"error": "date must be in YYYY-MM-DD format"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate staff exists
            try:
                staff = Staff.objects.get(id=staff_id)
            except Staff.DoesNotExist:
                return Response(
                    {"error": f"Staff {staff_id} not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            logger.info(
                f"Starting timesheet retrieval for staff {staff_id}, date {entry_date}"
            )

            # Find all cost lines for this staff on this date
            cost_lines = (
                CostLine.objects.annotate(
                    staff_id_meta=KeyTextTransform("staff_id", "meta"),
                    calculated_total_cost=models.F("quantity") * models.F("unit_cost"),
                    calculated_total_rev=models.F("quantity") * models.F("unit_rev"),
                )
                .filter(
                    cost_set__kind="actual",
                    kind="time",
                    staff_id_meta=str(staff_id),
                    accounting_date=parsed_date,
                )
                .select_related("cost_set__job")
                .order_by("id")
            )

            logger.info(f"Found {cost_lines.count()} cost lines for staff timesheet")
            # Serialize the cost lines using timesheet-specific serializer
            serializer = TimesheetCostLineSerializer(cost_lines, many=True)

            return Response(
                {
                    "staff_id": str(staff_id),
                    "staff_name": f"{staff.first_name} {staff.last_name}",
                    "entry_date": entry_date,
                    "cost_lines": serializer.data,
                    "total_hours": sum(float(line.quantity) for line in cost_lines),
                    "total_cost": sum(
                        float(line.calculated_total_cost) for line in cost_lines
                    ),
                    "total_revenue": sum(
                        float(line.calculated_total_rev) for line in cost_lines
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(
                f"Error retrieving timesheet day for staff {staff_id}, date {entry_date}: {e}"
            )
            return Response(
                {"error": "Failed to retrieve timesheet data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ModernTimesheetJobView(APIView):
    """
    Get timesheet entries for a specific job

    GET /job/rest/timesheet/jobs/<job_id>/
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = ModernTimesheetJobGetResponseSerializer

    def get(self, request, job_id):
        """Get all timesheet cost lines for a job"""
        try:
            # Validate job exists
            job = get_object_or_404(Job, id=job_id)

            logger.info(f"Starting timesheet retrieval for job {job_id}")

            # Get timesheet cost lines for this job
            timesheet_lines = (
                CostLine.objects.annotate(
                    calculated_total_cost=models.F("quantity") * models.F("unit_cost"),
                    calculated_total_rev=models.F("quantity") * models.F("unit_rev"),
                )
                .filter(
                    cost_set__job=job,
                    cost_set__kind="actual",
                    kind="time",
                    meta__created_from_timesheet=True,
                )
                .order_by("id")
            )

            logger.info(f"Found {timesheet_lines.count()} timesheet lines for job")

            # Serialize the cost lines using timesheet-specific serializer
            serializer = TimesheetCostLineSerializer(timesheet_lines, many=True)

            return Response(
                {
                    "job_id": str(job_id),
                    "job_name": job.name,
                    "job_number": job.job_number,
                    "cost_lines": serializer.data,
                    "total_hours": sum(
                        float(line.quantity) for line in timesheet_lines
                    ),
                    "total_cost": sum(
                        float(line.calculated_total_cost) for line in timesheet_lines
                    ),
                    "total_revenue": sum(
                        float(line.calculated_total_rev) for line in timesheet_lines
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error retrieving timesheet entries for job {job_id}: {e}")
            return Response(
                {"error": "Failed to retrieve timesheet entries"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
