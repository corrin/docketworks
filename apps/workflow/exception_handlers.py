"""
Custom DRF exception handlers for the application.
"""

import logging
from typing import Optional

from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

auth_logger = logging.getLogger("auth")


def custom_exception_handler(exc: Exception, context: dict) -> Optional[Response]:
    """
    Custom exception handler that persists unlogged errors and logs permission denied.

    Catches all exceptions that reach DRF's exception handler. Persists any that
    haven't already been persisted upstream (detected via AlreadyLoggedException).
    """
    response = exception_handler(exc, context)
    request = context.get("request")
    user_id = None
    session_replay_id = None
    additional_context = None
    if request:
        if getattr(request, "user", None) and request.user.is_authenticated:
            user_id = str(request.user.id)
        session_replay_id = request.headers.get("X-Session-Replay-Id")
        additional_context = {
            "request_path": request.path,
            "request_method": request.method,
            "session_replay_id": session_replay_id,
        }

    if not isinstance(exc, AlreadyLoggedException):
        persist_app_error(
            exc,
            user_id=user_id,
            session_replay_id=session_replay_id,
            additional_context=additional_context,
        )

    if isinstance(exc, PermissionDenied):
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

    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        view = context.get("view")

        endpoint = request.path if request else "unknown"
        method = request.method if request else "unknown"
        view_name = (
            f"{view.__class__.__module__}.{view.__class__.__name__}"
            if view
            else "unknown"
        )
        access_cookie_present = False
        refresh_cookie_present = False
        if request:
            access_cookie_present = "access_token" in request.COOKIES
            refresh_cookie_present = "refresh_token" in request.COOKIES

        auth_logger.warning(
            "Authentication rejected: endpoint=%s method=%s view=%s access_cookie_present=%s refresh_cookie_present=%s error=%s",
            endpoint,
            method,
            view_name,
            access_cookie_present,
            refresh_cookie_present,
            exc,
        )

    return response
