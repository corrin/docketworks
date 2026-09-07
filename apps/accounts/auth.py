"""Resolve the authenticated staff member once at the API boundary."""

from django.http import HttpRequest
from ninja.errors import HttpError

from apps.accounts.models import Staff


def authenticated_staff(request: HttpRequest) -> Staff:
    """Require the authenticated principal to be a staff member."""
    auth_user: object = getattr(request, "auth", None)
    user = auth_user if isinstance(auth_user, Staff) else request.user
    if not isinstance(user, Staff):
        raise HttpError(401, "Authentication credentials were not provided.")
    return user
