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

from apps.company.models import Company, SupplierSearchAlias
from apps.company.serializers import (
    SupplierSearchAliasCreateSerializer,
    SupplierSearchAliasSerializer,
)
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


def _build_server_error_response(*, message: str, exc: Exception) -> Response:
    app_error = persist_app_error(exc)

    logger.error("%s: %s", message, exc)

    payload: dict[str, Any] = {"error": message, "details": str(exc)}
    payload["error_id"] = str(app_error.id)
    return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema_view(
    get=extend_schema(
        summary="List supplier search aliases",
        responses=SupplierSearchAliasSerializer(many=True),
        tags=["Companies"],
    ),
    post=extend_schema(
        summary="Create supplier search alias",
        request=SupplierSearchAliasCreateSerializer,
        responses={status.HTTP_201_CREATED: SupplierSearchAliasSerializer},
        tags=["Companies"],
    ),
)
class CompanySupplierAliasListCreateView(APIView):
    """List and create search aliases for a company/supplier contact."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, company_id) -> Response:
        try:
            company = Company.objects.get(id=company_id)
            aliases = company.supplier_search_aliases.filter(is_active=True).order_by(
                "alias"
            )
            serializer = SupplierSearchAliasSerializer(aliases, many=True)
            return Response(serializer.data)
        except Company.DoesNotExist:
            return Response(
                {"error": "Company not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as exc:
            return _build_server_error_response(
                message="Error listing supplier aliases", exc=exc
            )

    def post(self, request: Request, company_id) -> Response:
        try:
            company = Company.objects.get(id=company_id)
            serializer = SupplierSearchAliasCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            alias_text = serializer.validated_data["alias"].strip()

            alias, _ = SupplierSearchAlias.objects.get_or_create(
                company=company,
                alias=alias_text,
                defaults={"is_active": True},
            )
            if not alias.is_active:
                alias.is_active = True
                alias.save(update_fields=["is_active", "updated_at"])

            output = SupplierSearchAliasSerializer(alias)
            return Response(output.data, status=status.HTTP_201_CREATED)
        except Company.DoesNotExist:
            return Response(
                {"error": "Company not found"},
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
        tags=["Companies"],
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
