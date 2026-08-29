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

from django.conf import settings
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET

from apps.core.auth import SuperuserCookieJWTAuth
from apps.core.events import authed_event_stream


@require_GET
def payroll_runs_stream(request: HttpRequest) -> HttpResponseBase:
    """Stream this organisation's payroll run documents to the weekly page."""
    return authed_event_stream(request, SuperuserCookieJWTAuth(), settings.PAYROLL_RUNS_CHANNEL)
