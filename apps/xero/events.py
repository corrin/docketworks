"""SSE stream carrying Xero sync progress — a plain Django view, outside ninja.

Fable: **This endpoint only reads.** The sync runs in
``apps.xero.sync_worker.xero_sync_task``; this stream relays the progress
events that worker publishes. v1 buffered messages in the shared cache and
had an SSE view poll the buffer by index every half-second — a hand-rolled
replay mechanism ADR 0047 replaces with django-eventstream. A reader that
connects late starts from the next event; the present state it missed is one
``sync-info`` fetch away (``sync_in_progress`` + per-entity ``last_syncs``),
which is the polling sibling this stream pairs with.

Fable: Its own channel rather than an event on data-versions. That stream
authenticates any staff member; sync progress is office-only — it carries
AppError ids and operational detail, and every action on its page is
``office_auth`` — so sharing a channel would push it to every logged-in
workshop worker's open stream. Mechanics live in ``apps.core.events``.
"""

from django.conf import settings
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET

from apps.core.auth import OfficeStaffCookieJWTAuth
from apps.core.events import authed_event_stream


@require_GET
def xero_sync_stream(request: HttpRequest) -> HttpResponseBase:
    """Stream Xero sync progress events to the connection page."""
    return authed_event_stream(request, OfficeStaffCookieJWTAuth(), settings.XERO_SYNC_CHANNEL)
