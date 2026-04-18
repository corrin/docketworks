"""
Quote Sync Views

REST endpoints for managing quote spreadsheets integrated with Google Sheets.
Provides functionality to:
- Link jobs to Google Sheets quote templates
- Preview quote changes from linked sheets
- Apply quote changes from linked sheets
"""

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.costing_serializer import CostSetSerializer
from apps.job.serializers.quote_sync_serializer import (
    ApplyQuoteErrorResponseSerializer,
    ApplyQuoteResponseSerializer,
    LinkQuoteSheetResponseSerializer,
    LinkQuoteSheetSerializer,
    PreviewQuoteResponseSerializer,
    QuoteSyncErrorResponseSerializer,
)
from apps.job.services import quote_sync_service

logger = logging.getLogger(__name__)


class LinkQuoteSheetAPIView(APIView):
    """
    Link a job to a Google Sheets quote template.

    POST /job/rest/jobs/<uuid:pk>/quote/link/
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        summary="Link a job to a Google Sheets quote template",
        request=LinkQuoteSheetSerializer,
        responses={
            200: LinkQuoteSheetResponseSerializer,
            400: QuoteSyncErrorResponseSerializer,
            404: QuoteSyncErrorResponseSerializer,
            500: QuoteSyncErrorResponseSerializer,
        },
    )
    def post(self, request: Request, pk: str) -> Response:
        try:
            logger.info(f"Starting link quote sheet process for job {pk}")

            # Get job
            try:
                job = Job.objects.get(pk=pk)
                logger.info(f"Found job: {job.job_number}")
            except Job.DoesNotExist:
                error_response = {"error": "Job not found"}
                error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
                error_serializer.is_valid(raise_exception=True)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

            # Validate input data
            logger.info("Validating input data")
            input_serializer = LinkQuoteSheetSerializer(data=request.data)
            if not input_serializer.is_valid():
                error_response = {"error": f"Invalid input: {input_serializer.errors}"}
                error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            # Extract template URL from request if provided
            template_url = input_serializer.validated_data.get("template_url")
            logger.info(f"Template URL: {template_url}")

            # Link quote sheet
            logger.info("Calling quote_sync_service.link_quote_sheet")
            quote_sheet = quote_sync_service.link_quote_sheet(job, template_url)
            logger.info(f"Quote sheet linked successfully: {quote_sheet.sheet_id}")

            response_data = {
                "sheet_url": quote_sheet.sheet_url,
                "sheet_id": quote_sheet.sheet_id,
                "job_id": str(job.id),
            }

            response_serializer = LinkQuoteSheetResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except RuntimeError as e:
            logger.error(f"Error linking quote sheet for job {pk}: {str(e)}")
            error_response = {"error": str(e)}
            error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error linking quote sheet for job {pk}: {str(e)}")
            error_response = {"error": "An unexpected error occurred"}
            error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PreviewQuoteAPIView(APIView):
    """
    Preview quote import from linked Google Sheet.

    POST /job/rest/jobs/<uuid:pk>/quote/preview/
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Preview quote import from linked Google Sheet",
        request=None,
        responses={
            200: PreviewQuoteResponseSerializer,
            400: QuoteSyncErrorResponseSerializer,
            404: QuoteSyncErrorResponseSerializer,
            500: QuoteSyncErrorResponseSerializer,
        },
    )
    def post(self, request: Request, pk: str) -> Response:
        try:
            # Get job
            try:
                job = Job.objects.get(pk=pk)
            except Job.DoesNotExist:
                error_response = {"error": "Job not found"}
                error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
                error_serializer.is_valid(raise_exception=True)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

            # Preview quote
            preview_data = quote_sync_service.preview_quote(job)

            # Serialize the preview data
            response_serializer = PreviewQuoteResponseSerializer(data=preview_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except RuntimeError as e:
            logger.error(f"Error previewing quote for job {pk}: {str(e)}")
            error_response = {"error": str(e)}
            error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error previewing quote for job {pk}: {str(e)}")
            error_response = {"error": "An unexpected error occurred"}
            error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ApplyQuoteAPIView(APIView):
    """
    Apply quote import from linked Google Sheet.

    POST /job/rest/jobs/<uuid:pk>/quote/apply/
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        summary="Apply quote import from linked Google Sheet",
        request=None,
        responses={
            200: ApplyQuoteResponseSerializer,
            400: ApplyQuoteErrorResponseSerializer,
            404: QuoteSyncErrorResponseSerializer,
            500: QuoteSyncErrorResponseSerializer,
        },
    )
    def post(self, request: Request, pk: str) -> Response:
        try:
            # Get job
            try:
                job = Job.objects.get(pk=pk)
            except Job.DoesNotExist:
                error_response = {"error": "Job not found"}
                error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
                error_serializer.is_valid(raise_exception=True)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

            # Apply quote
            result = quote_sync_service.apply_quote(job)

            if result.success:
                # Serialize the cost set if available
                cost_set_data = None
                if result.cost_set:
                    cost_set_data = CostSetSerializer(result.cost_set).data

                # Convert DraftLine objects to dictionaries for JSON serialization
                def draft_line_to_dict(draft_line):
                    return {
                        "kind": draft_line.kind,
                        "desc": draft_line.desc,
                        "quantity": float(draft_line.quantity),
                        "unit_cost": float(draft_line.unit_cost),
                        "unit_rev": float(draft_line.unit_rev),
                        "total_cost": float(draft_line.quantity * draft_line.unit_cost),
                        "total_rev": float(draft_line.quantity * draft_line.unit_rev),
                    }

                response_data = {
                    "success": True,
                    "cost_set": cost_set_data,
                    "draft_lines": (
                        [draft_line_to_dict(line) for line in result.diff_result.to_add]
                        if result.diff_result
                        else []
                    ),
                    "changes": {
                        "additions": (
                            [
                                draft_line_to_dict(line)
                                for line in result.diff_result.to_add
                            ]
                            if result.diff_result
                            else []
                        ),
                        "updates": (
                            [
                                draft_line_to_dict(draft_line)
                                for _, draft_line in result.diff_result.to_update
                            ]
                            if result.diff_result
                            else []
                        ),
                        "deletions": (
                            [
                                {
                                    "kind": line.kind,
                                    "desc": line.desc,
                                    "quantity": float(line.quantity),
                                    "unit_cost": float(line.unit_cost),
                                    "unit_rev": float(line.unit_rev),
                                }
                                for line in result.diff_result.to_delete
                            ]
                            if result.diff_result
                            else []
                        ),
                    },
                }

                response_serializer = ApplyQuoteResponseSerializer(data=response_data)
                response_serializer.is_valid(raise_exception=True)
                return Response(response_serializer.data, status=status.HTTP_200_OK)
            else:
                error_response = {"success": False, "error": result.error_message}
                error_serializer = ApplyQuoteErrorResponseSerializer(
                    data=error_response
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

        except RuntimeError as e:
            logger.error(f"Error applying quote for job {pk}: {str(e)}")
            error_response = {"success": False, "error": str(e)}
            error_serializer = ApplyQuoteErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error applying quote for job {pk}: {str(e)}")
            error_response = {"error": "An unexpected error occurred"}
            error_serializer = QuoteSyncErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
