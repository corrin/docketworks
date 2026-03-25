"""
Custom DRF exception handlers for the application.
"""

import logging
from typing import Optional

from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler

auth_logger = logging.getLogger("auth")


def custom_exception_handler(exc: Exception, context: dict) -> Optional[Response]:
    """
    Custom exception handler that logs permission denied errors.

    Logs to the auth logger when a user is denied access to an endpoint,
    including user identity, endpoint, and HTTP method.
    """
    response = exception_handler(exc, context)

    if isinstance(exc, PermissionDenied):
        request = context.get("request")
        view = context.get("view")

        user_info = "anonymous"
        if request and hasattr(request, "user"):
            user = request.user
            if hasattr(user, "is_authenticated") and user.is_authenticated:
                user_info = (
                    getattr(user, "email", None)
                    or getattr(user, "username", None)
                    or str(user.pk)
                )

        endpoint = request.path if request else "unknown"
        method = request.method if request else "unknown"
        view_name = (
            f"{view.__class__.__module__}.{view.__class__.__name__}"
            if view
            else "unknown"
        )

        auth_logger.warning(
            "Permission denied: user=%s endpoint=%s method=%s view=%s",
            user_info,
            endpoint,
            method,
            view_name,
        )

    return response
