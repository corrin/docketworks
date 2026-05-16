from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


class CompanyProfitAndLossReport(APIView):
    """Unavailable until rebuilt against the Xero Reports API."""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=str,
                required=True,
                description="Period start date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="end_date",
                type=str,
                required=True,
                description="Period end date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="compare",
                type=int,
                required=False,
                description="Number of comparison periods to include. Defaults to 0.",
            ),
            OpenApiParameter(
                name="period_type",
                type=str,
                required=False,
                enum=["month", "year"],
                description="Period type for comparison. Defaults to 'month'.",
            ),
        ],
        responses={501: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        return Response(
            {
                "error": (
                    "Profit and Loss reporting is unavailable until it is rebuilt "
                    "against the Xero Reports API."
                )
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
