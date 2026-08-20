"""The SSE endpoint the SPA opens for data-version pushes.

Only the handshake is asserted here: status, media type, and the header that
keeps the response out of GZipMiddleware. The stream body itself belongs to
django-eventstream's own suite and to the E2E spec, which is the only place a
real EventSource is on the other end.
"""

from typing import cast

import pytest
from django.http import StreamingHttpResponse
from django.test import Client

pytestmark = pytest.mark.django_db

STREAM_URL = "/api/data-versions/stream/"


def test_requires_the_access_cookie(client: Client) -> None:
    """The view sits outside ninja, so it enforces the cookie JWT itself."""
    response = client.get(STREAM_URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication credentials were not provided."}


def test_opens_an_event_stream_for_an_authenticated_client(api: Client) -> None:
    response = api.get(STREAM_URL)
    try:
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "text/event-stream"
        # GZipMiddleware compresses streaming responses and skips any that
        # already declares a Content-Encoding; without this the events sit in
        # a compression buffer instead of reaching the tab.
        assert response.headers["Content-Encoding"] == "identity"
        # Opus: Django decides `is_async` by whether `iter()` accepts the
        # generator, and a SYNC one makes `__aiter__` fall back to draining the
        # whole thing into a list before sending a byte — a stream that does not
        # stream, which every other assertion here still passes. The payroll
        # stream shipped exactly that defect; this pins the property rather than
        # trusting the library to keep its generator async.
        assert cast("StreamingHttpResponse", response).is_async
    finally:
        response.close()


def test_stream_is_not_cached(api: Client) -> None:
    """A cached SSE response would replay one snapshot forever."""
    response = api.get(STREAM_URL)
    try:
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["X-Accel-Buffering"] == "no"
    finally:
        response.close()
