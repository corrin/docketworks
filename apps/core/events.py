"""The one SSE view scaffold behind every eventstream endpoint.

Fable: hoisted when the Xero sync stream became the third line-for-line copy
of the auth-dance + eventstream + anti-gzip sequence (ADR 0039 — two copies
were tolerated, three is a pattern). Each channel's view stays a thin,
separately-mounted function in its own app, because the channel choice, its
auth class and its rationale are per-domain facts; only the mechanics live
here.

Fable: these views are deliberately not ninja operations: the response never
ends, so the generated axios client cannot call one, and inside ninja each
would put an operation in the OpenAPI schema that the API-boundary gate
would then demand be called through generated code.
"""

from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.http.response import HttpResponseBase
from django_eventstream import views as eventstream_views
from ninja.errors import AuthenticationError, AuthorizationError

from apps.core.auth import CookieJWTAuth


def authed_event_stream(
    request: HttpRequest, auth: CookieJWTAuth, channel: str
) -> HttpResponseBase:
    """Authenticate with ``auth`` and open an eventstream on ``channel``."""
    try:
        user = auth.authenticate(request, request.COOKIES.get(auth.param_name))
    # deliberate-swallow: Fable: the auth classes' two typed refusals (bad or
    # expired token; wrong role) must both land on the same unrevealing 401 —
    # telling an unauthorised caller WHICH it was only helps the caller.
    # Anything else is an infrastructure or programming failure and
    # propagates to the error-persisting layer instead of masquerading as a
    # quiet 401 (the blanket catch this narrows was inherited from the
    # pre-hoist views).
    except (AuthenticationError, AuthorizationError):
        user = None
    if user is None:
        return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)
    if not isinstance(user, get_user_model()):
        raise TypeError(f"Cookie JWT resolved a non-Staff principal: {type(user)!r}")

    # Fable: django-eventstream reads ``request.user`` itself rather than
    # taking a user argument (its eventrequest.py), and
    # AuthenticationMiddleware left it anonymous — that middleware reads the
    # Django session, not the JWT cookie this contract authenticates with.
    request.user = user

    response = eventstream_views.events(request, channels=[channel])
    # Fable: GZipMiddleware compresses streaming responses, batching events
    # into compression blocks; it skips any response already declaring an
    # encoding. Cache-Control and X-Accel-Buffering come from the library's
    # own defaults.
    response["Content-Encoding"] = "identity"
    return response
