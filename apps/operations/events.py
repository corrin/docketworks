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
from django.http import HttpRequest, JsonResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET
from django_eventstream.views import events

from apps.accounts.models import Staff
from apps.core.auth import CookieJWTAuth


@require_GET
def data_versions_stream(request: HttpRequest) -> HttpResponseBase:
    """Serve an EventSource stream of ``data_versions`` events."""
    auth = CookieJWTAuth()
    try:
        user = auth.authenticate(request, request.COOKIES.get(auth.param_name))
    # deliberate-swallow: every auth failure mode has the same one answer, the
    # 401 below — whose body mirrors ninja's envelope wording
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)
    if not isinstance(user, Staff):
        raise TypeError(f"Cookie JWT resolved a non-Staff principal: {type(user)!r}")

    # django-eventstream reads ``request.user`` itself rather than taking a
    # user argument (its eventrequest.py), and AuthenticationMiddleware left
    # it anonymous — that middleware reads the Django session, not the JWT
    # cookie this contract authenticates with.
    request.user = user

    response = events(request, channels=[settings.DATA_VERSIONS_CHANNEL])
    # GZipMiddleware sits second in MIDDLEWARE and does compress streaming
    # responses, which buffers events into compression blocks; it skips any
    # response that already declares a Content-Encoding. Cache-Control and
    # X-Accel-Buffering are already set by the library's add_default_headers,
    # so they are not repeated here.
    response["Content-Encoding"] = "identity"
    return response
