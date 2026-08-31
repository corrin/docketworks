"""Authentication against either Docketworks or Xero payroll email."""

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from apps.accounts.models import Staff


class StaffEmailBackend(ModelBackend):
    """Authenticate one unambiguous Staff row by either email address."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> Staff | None:
        """Return the sole matching user when its password is valid."""
        del request, kwargs
        if username is None or password is None:
            return None

        user = Staff.objects.sole_login_match(username)
        if user is None:
            # Match Django's default backend timing for an unknown login.
            Staff().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
