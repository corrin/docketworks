"""SSE stream carrying Xero sync progress — a plain Django view, outside ninja.

Fable: **This endpoint only reads.** The sync runs in
``apps.xero.sync_worker.xero_sync_task``; this stream relays the progress
events that worker publishes. v1 buffered messages in the shared cache and
had an SSE view poll the buffer by index every half-second — a hand-rolled
replay mechanism ADR 0047 replaces with django-eventstream, the same library
and shape as ``apps/operations/events.py`` and ``apps/timesheet/events.py``.
A reader that connects late starts from the next event; the present state it
missed is one ``sync-info`` fetch away (``sync_in_progress`` + per-entity
``last_syncs``), which is the polling sibling this stream pairs with.

Fable: Deliberately not a ninja operation, for the same reason its two
siblings are not: the response never ends, so the generated axios client
cannot call it, and inside ninja it would put an operation in the OpenAPI
schema that the API-boundary gate would then demand be called through
generated code.

Fable: Its own channel rather than an event on data-versions. That stream
authenticates any staff member; sync progress is office-only — it carries
AppError ids and operational detail, and every action on its page is
``office_auth`` — so sharing a channel would push it to every logged-in
workshop worker's open stream.
"""

import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET
from django_eventstream import views as eventstream_views

from apps.accounts.models import Staff
from apps.core.auth import OfficeStaffCookieJWTAuth

logger = logging.getLogger(__name__)


@require_GET
def xero_sync_stream(request: HttpRequest) -> HttpResponseBase:
    """Stream Xero sync progress events to the connection page."""
    auth = OfficeStaffCookieJWTAuth()
    try:
        user = auth.authenticate(request, request.COOKIES.get(auth.param_name))
    # deliberate-swallow: Fable: an unreadable, expired or non-office token
    # must all land on the same unrevealing 401 — mirroring the payroll
    # stream's contract; the distinction helps only an unauthorised caller.
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)
    if not isinstance(user, Staff):
        raise TypeError(f"Cookie JWT resolved a non-Staff principal: {type(user)!r}")

    # Fable: django-eventstream reads ``request.user`` itself rather than
    # taking a user argument, and AuthenticationMiddleware left it anonymous —
    # that middleware reads the Django session, not the JWT cookie this
    # contract authenticates with.
    request.user = user

    response = eventstream_views.events(request, channels=[settings.XERO_SYNC_CHANNEL])
    # Fable: GZipMiddleware compresses streaming responses, batching events
    # into compression blocks; it skips any response already declaring an
    # encoding. Cache-Control and X-Accel-Buffering come from the library's
    # own defaults.
    response["Content-Encoding"] = "identity"
    return response
