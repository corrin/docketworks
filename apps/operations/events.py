"""SSE stream of data-version documents — a plain Django view, outside ninja.

Deliberately not a ninja operation: the response never ends, is consumed by
``EventSource`` rather than the generated client, and inside ninja it would
put an operation in the OpenAPI schema that the API-boundary gate would then
require calling through generated code. Same mounting precedent as the Xero
OAuth views and the webhook (config/urls.py).

Auth: the cookie JWT, checked here directly — plain views sit outside ninja's
auth classes, and ``EventSource`` can send a same-origin cookie but cannot set
an Authorization header.

Everything past the handshake belongs to django-eventstream: it owns the
stream loop, the ``stream-open`` event and the ~20s ``keep-alive`` frames
(ADR 0032 — none of that is ours to rewrite). No storage backend is
configured (ADR 0047's "Do not" section forbids enabling one), so no event
ids are emitted and there is no Last-Event-ID resume: catch-up after a
reconnect is the client's job, done by fetching data-versions on the
library's ``stream-open`` event.
"""

from django.conf import settings
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET

from apps.core.auth import CookieJWTAuth
from apps.core.events import authed_event_stream


@require_GET
def data_versions_stream(request: HttpRequest) -> HttpResponseBase:
    """Serve an EventSource stream of ``data_versions`` events."""
    return authed_event_stream(request, CookieJWTAuth(), settings.DATA_VERSIONS_CHANNEL)
