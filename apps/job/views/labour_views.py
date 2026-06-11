"""
Labour subtype REST views

- List labour subtypes (dropdowns, rate displays)
- Update a job's per-subtype charge-out rates
"""

import logging
from uuid import UUID

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.job.models import Job, JobEvent, LabourSubtype
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.labour_serializer import (
    JobLabourRateSerializer,
    JobLabourRatesUpdateRequestSerializer,
    LabourSubtypeSerializer,
)

logger = logging.getLogger(__name__)


class LabourSubtypeListView(APIView):
    """
    List active labour subtypes.

    GET /job/rest/labour-subtypes/
    """

    permission_classes = [IsAuthenticated]
    serializer_class = LabourSubtypeSerializer

    @extend_schema(responses={200: LabourSubtypeSerializer(many=True)})
    def get(self, request: Request) -> Response:
        subtypes = LabourSubtype.objects.filter(is_active=True)
        serializer = LabourSubtypeSerializer(subtypes, many=True)
        return Response(serializer.data)


class JobLabourRatesView(APIView):
    """
    Read or update a job's per-subtype charge-out rates.

    GET  /job/rest/jobs/<job_id>/labour-rates/
    PATCH /job/rest/jobs/<job_id>/labour-rates/  {"rates": [{"labour_subtype": ..., "charge_out_rate": ...}]}
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = JobLabourRateSerializer

    @extend_schema(responses={200: JobLabourRateSerializer(many=True)})
    def get(self, request: Request, job_id: UUID) -> Response:
        job = get_object_or_404(Job, id=job_id)
        serializer = JobLabourRateSerializer(
            job.labour_rates.select_related("labour_subtype"), many=True
        )
        return Response(serializer.data)

    @extend_schema(
        request=JobLabourRatesUpdateRequestSerializer,
        responses={200: JobLabourRateSerializer(many=True)},
    )
    def patch(self, request: Request, job_id: UUID) -> Response:
        # Unreachable: IsAuthenticated + IsOfficeStaff guarantee a Staff user;
        # narrows the type for the JobEvent write below.
        assert isinstance(request.user, Staff)
        job = get_object_or_404(Job, id=job_id)
        serializer = JobLabourRatesUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        changes: list[str] = []
        for entry in serializer.validated_data["rates"]:
            rate = job.labour_rates.get(labour_subtype=entry["labour_subtype"])
            if rate.charge_out_rate == entry["charge_out_rate"]:
                continue
            changes.append(
                f"{entry['labour_subtype'].name}: "
                f"${rate.charge_out_rate}/hour -> ${entry['charge_out_rate']}/hour"
            )
            rate.charge_out_rate = entry["charge_out_rate"]
            rate.save(update_fields=["charge_out_rate"])

        if changes:
            JobEvent.objects.create(
                job=job,
                event_type="pricing_changed",
                detail={
                    "field_name": "Labour charge-out rates",
                    "changes": changes,
                },
                staff=request.user,
            )
        else:
            pass  # No-op update: nothing changed, no event to record

        refreshed = JobLabourRateSerializer(
            job.labour_rates.select_related("labour_subtype"), many=True
        )
        return Response(refreshed.data)
