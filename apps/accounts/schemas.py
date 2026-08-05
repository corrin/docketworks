"""Request and response schemas for the accounts authentication endpoints.

These schemas are the single source of Staff field lists exposed over the API.
"""

from uuid import UUID

from ninja import Field, Schema

from apps.accounts.models import Staff


class LoginRequest(Schema):
    """Wire contract for LoginRequest."""

    username: str
    password: str


class LoginResponse(Schema):
    """Login response for cookie-based authentication.

    Tokens are set as HttpOnly cookies and never appear in the body.
    ``password_needs_reset`` appears only when true, so the normal success body
    is ``{}``.
    """

    password_needs_reset: bool | None = None


class TokenRefreshRequest(Schema):
    """Token-refresh body; the refresh cookie supplies an omitted token."""

    refresh: str | None = None


class TokenRefreshResponse(Schema):
    """Empty response body for cookie-based token refresh.

    The new access token travels only in the HttpOnly cookie.
    """


class LogoutResponse(Schema):
    """Wire contract for LogoutResponse."""

    success: bool
    message: str


class UserProfile(Schema):
    """Authenticated profile returned by ``/accounts/me/``.

    The wire key ``fullName`` is produced via a serialization
    alias; the /me/ endpoint therefore serialises with ``by_alias=True``.
    """

    id: UUID
    username: str
    email: str
    first_name: str
    last_name: str
    preferred_name: str | None = None
    full_name: str = Field(serialization_alias="fullName")
    is_office_staff: bool
    is_superuser: bool

    @staticmethod
    def resolve_username(obj: Staff) -> str:
        """Expose email as the API's username value."""
        return obj.email

    @staticmethod
    def resolve_full_name(obj: Staff) -> str:
        """Concatenate first and last name for the ``fullName`` wire field."""
        return f"{obj.first_name} {obj.last_name}".strip()
