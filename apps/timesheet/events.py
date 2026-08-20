"""SSE stream carrying the payroll run document — a plain Django view, outside ninja.

Opus: **This endpoint only reads.** The posting happens in
``apps.timesheet.tasks.post_payroll_week_task``. v1 did the Xero writing inside
this GET handler, which made fetching a URL post payroll, and meant a client that
disconnected mid-batch destroyed the only record of which staff had succeeded.

Opus: It is django-eventstream now, the same library and the same shape as
``apps/operations/events.py``. The version this replaces hand-rolled a poll loop
over an append-only event log, on the argument that the library cannot replay
what a reader missed without a storage backend ADR 0047 forbids. That argument
was answered by changing the payload rather than the transport: every push
carries the WHOLE run document, so there is nothing to replay — a reader that
connects late, reconnects, or reloads needs the present, and gets it from the
polling sibling on ``stream-open``.

Opus: Deliberately not a ninja operation, for the same reason the data-versions
stream is not: the response does not end, so it is not something the generated
axios client can call, and inside ninja it would put an operation in the OpenAPI
schema that the API-boundary gate would then demand be called through generated
code.

Opus: Its own channel rather than an event on the data-versions one. That stream
authenticates any staff member; this document carries names, hours and pay basis,
so it is superuser-only — sharing a channel would push other people's pay to
every logged-in worker's open stream.
"""

import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET
from django_eventstream import views as eventstream_views

from apps.accounts.models import Staff
from apps.core.auth import SuperuserCookieJWTAuth

logger = logging.getLogger(__name__)


@require_GET
def payroll_runs_stream(request: HttpRequest) -> HttpResponseBase:
    """Stream this organisation's payroll run documents to the weekly page."""
    auth = SuperuserCookieJWTAuth()
    try:
        user = auth.authenticate(request, request.COOKIES.get(auth.param_name))
    # deliberate-swallow: Opus: this stream reports other staff members' pay, so an
    # unreadable, expired or non-superuser token must all land on the same
    # unrevealing 401 — telling an unauthorised caller WHICH of those it was
    # would confirm the run exists
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)
    if not isinstance(user, Staff):
        raise TypeError(f"Cookie JWT resolved a non-Staff principal: {type(user)!r}")

    # Opus: django-eventstream reads ``request.user`` itself rather than taking a
    # user argument (its eventrequest.py), and AuthenticationMiddleware left it
    # anonymous — that middleware reads the Django session, not the JWT cookie
    # this contract authenticates with.
    request.user = user

    response = eventstream_views.events(request, channels=[settings.PAYROLL_RUNS_CHANNEL])
    # Opus: GZipMiddleware compresses streaming responses, batching events into
    # compression blocks; it skips any response already declaring an encoding.
    # Cache-Control and X-Accel-Buffering come from the library's own defaults.
    response["Content-Encoding"] = "identity"
    return response
