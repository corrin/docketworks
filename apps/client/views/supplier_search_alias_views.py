"""REST views for supplier search aliases."""

import logging
from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.client.models import Client, SupplierSearchAlias
from apps.client.serializers import (
    SupplierSearchAliasCreateSerializer,
    SupplierSearchAliasSerializer,
)
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


def _build_server_error_response(*, message: str, exc: Exception) -> Response:
    if isinstance(exc, AlreadyLoggedException):
        root_exc = exc.original
        error_id = exc.app_error_id
    else:
        root_exc = exc
        app_error = persist_app_error(exc)
        error_id = getattr(app_error, "id", None)

    logger.error("%s: %s", message, root_exc)

    payload: dict[str, Any] = {"error": message, "details": str(root_exc)}
    if error_id:
        payload["error_id"] = str(error_id)
    return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema_view(
    get=extend_schema(
        summary="List supplier search aliases",
        responses=SupplierSearchAliasSerializer(many=True),
        tags=["Clients"],
    ),
    post=extend_schema(
        summary="Create supplier search alias",
        request=SupplierSearchAliasCreateSerializer,
        responses=SupplierSearchAliasSerializer,
        tags=["Clients"],
    ),
)
class ClientSupplierAliasListCreateView(APIView):
    """List and create search aliases for a client/supplier contact."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, client_id) -> Response:
        try:
            client = Client.objects.get(id=client_id)
            aliases = client.supplier_search_aliases.filter(is_active=True).order_by(
                "alias"
            )
            serializer = SupplierSearchAliasSerializer(aliases, many=True)
            return Response(serializer.data)
        except Client.DoesNotExist:
            return Response(
                {"error": "Client not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as exc:
            return _build_server_error_response(
                message="Error listing supplier aliases", exc=exc
            )

    def post(self, request: Request, client_id) -> Response:
        try:
            client = Client.objects.get(id=client_id)
            serializer = SupplierSearchAliasCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            alias_text = serializer.validated_data["alias"].strip()

            alias, _ = SupplierSearchAlias.objects.get_or_create(
                client=client,
                alias=alias_text,
                defaults={"is_active": True},
            )
            if not alias.is_active:
                alias.is_active = True
                alias.save(update_fields=["is_active", "updated_at"])

            output = SupplierSearchAliasSerializer(alias)
            return Response(output.data, status=status.HTTP_201_CREATED)
        except Client.DoesNotExist:
            return Response(
                {"error": "Client not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValidationError as exc:
            return Response(
                {"error": "Invalid supplier alias", "details": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return _build_server_error_response(
                message="Error creating supplier alias", exc=exc
            )


@extend_schema_view(
    delete=extend_schema(
        summary="Deactivate supplier search alias",
        responses={204: None},
        tags=["Clients"],
    )
)
class SupplierAliasDetailView(APIView):
    """Deactivate a supplier search alias."""

    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, alias_id) -> Response:
        try:
            alias = SupplierSearchAlias.objects.get(id=alias_id, is_active=True)
            alias.is_active = False
            alias.save(update_fields=["is_active", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        except SupplierSearchAlias.DoesNotExist:
            return Response(
                {"error": "Supplier alias not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as exc:
            return _build_server_error_response(
                message="Error deleting supplier alias", exc=exc
            )
