"""
User profile views for JWT authentication
"""

from logging import getLogger

from django.conf import settings
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import UserProfileSerializer
from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.services.request import get_client_ip

logger = getLogger(__name__)
auth_logger = getLogger("auth")


class GetCurrentUserAPIView(APIView):
    """
    Get current authenticated user information via JWT from httpOnly cookie
    """

    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    @extend_schema(
        summary="Returns the current authenticated user profile",
        responses={200: UserProfileSerializer},
    )
    def get(self, request: Request) -> Response:
        # Defensive guard: return 401 when unauthenticated instead of 500
        user = getattr(request, "user", None)
        logger.info(f"[/ME] -> received request: {request} and user: {user}")
        if user is None or not getattr(user, "is_authenticated", False):
            logger.info("Unauthorized access to /accounts/me/ (anonymous user)")
            return Response(
                {"detail": "Authentication credentials were not provided."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        serializer = UserProfileSerializer(user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutUserAPIView(APIView):
    """
    Custom logout view that clears JWT httpOnly cookies
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Logs out the current user by clearing JWT cookies",
        request=None,
        responses={200: OpenApiTypes.OBJECT, 500: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        try:
            simple_jwt_settings = getattr(settings, "SIMPLE_JWT", {})
            access_cookie_name = simple_jwt_settings.get("AUTH_COOKIE", "access_token")
            refresh_cookie_name = simple_jwt_settings.get(
                "REFRESH_COOKIE", "refresh_token"
            )

            auth_logger.info(
                "JWT LOGOUT REQUEST - ip=%s access_cookie_present=%s refresh_cookie_present=%s",
                get_client_ip(request),
                access_cookie_name in request.COOKIES,
                refresh_cookie_name in request.COOKIES,
            )

            response = Response(
                {"success": True, "message": "Successfully logged out"},
                status=status.HTTP_200_OK,
            )

            # Clear access token cookie
            response.delete_cookie(
                access_cookie_name,
                domain=simple_jwt_settings.get("AUTH_COOKIE_DOMAIN"),
                samesite=simple_jwt_settings.get("AUTH_COOKIE_SAMESITE", "Lax"),
            )

            # Clear refresh token cookie
            response.delete_cookie(
                refresh_cookie_name,
                domain=simple_jwt_settings.get("AUTH_COOKIE_DOMAIN"),
                samesite=simple_jwt_settings.get("REFRESH_COOKIE_SAMESITE", "Lax"),
            )

            return response

        except Exception as e:
            app_error = persist_app_error(e)
            return Response(
                {
                    "error": f"Error during logout: {str(e)}",
                    "details": {"error_id": str(app_error.id)},
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
