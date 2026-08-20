"""Request and response schemas for the accounts authentication endpoints.

These schemas are the single source of Staff field lists exposed over the API.
"""

import datetime as datetime_module
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
    office_email: str
    payroll_email: str | None
    first_name: str
    last_name: str
    preferred_name: str | None = None
    full_name: str = Field(serialization_alias="fullName")
    is_office_staff: bool
    is_superuser: bool

    @staticmethod
    def resolve_full_name(obj: Staff) -> str:
        """Concatenate first and last name for the ``fullName`` wire field."""
        return f"{obj.first_name} {obj.last_name}".strip()


class StaffListItemOut(Schema):
    """One row of the staff admin list (GET /api/accounts/staff/)."""

    id: UUID
    first_name: str
    last_name: str
    office_email: str
    payroll_email: str | None
    employment_start_date: date
    pay_basis: str | None
    wage_rate: Decimal
    base_wage_rate: Decimal
    date_left: date | None
    is_office_staff: bool


class KanbanStaffQuery(Schema):
    """Query parameters for accounts_staff_all_list."""

    # datetime_module.date, not the bare `date` import: the field is itself
    # named ``date``, and a same-named annotation binds to the field being
    # defined (None) before the class body's own assignment resolves it,
    # raising `unsupported operand type(s) for |: 'NoneType' and 'NoneType'`
    # — apps/job/schemas.py carries the identical workaround.
    date: datetime_module.date | None = None
    include_inactive: bool = False
    actual_users: bool = False


class KanbanStaffOut(Schema):
    """One row of the kanban board's staff panel (GET /api/accounts/staff/all/).

    No wage fields — unlike StaffListItemOut, this is every authenticated
    user's view.
    """

    id: UUID
    first_name: str
    last_name: str
    # Plain str, not a URL type: site-root-relative /media/ paths must resolve
    # against the browser's own origin, matching KanbanJobPersonOut.icon_url.
    icon_url: str | None
    display_name: str
    is_office_staff: bool
    is_workshop_staff: bool

    @staticmethod
    def resolve_icon_url(obj: Staff) -> str | None:
        """Site-relative icon path, or None when the staff member has no icon."""
        return obj.icon.url if obj.icon else None

    @staticmethod
    def resolve_display_name(obj: Staff) -> str:
        """Return the kanban card's display name: preferred/first name + last name."""
        return obj.get_display_full_name()
