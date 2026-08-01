"""Request/response schemas for the accounts auth endpoints.

Shapes ported from v1 apps/accounts/serializers.py. Per CLAUDE.md these
schemas are the single source of Staff field lists exposed over the API.

Note: v1's "me" payload (UserProfileSerializer) never included
default_labour_subtype, so the Staff model deferring that FK to Phase 2 costs
nothing here.
"""

from uuid import UUID

from ninja import Schema

from apps.accounts.models import Staff


class LoginRequest(Schema):
    """v1 CustomTokenObtainPairSerializer input: username (an email address) + password."""

    username: str
    password: str


class LoginResponse(Schema):
    """v1 TokenObtainPairResponseSerializer in cookie mode.

    Tokens are set as HttpOnly cookies and never appear in the body (v1
    deleted them from the payload when ENABLE_JWT_AUTH was on, which it always
    is in v2). password_needs_reset appears only when true; the endpoint
    serialises with exclude_none so the normal success body is ``{}`` like v1.
    """

    password_needs_reset: bool | None = None


class TokenRefreshRequest(Schema):
    """Body for token refresh; optional because v1 fell back to the refresh cookie."""

    refresh: str | None = None


class TokenRefreshResponse(Schema):
    """Empty body (v1 TokenRefreshResponseSerializer in cookie mode): the new
    access token travels only in the HttpOnly cookie."""


class LogoutResponse(Schema):
    """v1 LogoutUserAPIView success body."""

    success: bool
    message: str


class UserProfile(Schema):
    """v1 UserProfileSerializer — the /accounts/me/ payload."""

    id: UUID
    username: str
    email: str
    first_name: str
    last_name: str
    preferred_name: str | None = None
    fullName: str
    is_office_staff: bool
    is_superuser: bool

    @staticmethod
    def resolve_username(obj: Staff) -> str:
        """v1 aliased username to the email field."""
        return obj.email

    @staticmethod
    def resolve_fullName(obj: Staff) -> str:
        return f"{obj.first_name} {obj.last_name}".strip()
