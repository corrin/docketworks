"""
API endpoint returning per-dataset version strings.

The frontend uses these to detect when a backend dataset has changed since
the last time it cached it (e.g. Xero stock-price updates landing in the
local DB) and to trigger refetches of the affected Pinia stores. This is
deliberately a separate channel from /api/build-id/ — that one fires on
code deploys, this one fires on data changes during normal operation.

Each dataset key has a deterministic provider that produces a version
string from the underlying table. To add a new dataset, register a
provider in DATASET_VERSION_PROVIDERS.
"""

from typing import Callable, Dict

from django.db.models import Count, Max
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.purchasing.models import Stock
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error


def _stock_version() -> str:
    agg = Stock.objects.aggregate(m=Max("updated_at"), c=Count("id"))
    max_ts = agg["m"].timestamp() if agg["m"] is not None else 0.0
    return f"{max_ts}-{agg['c']}"


DATASET_VERSION_PROVIDERS: Dict[str, Callable[[], str]] = {
    "stock": _stock_version,
}


class DataVersionsAPIView(APIView):
    """Return a flat dict of dataset version strings."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: inline_serializer(
                name="DataVersions",
                fields={
                    key: serializers.CharField() for key in DATASET_VERSION_PROVIDERS
                },
            )
        },
    )
    def get(self, request: Request) -> Response:
        try:
            payload = {
                key: provider() for key, provider in DATASET_VERSION_PROVIDERS.items()
            }
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc

        response = Response(payload)
        response["Cache-Control"] = "no-store"
        return response
