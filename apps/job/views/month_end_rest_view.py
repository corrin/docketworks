import json
import logging

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.job_serializer import (
    MonthEndErrorResponseSerializer,
    MonthEndGetResponseSerializer,
    MonthEndPostResponseSerializer,
    MonthEndPostSerializer,
)
from apps.job.services.month_end_service import MonthEndService

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class MonthEndRestView(APIView):
    """
    REST API view for month-end processing of special jobs and stock data.

    GET: Returns special jobs data and stock job information for month-end review
    POST: Processes selected jobs for month-end archiving and status updates
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = MonthEndGetResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method == "GET":
            return MonthEndGetResponseSerializer
        elif self.request.method == "POST":
            return MonthEndPostResponseSerializer
        return MonthEndGetResponseSerializer

    def get(self, request):
        try:
            jobs = MonthEndService.get_special_jobs_data()
            stock = MonthEndService.get_stock_job_data()
            serialized_jobs = [
                {
                    "job_id": str(item["job"].id),
                    "job_number": item["job"].job_number,
                    "job_name": item["job"].name,
                    "client_name": (
                        item["job"].client.name if item["job"].client else ""
                    ),
                    "history": [
                        {
                            "date": h["date"].date(),
                            "total_hours": float(h["total_hours"]),
                            "total_dollars": float(h["total_dollars"]),
                        }
                        for h in item["history"]
                    ],
                    "total_hours": float(item["total_hours"]),
                    "total_dollars": float(item["total_dollars"]),
                }
                for item in jobs
            ]
            stock_serialized = {
                "job_id": str(stock["job"].id),
                "job_number": stock["job"].job_number,
                "job_name": stock["job"].name,
                "history": [
                    {
                        "date": h["date"].date(),
                        "material_line_count": h["material_line_count"],
                        "material_cost": float(h["material_cost"]),
                    }
                    for h in stock["history"]
                ],
            }

            response_data = {"jobs": serialized_jobs, "stock_job": stock_serialized}
            response_serializer = MonthEndGetResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.info(f"Error trying to get month-end information: {e}")
            return Response({}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        summary="Runs month-end operation based on given processed ids",
        request=MonthEndPostSerializer,
        responses={200: MonthEndPostResponseSerializer},
    )
    def post(self, request):
        try:
            # Validate input data
            input_serializer = MonthEndPostSerializer(data=request.data)
            if not input_serializer.is_valid():
                error_response = {"error": f"Invalid input: {input_serializer.errors}"}
                error_serializer = MonthEndErrorResponseSerializer(data=error_response)
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            job_ids = input_serializer.validated_data["job_ids"]
            processed, errors = MonthEndService.process_jobs(job_ids, request.user)

            response_data = {
                "processed": [str(job.id) for job in processed],
                "errors": errors,
            }
            response_serializer = MonthEndPostResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except json.JSONDecodeError:
            error_response = {"error": "Invalid JSON"}
            error_serializer = MonthEndErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)
