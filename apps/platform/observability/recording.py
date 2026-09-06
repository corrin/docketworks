"""Recording one row per external vendor call.

The shape follows ``apps.core.errors.persist_app_error``: a frozen context
dataclass rather than a long keyword signature, so a new meter is a typed
field instead of another positional argument at five call sites.
"""

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlsplit

import requests

from apps.platform.observability.models import VendorCall


@dataclass(frozen=True, kw_only=True, slots=True)
class VendorCallRecord:
    """What one vendor call consumed, and what the vendor said remained.

    Every meter is optional because a vendor reports only its own: Xero
    returns remaining-quota headers and no token count, the LLM gateway the
    reverse. ``None`` here means "this vendor does not report this meter",
    which is a real value with a real reader, not a widened annotation.
    The separate USD estimate is supplied only by the LLM gateway.
    """

    vendor: VendorCall.Vendor
    method: str
    url: str
    duration_ms: int
    status_code: int | None = None
    day_remaining: int | None = None
    minute_remaining: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    model_name: str | None = None
    estimated_cost_usd: Decimal | None = None


def endpoint_of(url: str) -> str:
    """Reduce a request URL to the path the rows group by."""
    return urlsplit(url).path


def record_vendor_call(record: VendorCallRecord) -> None:
    """Write the row for one vendor call.

    Deliberately unguarded. A failing insert is a defect, and the codebase
    already accepts an unguarded write on this exact path — the Xero client
    updated ``XeroApp`` inline on every response before this table existed.
    Swallowing here would leave the spend invisible in precisely the runs
    where the database is also unhappy.
    """
    VendorCall.objects.create(
        vendor=record.vendor,
        method=record.method,
        endpoint=endpoint_of(record.url),
        duration_ms=record.duration_ms,
        status_code=record.status_code,
        day_remaining=record.day_remaining,
        minute_remaining=record.minute_remaining,
        tokens_in=record.tokens_in,
        tokens_out=record.tokens_out,
        model_name=record.model_name,
        estimated_cost_usd=record.estimated_cost_usd,
    )


def record_response(response: requests.Response, *, vendor: VendorCall.Vendor) -> None:
    """Record one response a ``requests``-based vendor returned.

    ``elapsed`` is requests' own measurement, so the duration is the library's
    rather than a second stopwatch of ours (ADR 0032).

    A transport failure — DNS, connection refused, timeout — raises before a
    response exists and so records nothing. That is the intended reading: the
    request never reached the vendor, so it spent none of the vendor's budget.
    Refusals the vendor did answer, 4xx and 429 included, arrive here like any
    other response.
    """
    record_vendor_call(
        VendorCallRecord(
            vendor=vendor,
            method=response.request.method or "GET",
            url=response.request.url or "",
            duration_ms=int(response.elapsed.total_seconds() * 1000),
            status_code=response.status_code,
        )
    )


def record_responses(session: requests.Session, *, vendor: VendorCall.Vendor) -> None:
    """Record every response this session receives.

    For a client that holds a session across several endpoints, the hook is
    the library's own extension point and fires for every verb helper, because
    they all funnel through ``Session.request``. A caller making a single
    one-off request calls ``record_response`` directly instead — same one
    implementation, reached without a session it would otherwise not need.
    """

    def hook(response: requests.Response, **_kwargs: object) -> None:
        record_response(response, vendor=vendor)

    session.hooks["response"].append(hook)
