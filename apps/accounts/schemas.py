"""Request and response schemas for the accounts authentication endpoints.

These schemas are the single source of Staff field lists exposed over the API.
"""

import datetime as datetime_module
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ninja import Field, Schema
from pydantic import ConfigDict

from apps.accounts.models import STAFF_MANAGER_GROUP_NAME, Staff
from apps.core.schemas import (
    NonBlankText,
    NonNegativeQuantity,
    NullableText,
    Quantity,
    ResponseSchema,
    omittable,
)


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


class PasswordChangeRequest(Schema):
    """Self-service change body for POST /api/accounts/me/password/.

    Plain ``str`` like LoginRequest: a password is never whitespace-stripped
    or length-coerced on the way in — the validators judge the new value and
    check_password judges the old.
    """

    current_password: str
    new_password: str


class PasswordChangeResponse(ResponseSchema):
    """Empty 200 body for the self-service password change.

    The change's effect is the cleared ``password_needs_reset``, which the
    client re-reads from ``/me/``.
    """


class PasswordResetRequest(Schema):
    """Body for POST /api/accounts/password-reset/ — just the login email."""

    email: str


class PasswordResetResponse(ResponseSchema):
    """Fixed empty 200 for the reset request.

    The same body whether or not the email has an account, so the anonymous
    contract reveals nothing about which addresses exist.
    """


class PasswordResetConfirmRequest(Schema):
    """Body for POST /api/accounts/password-reset/confirm/.

    ``uid``/``token`` come verbatim from the emailed link; ``new_password``
    is plain ``str`` like every password field — never whitespace-stripped.
    """

    uid: str
    token: str
    new_password: str


class PasswordResetConfirmResponse(ResponseSchema):
    """Empty 200: the caller's next step is simply logging in."""


class PasswordErrorOut(ResponseSchema):
    """DECLARED 400 body for the credential endpoints (change and reset).

    A declared response rather than an HttpError: the envelope masks
    exception text on anonymous requests (ADR 0038), a declared shape rides
    the exported schema into the generated client, and every refusal here
    (dead link, wrong current password, weak new password) is exactly what
    the caller must read.
    """

    detail: str


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
    office_email: str | None
    payroll_email: str | None
    first_name: str
    last_name: str
    preferred_name: str | None = None
    full_name: str = Field(serialization_alias="fullName")
    is_office_staff: bool
    is_superuser: bool
    # The SPA's route guard reads the flag from /me/; the auth-layer gate is
    # the control, this field is what makes the guard's navigation informed.
    password_needs_reset: bool

    @staticmethod
    def resolve_full_name(obj: Staff) -> str:
        """Concatenate first and last name for the ``fullName`` wire field."""
        return f"{obj.first_name} {obj.last_name}".strip()


class StaffListItemOut(Schema):
    """One row of the staff admin list (GET /api/accounts/staff/).

    Also the response of every staff write: the admin screen's edit modal is
    populated from this row (there is no retrieve endpoint), so the full
    editable field set rides here.
    """

    id: UUID
    first_name: str
    last_name: str
    preferred_name: str | None
    # Fable: The server's one naming rule (first word of preferred/first name
    # plus last name) — carried on the wire so no client re-derives it with
    # different semantics and hashes a different avatar colour than kanban.
    display_name: str
    office_email: str | None
    payroll_email: str | None
    employment_start_date: date
    pay_basis: str | None
    wage_rate: Quantity
    base_wage_rate: Quantity
    date_left: date | None
    xero_user_id: str | None
    is_office_staff: bool
    is_workshop_staff: bool
    is_superuser: bool
    is_staff_manager: bool
    # Editable via the admin's force-change checkbox, so the edit modal must
    # see the stored value — an always-unchecked box on a flagged account
    # would clear the flag on the next unrelated save.
    password_needs_reset: bool
    hours_mon: Quantity
    hours_tue: Quantity
    hours_wed: Quantity
    hours_thu: Quantity
    hours_fri: Quantity
    hours_sat: Quantity
    hours_sun: Quantity
    # Plain str, not a URL type: site-root-relative /media/ paths must resolve
    # against the browser's own origin, matching KanbanStaffOut.icon_url.
    icon_url: str | None

    @staticmethod
    def resolve_display_name(obj: Staff) -> str:
        """Resolve the canonical display name, same rule as the kanban wire types."""
        return obj.get_display_full_name()

    @staticmethod
    def resolve_icon_url(obj: Staff) -> str | None:
        """Site-relative icon path, or None when the staff member has no icon."""
        return obj.icon.url if obj.icon else None

    @staticmethod
    def resolve_is_staff_manager(obj: Staff) -> bool:
        """Raw StaffManager membership, NOT Staff.is_staff_manager().

        Fable: The model method folds in is_superuser (effective privilege); a
        checkbox round-tripping that would silently enrol every superuser in
        the group. list_all_staff prefetches groups, so this is not N+1.
        """
        return any(group.name == STAFF_MANAGER_GROUP_NAME for group in obj.groups.all())


