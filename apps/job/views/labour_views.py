"""
Labour subtype REST views

- List labour subtypes (dropdowns, rate displays)
- Update a job's per-subtype charge-out rates
"""

import logging
from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.job.models import Job, JobEvent, LabourSubtype
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.labour_serializer import (
    JobLabourRateSerializer,
    JobLabourRatesUpdateRequestSerializer,
    LabourSubtypeManageSerializer,
    LabourSubtypeSerializer,
)
from apps.job.services.labour_subtype_service import seed_subtype_onto_existing_jobs

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


class LabourSubtypeManageListCreateView(ListCreateAPIView[LabourSubtype]):
    """
    List all labour subtypes (including inactive) and create new ones.

    GET  /job/rest/labour-subtypes/manage/
    POST /job/rest/labour-subtypes/manage/

    Office-staff only. Creating an active subtype backfills a JobLabourRate onto
    every existing job so the data-integrity invariant stays satisfied.
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = LabourSubtypeManageSerializer
    queryset = LabourSubtype.objects.all()

    @transaction.atomic
    def perform_create(self, serializer: BaseSerializer[LabourSubtype]) -> None:
        subtype = serializer.save()
        if subtype.is_active:
            seed_subtype_onto_existing_jobs(subtype)
        else:
            pass  # inactive subtype is not seeded onto jobs (matches Job.save)


class LabourSubtypeManageDetailView(RetrieveUpdateAPIView[LabourSubtype]):
    """
    Retrieve or update one labour subtype (office staff). No delete — subtypes
    are referenced by historical cost lines (PROTECT); deactivate instead.

    GET   /job/rest/labour-subtypes/manage/<id>/
    PATCH /job/rest/labour-subtypes/manage/<id>/
    """

    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = LabourSubtypeManageSerializer
    queryset = LabourSubtype.objects.all()
    http_method_names = ["get", "patch", "head", "options"]

    @transaction.atomic
    def perform_update(self, serializer: BaseSerializer[LabourSubtype]) -> None:
        instance = serializer.instance
        assert instance is not None
        subtype = LabourSubtype.objects.select_for_update().get(pk=instance.pk)
        was_active = subtype.is_active
        serializer.instance = subtype
        updated = serializer.save()
        if not was_active and updated.is_active:
            seed_subtype_onto_existing_jobs(updated)
        else:
            pass  # no activation boundary crossed; no backfill needed


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
