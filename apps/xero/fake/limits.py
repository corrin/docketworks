"""Xero's rate limits, kept as Xero keeps them: rolling windows per app and organisation.

The fake counts its own calls in the observability rows the real transport
writes (``apps.platform.observability``), because the fake transport IS the
paced client with only the socket replaced. So what a run spent is one record
whichever transport served it, the day-floor gate reads it, and past the
minute limit the fake answers the 429 Xero answered when it was provoked
(``recordings/rate_limit_minute.json``: status, no body, four headers), so
the paced client's sleep-and-retry runs under the fake too.
"""

import json
import math
from datetime import timedelta
from pathlib import Path

from django.utils import timezone
from xero_python.rest import RESTResponse

from apps.platform.observability.models import VendorCall
from apps.xero.fake.http import raw_response

#: Xero's published limits per app per organisation.
DAY_LIMIT = 5000
MINUTE_LIMIT = 60
DAY_WINDOW = timedelta(hours=24)
MINUTE_WINDOW = timedelta(minutes=1)

_REFUSAL = json.loads((Path(__file__).parent / "recordings" / "rate_limit_minute.json").read_text())
_REFUSAL_STATUS: int = _REFUSAL["response"]["status"]
#: The header names Xero's 429 carried; the values are this window's.
_REFUSAL_HEADERS: tuple[str, ...] = tuple(_REFUSAL["response"]["headers"])


def _calls_since(window: timedelta) -> int:

    return VendorCall.objects.filter(
        vendor=VendorCall.Vendor.XERO, occurred_at__gte=timezone.now() - window
    ).count()


def _oldest_ages_out_in(window: timedelta) -> int:

    oldest = (
        VendorCall.objects.filter(
            vendor=VendorCall.Vendor.XERO, occurred_at__gte=timezone.now() - window
        )
        .order_by("occurred_at")
        .values_list("occurred_at", flat=True)
        .first()
    )
    if oldest is None:
        return 1
    return max(1, math.ceil((oldest + window - timezone.now()).total_seconds()))


def quota_headers() -> dict[str, str]:
    """Return the two meters every tenant-scoped answer carries, after this call is counted."""
    return {
        "X-DayLimit-Remaining": str(max(0, DAY_LIMIT - _calls_since(DAY_WINDOW) - 1)),
        "X-MinLimit-Remaining": str(max(0, MINUTE_LIMIT - _calls_since(MINUTE_WINDOW) - 1)),
    }


def rate_limit_refusal() -> RESTResponse | None:
    """Xero's 429 when a window is full, or None when this call may proceed."""
    if _calls_since(MINUTE_WINDOW) >= MINUTE_LIMIT:
        problem, retry_after = "minute", _oldest_ages_out_in(MINUTE_WINDOW)
    elif _calls_since(DAY_WINDOW) >= DAY_LIMIT:
        problem, retry_after = "day", _oldest_ages_out_in(DAY_WINDOW)
    else:
        return None
    values = {
        **quota_headers(),
        "Retry-After": str(retry_after),
        "X-Rate-Limit-Problem": problem,
    }
    return raw_response(_REFUSAL_STATUS, b"", {name: values[name] for name in _REFUSAL_HEADERS})
