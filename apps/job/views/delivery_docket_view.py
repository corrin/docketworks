"""API view for generating delivery dockets."""

import logging

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.job_serializer import WorkshopPDFResponseSerializer
from apps.job.services.delivery_docket_service import generate_delivery_docket

logger = logging.getLogger(__name__)


class DeliveryDocketView(APIView):
    """
    API view for generating and serving delivery docket PDFs.

    This view creates delivery docket PDFs that are identical to the workshop
    PDF (job details, specifications, client info, signature fields), saves
    them as JobFile records, creates a JobEvent for tracking, and returns
    the PDF for immediate download or printing.

    GET: Generates a delivery docket PDF for the specified job ID, saves it
         to the job folder, and returns it as a file response.
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = WorkshopPDFResponseSerializer

    @extend_schema(
        operation_id="generateDeliveryDocketRest",
        description="Generate a delivery docket PDF for a job and save it as a JobFile",
    )
    def get(self, request, job_id):
        """Generate, save, and return a delivery docket PDF."""
        try:
            job = get_object_or_404(Job, pk=job_id)

            # Generate the delivery docket PDF and save it
            pdf_buffer, job_file = generate_delivery_docket(job, staff=request.user)

            # Return the PDF for download/printing
            response = FileResponse(
                pdf_buffer,
                as_attachment=False,
                filename=job_file.filename,
                content_type="application/pdf",
            )

            # Use inline disposition so it opens in browser for printing
            response["Content-Disposition"] = f'inline; filename="{job_file.filename}"'

            return response

        except Exception as e:
            logger.exception(f"Error generating delivery docket for job {job_id}")
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