class StaffCreateIn(Schema):
    """Create body for POST /api/accounts/staff/.

    Unknown keys are rejected rather than dropped (``extra="forbid"``): the
    derived ``wage_rate`` in a payload must be a 422, not a silent no-op.
    Omitted fields take the model defaults — the handler dumps with
    ``exclude_unset`` and never reads the placeholders here.

    ``password_needs_reset`` is the admin's "must change at next login"
    control — and, because the gate lives at the auth layer, the only way an
    existing session (not just the next login) gets locked to the change
    screen.
    """

    model_config = ConfigDict(extra="forbid")

    office_email: NullableText = omittable(None)
    first_name: NonBlankText
    last_name: NonBlankText
    password: NonBlankText
    password_needs_reset: bool = omittable(False)
    preferred_name: NullableText = omittable(None)
    payroll_email: NullableText = omittable(None)
    xero_user_id: NullableText = omittable(None)
    base_wage_rate: NonNegativeQuantity = omittable(Decimal("0"))
    employment_start_date: date = omittable(date(1970, 1, 1))
    date_left: date | None = omittable(None)
    pay_basis: Literal["hourly", "salary"] | None = omittable(None)
    is_office_staff: bool = omittable(False)
    is_workshop_staff: bool = omittable(True)
    is_superuser: bool = omittable(False)
    is_staff_manager: bool = omittable(False)
    hours_mon: NonNegativeQuantity = omittable(Decimal("8"))
    hours_tue: NonNegativeQuantity = omittable(Decimal("8"))
    hours_wed: NonNegativeQuantity = omittable(Decimal("8"))
    hours_thu: NonNegativeQuantity = omittable(Decimal("8"))
    hours_fri: NonNegativeQuantity = omittable(Decimal("8"))
    hours_sat: NonNegativeQuantity = omittable(Decimal("0"))
    hours_sun: NonNegativeQuantity = omittable(Decimal("0"))


class StaffUpdateIn(Schema):
    """Partial-update body for PATCH /api/accounts/staff/{staff_id}/.

    Everything omittable: omission leaves the stored value alone. On the
    nullable fields ``null`` is a real value — ``date_left: null`` reinstates a
    departed staff member (ADR 0040). ``password`` is presence-only: null is
    never a password value, so only supplying one changes it.

    ``password_needs_reset`` is the admin's "must change at next login"
    control. Supplied alongside ``password``, the explicit flag wins over the
    set-password clear (_set_staff_password runs before _apply_staff_fields).
    """

    model_config = ConfigDict(extra="forbid")

    office_email: NullableText = omittable(None)
    first_name: NonBlankText = omittable("")
    last_name: NonBlankText = omittable("")
    password: NonBlankText = omittable("")
    password_needs_reset: bool = omittable(False)
    preferred_name: NullableText = omittable(None)
    payroll_email: NullableText = omittable(None)
    xero_user_id: NullableText = omittable(None)
    base_wage_rate: NonNegativeQuantity = omittable(Decimal("0"))
    employment_start_date: date = omittable(date(1970, 1, 1))
    date_left: date | None = omittable(None)
    pay_basis: Literal["hourly", "salary"] | None = omittable(None)
    is_office_staff: bool = omittable(False)
    is_workshop_staff: bool = omittable(True)
    is_superuser: bool = omittable(False)
    is_staff_manager: bool = omittable(False)
    hours_mon: NonNegativeQuantity = omittable(Decimal("8"))
    hours_tue: NonNegativeQuantity = omittable(Decimal("8"))
    hours_wed: NonNegativeQuantity = omittable(Decimal("8"))
    hours_thu: NonNegativeQuantity = omittable(Decimal("8"))
    hours_fri: NonNegativeQuantity = omittable(Decimal("8"))
    hours_sat: NonNegativeQuantity = omittable(Decimal("0"))
    hours_sun: NonNegativeQuantity = omittable(Decimal("0"))


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
