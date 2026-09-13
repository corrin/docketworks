"""Read Xero's remaining quota, at the price of one call.

Xero reports remaining quota only in the headers of a tenant-scoped response,
and every such response is itself a counted call; the identity endpoints
(connections, token) carry no limit headers at all. So there is no free read.
The cheapest paid one is GET Organisation, which also names the tenant the
credentials are bound to — the two questions an operator asks before spending
a long run are answered together.

``quota_floor_breached`` (client.py) is the free read: the freshest header the
recorder saw. It is right for a scheduled job that will call Xero anyway, and
wrong for a preflight, where the last reading may be hours old or from before
another consumer spent the day.
"""

from dataclasses import dataclass

from xero_python.accounting import AccountingApi

from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.client import DAY_LIMIT_HEADER, MINUTE_LIMIT_HEADER


class XeroQuotaUnreportedError(Exception):
    """A tenant-scoped response arrived without a quota header.

    Xero sends both headers on every tenant-scoped response, so their absence
    means the call did not reach the tenant API. A preflight that read that
    as "unknown" and proceeded would be the half-hour failure it exists to
    prevent.
    """


@dataclass(frozen=True)
class XeroQuotaReading:
    """What one tenant-scoped call reported about the connection."""

    organisation_name: str
    day_remaining: int
    minute_remaining: int


def read_day_quota() -> XeroQuotaReading:
    """Spend one call and return the tenant's name and remaining quota."""
    api = AccountingApi(get_api_client())
    # The SDK discards headers unless told to hand back the whole triple.
    body, _status, headers = api.get_organisations(
        xero_tenant_id=get_tenant_id(), _return_http_data_only=False
    )
    # A 200 with no organisation, or one without a name, is a response from
    # something other than the tenant API, the same as a missing header.
    if not body.organisations or body.organisations[0].name is None:
        raise XeroQuotaUnreportedError("Xero's response named no organisation")
    return XeroQuotaReading(
        organisation_name=body.organisations[0].name,
        day_remaining=_required_count(headers, DAY_LIMIT_HEADER),
        minute_remaining=_required_count(headers, MINUTE_LIMIT_HEADER),
    )


def _required_count(headers: dict[str, str], name: str) -> int:
    if name not in headers:
        raise XeroQuotaUnreportedError(f"Xero's response carried no {name} header")
    return int(headers[name])
