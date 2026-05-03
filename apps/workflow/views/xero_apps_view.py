"""DRF viewset for /api/workflow/xero-apps/ — manage Xero app credential pairs.

Staff-only. The serializer never returns client_secret / access_token /
refresh_token; only the has_tokens boolean and quota timestamps.

This is the break-glass UI: the Activate action swaps which row's
credentials Xero calls use, replacing the legacy "ssh + edit .env +
restart" procedure.
"""

from django.conf import settings
from django.db import IntegrityError
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.job.permissions import IsOfficeStaff
from apps.workflow.api.xero.active_app import (
    swap_active,
    wipe_tokens_and_quota,
)
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import XeroApp
from apps.workflow.serializers import XeroAppSerializer
from apps.workflow.services.error_persistence import persist_app_error


class XeroAppConfigSerializer(serializers.Serializer):
    """Read-only config snapshot for clients (e.g. the quota badge) that
    need to align UI thresholds to backend behaviour."""

    day_floor = serializers.IntegerField(
        help_text=(
            "XERO_AUTOMATED_DAY_FLOOR — automated Xero traffic is gated off "
            "once X-DayLimit-Remaining is at or below this value."
        )
    )


class XeroAppViewSet(viewsets.ModelViewSet):
    queryset = XeroApp.objects.all().order_by("created_at")
    serializer_class = XeroAppSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"detail": "A XeroApp with that client_id already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        before_client_id = instance.client_id
        before_client_secret = instance.client_secret
        try:
            response = super().partial_update(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"detail": "A XeroApp with that client_id already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if response.status_code == 200:
            instance.refresh_from_db()
            credentials_changed = (
                instance.client_id != before_client_id
                or instance.client_secret != before_client_secret
            )
            if credentials_changed:
                # New client_id is a different Xero app from Xero's
                # perspective — old tokens and quota are invalid for it.
                wipe_tokens_and_quota(instance)
                instance.refresh_from_db()
                response.data = self.get_serializer(instance).data
        return response

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_active:
            return Response(
                {
                    "detail": (
                        "Cannot delete the active XeroApp. "
                        "Activate another row first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(request=None, responses={200: XeroAppSerializer})
    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        try:
            target = swap_active(pk)
        except XeroApp.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc
        # swap_active dispatched a detached `systemctl restart` for the
        # worker units — gunicorn (this process) included. The HTTP response
        # gets out before systemd kills us; the operator's next request
        # lands on a fresh worker bound to the new active row.
        data = self.get_serializer(target).data
        data["restart_initiated"] = True
        data["message"] = (
            "Active Xero app swapped. Workers are restarting; "
            "this page will refresh in a few seconds."
        )
        return Response(data)

    @extend_schema(request=None, responses={200: XeroAppConfigSerializer})
    @action(detail=False, methods=["get"], url_path="config")
    def config(self, request):
        """Expose backend Xero config to the frontend.

        Today: just the day-quota floor — the quota badge derives its
        red/amber thresholds from this so a deployment bumping the floor
        in env doesn't leave the UI showing "healthy" while syncs abort.
        """
        return Response({"day_floor": settings.XERO_AUTOMATED_DAY_FLOOR})
