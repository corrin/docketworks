"""Service-to-service authentication via the ``X-API-Key`` header.

Its own module rather than a class in ``apps.core.auth``: that module holds the
cookie-JWT policies, and ``apps.platform`` imports them. ``ServiceAPIKey`` is the
only model any auth class touches, so leaving it beside them put a business model
on every platform import path and the ADR 0055 contract refused it. Splitting the
one model-touching class out is what makes the contract hold with no exception
declared, rather than an ignore that would also stop watching every other chain.
"""

import logging

from django.http import HttpRequest
from ninja.security import APIKeyHeader

from apps.core.models import ServiceAPIKey

logger = logging.getLogger(__name__)


class ServiceAPIKeyAuth(APIKeyHeader):
    """Service-to-service auth via the X-API-Key header."""

    param_name = "X-API-Key"

    def authenticate(self, request: HttpRequest, key: str | None) -> ServiceAPIKey | None:
        """Look up an active ServiceAPIKey for the header value, else None."""
        if not key:
            return None
        try:
            service_key = ServiceAPIKey.objects.get(key=key, is_active=True)
        # deliberate-swallow: unknown key is an auth failure: logged, then rejected
        except ServiceAPIKey.DoesNotExist:
            logger.warning(
                "SERVICE API KEY INVALID - method=%s path=%s", request.method, request.path
            )
            return None
        service_key.mark_used()
        return service_key
