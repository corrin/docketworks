"""Browser authentication for tests through the application's token issuer."""

from django.test import Client

from apps.accounts.models import Staff
from apps.core.auth import issue_refresh_token, jwt_cookie_config


def authenticate(client: Client, staff: Staff) -> None:
    """Attach the configured access cookie, including the password fingerprint."""
    refresh = issue_refresh_token(staff)
    client.cookies[jwt_cookie_config().access_name] = str(refresh.access_token)
