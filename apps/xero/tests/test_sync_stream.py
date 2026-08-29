"""The SSE endpoint the Xero page opens for sync-progress pushes.

Only the handshake is asserted here, like its data-versions sibling: status,
media type, the anti-gzip header, and the async property. The stream body
belongs to django-eventstream's suite; the worker's publishes are pinned in
``test_sync_dispatch.py``. Office-gating matters: progress events carry
AppError ids and operational detail, so a workshop login must get the same
unrevealing 401 as an anonymous caller.
"""

from typing import cast

import pytest
from django.http import StreamingHttpResponse
from django.test import Client

pytestmark = pytest.mark.django_db

STREAM_URL = "/api/xero/sync/stream/"


def test_requires_the_access_cookie(client: Client) -> None:
    """The view sits outside ninja, so it enforces the cookie JWT itself."""
    response = client.get(STREAM_URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication credentials were not provided."}


def test_workshop_staff_get_the_same_unrevealing_401(non_office_api: Client) -> None:
    response = non_office_api.get(STREAM_URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication credentials were not provided."}


def test_opens_an_event_stream_for_office_staff(api: Client) -> None:
    response = api.get(STREAM_URL)
    try:
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "text/event-stream"
        # GZipMiddleware compresses streaming responses and skips any that
        # already declares a Content-Encoding; without this the events sit in
        # a compression buffer instead of reaching the tab.
        assert response.headers["Content-Encoding"] == "identity"
        # A sync generator makes StreamingHttpResponse drain everything into
        # a list before sending a byte — a stream that does not stream. The
        # payroll stream shipped exactly that defect; pin the property.
        assert cast("StreamingHttpResponse", response).is_async
    finally:
        response.close()
