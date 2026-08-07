"""Xero router. Currently the pay-item read the SPA needs on every page.

Mounted under ``/api/xero/``, matching the app the model lives in. v1 served
this from an app called ``workflow`` that v2 does not have; no external party
holds the URL, so there is nothing to preserve and no reason to import a dead
app's name (CLAUDE.md: exact-URL parity only where an external party holds it).

Read-only on purpose: pay items are synced from Xero Payroll, never authored
here. The sync itself is Phase 4 and does not exist yet — this endpoint serves
whatever a data restore brought in, which is what makes it useful before the
Xero port lands.
"""

from datetime import datetime
from uuid import UUID

from django.http import HttpRequest
from ninja import Router, Schema

from apps.core.auth import CookieJWTAuth
from apps.xero.models import XeroPayItem

router = Router(tags=["xero"])
auth = CookieJWTAuth()


class XeroPayItemOut(Schema):
    """A Xero leave type or earnings rate.

    ``multiplier`` is null for leave types and set for earnings rates — that is
    the discriminator the timesheet UI reads, alongside ``uses_leave_api``.
    """

    id: UUID
    xero_id: str | None
    xero_tenant_id: str | None
    name: str
    uses_leave_api: bool
    # float, not Decimal: v1's client is typed `z.number()`, and a Decimal
    # would serialise as a JSON string and fail that validation in the SPA.
    multiplier: float | None
    xero_last_modified: datetime | None
    xero_last_synced: datetime | None
    created_at: datetime
    updated_at: datetime


@router.get(
    "/xero/pay-items/",
    auth=auth,
    operation_id="xero_pay_items_list",
    response=list[XeroPayItemOut],
    summary="List Xero pay items (earnings rates and leave types)",
    tags=["xero"],
)
def xero_pay_items_list(request: HttpRequest) -> list[XeroPayItem]:
    """Every pay item, ordered leave-types-last then by name.

    A bare array rather than a paginated envelope: the table is a handful of
    rows a store loads once, and v1's client is typed for an array.
    """
    return list(XeroPayItem.objects.all())
