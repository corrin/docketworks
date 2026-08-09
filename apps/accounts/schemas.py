"""Request and response schemas for the accounts authentication endpoints.

These schemas are the single source of Staff field lists exposed over the API.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from ninja import Field, Schema

from apps.accounts.models import Staff
from apps.core.schemas import ResponseSchema


class LoginRequest(Schema):
    """Wire contract for LoginRequest."""

    username: str
    password: str


class LoginResponse(ResponseSchema):
    """Login response for cookie-based authentication.

    Tokens are set as HttpOnly cookies and never appear in the body, so
    ``password_needs_reset`` is the whole of it. It is always sent: a body whose
    keys depend on the answer makes the client check presence before reading a
    boolean it could have read directly.
    """

    password_needs_reset: bool = False


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


class UserProfile(ResponseSchema):
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


class StaffListItemOut(Schema):
    """One row of the staff admin list (GET /api/accounts/staff/)."""

    id: UUID
    first_name: str
    last_name: str
    email: str
    wage_rate: Decimal
    base_wage_rate: Decimal
    date_left: date | None
    is_office_staff: bool
