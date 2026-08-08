"""SSE stream of Xero sync progress — a plain Django view, outside ninja.

Deliberately not a ninja operation: the stream is infinite, is consumed by
``EventSource`` rather than the generated client, and inside ninja it would
pollute the OpenAPI schema with an operation the API-boundary gate would then
require calling through generated code. Same mounting precedent as the OAuth
views and the webhook (config/urls.py).

Auth: the office cookie-JWT, checked directly — plain views sit outside
ninja's auth classes, and EventSource sends cookies same-origin.
"""

import json
import logging
import time
from collections.abc import Iterator

from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.http.response import HttpResponseBase
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.auth import CookieJWTAuth
from apps.xero.auth import has_stored_token
from apps.xero.sync_service import XeroSyncService

logger = logging.getLogger(__name__)


def generate_xero_sync_events() -> Iterator[str]:
    """Yield SSE-framed JSON sync progress messages.

    Polls the shared-cache message list every 0.5s, attaches to a sync
    started after the stream opened, and ends with a "Sync stream ended"
    marker whose sync_status reflects whether any error events occurred.
    Unexpected errors emit a single error event plus the end marker rather
    than re-raising — half-closed SSE sockets cannot render a 500.
    """
    try:
        # Presence check, not get_valid_token(): a GET stream must not
        # trigger the token refresh (a DB write) the ping endpoint's
        # ledgered exception covers.
        if not has_stored_token():
            payload: dict[str, object] = {
                "datetime": timezone.now().isoformat(),
                "entity": "sync",
                "severity": "error",
                "message": "No valid Xero token. Please authenticate.",
                "progress": None,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            return

        start_payload = {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "info",
            "message": "Starting Xero sync",
            "progress": 0.0,
        }
        yield f"data: {json.dumps(start_payload)}\n\n"

        task_id = XeroSyncService.get_active_task_id()
        last_index = 0

        while True:
            active_task_id = XeroSyncService.get_active_task_id()

            if task_id is None and active_task_id:
                task_id = active_task_id
                last_index = 0

            if task_id is None:
                yield ": keep-alive\n\n"
                time.sleep(0.5)
                continue

            messages = XeroSyncService.get_messages(task_id, last_index)

            for msg in messages:
                yield f"data: {json.dumps(msg)}\n\n"
                last_index += 1

            has_active_lock = active_task_id == task_id and active_task_id is not None

            # Lock released and buffer drained → emit the terminal marker.
            if not has_active_lock and not messages:
                error_messages = [
                    m.get("message")
                    for m in XeroSyncService.get_messages(task_id, 0)
                    if m.get("severity") == "error"
                ]
                end_payload: dict[str, object] = {
                    "datetime": timezone.now().isoformat(),
                    "entity": "sync",
                    "severity": "info",
                    "message": "Sync stream ended",
                    "progress": 1.0,
                    "sync_status": "error" if error_messages else "success",
                }
                if error_messages:
                    end_payload["error_messages"] = error_messages
                yield f"data: {json.dumps(end_payload)}\n\n"
                break

            if not messages:
                yield ": keep-alive\n\n"

            time.sleep(0.5)

    # deliberate-swallow: a half-closed SSE socket cannot render a 500; the
    # error event + end marker are the only channel left to the client
    except Exception:
        logger.exception("Unexpected error in generate_xero_sync_events")
        error_payload = {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "error",
            "message": "Internal server error during sync.",
            "progress": None,
        }
        yield f"data: {json.dumps(error_payload)}\n\n"

        final_payload = {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "info",
            "message": "Sync stream ended",
            "progress": None,
        }
        yield f"data: {json.dumps(final_payload)}\n\n"


@require_GET
def stream_xero_sync(request: HttpRequest) -> HttpResponseBase:
    """Serve an EventSource stream of Xero sync events."""
    auth = CookieJWTAuth()
    try:
        user = auth.authenticate(request, request.COOKIES.get(auth.param_name))
    # deliberate-swallow: any auth failure has the same one answer, the 401
    # below — the JSON body mirrors ninja's envelope wording
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)

    response = StreamingHttpResponse(generate_xero_sync_events(), content_type="text/event-stream")
    # Prevent Django or proxies from buffering
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    response["Content-Encoding"] = "identity"
    return response
