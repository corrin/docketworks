import logging

from django.http import HttpRequest

logger = logging.getLogger(__name__)


def get_client_ip(request: HttpRequest) -> str:
    """
    Extract client IP address from request.

    Production path (behind nginx reverse proxy):
        - nginx receives client connection, knows real client IP
        - nginx sets X-Forwarded-For header with client's real IP
        - We read X-Forwarded-For

    Development path (direct connection to Django):
        - No nginx, browser connects directly to Django dev server
        - Django receives connection, REMOTE_ADDR contains real client IP
        - X-Forwarded-For not set, so we fall back to REMOTE_ADDR

    These are fundamentally different network topologies requiring different
    code paths. Both paths are tested: production via nginx config,
    development via direct connection.

    Args:
        request: Django HTTP request

    Returns:
        str: Client IP address
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    remote_addr = request.META.get("REMOTE_ADDR")

    logger.debug(
        "IP headers - X-Forwarded-For: %s, REMOTE_ADDR: %s",
        x_forwarded_for,
        remote_addr,
    )

    if x_forwarded_for:
        client_ip = x_forwarded_for.split(",")[0].strip()
        logger.debug("Using X-Forwarded-For: %s", client_ip)
        return client_ip
    elif remote_addr:
        logger.debug("Using REMOTE_ADDR: %s", remote_addr)
        return remote_addr
    else:
        raise ValueError("Unable to determine client IP address")
