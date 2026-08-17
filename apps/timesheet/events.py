"""SSE stream reporting a payroll-posting run — a plain Django view, outside ninja.

Opus: **This endpoint only reads.** The posting itself happens in
``apps.timesheet.tasks.post_payroll_week_task``. v1 did the Xero writing inside
this GET handler, which made fetching a URL post payroll, and meant a client
that disconnected mid-batch destroyed the only record of which staff had
succeeded. Here the task owns the work and writes its progress to the cache;
this view replays that log.

Opus: Deliberately not a ninja operation, for the same reasons as the data-versions
stream: the response does not end, it is consumed by ``EventSource`` rather
than the generated client, and inside ninja it would put an operation in the
OpenAPI schema that the API-boundary gate would then require calling through
generated code.

Opus: Deliberately not django-eventstream either, which is the library this repo
otherwise uses for SSE (ADR 0032). That library pushes live events but cannot
replay what a reader missed without a storage backend, which ADR 0047's "Do
not" section forbids enabling — and replaying what was missed is the entire
point of moving the work out of the request. Reading an append-only cache log
from an offset gives exact resume in a way the library, as configured here,
cannot.
"""

import json
import logging
import time
from collections.abc import Iterator

from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET

from apps.accounts.models import Staff
from apps.core.auth import SuperuserCookieJWTAuth
from apps.timesheet.services import payroll_progress

logger = logging.getLogger(__name__)

# Opus: How often to look for newly published events. The posting run makes several
# rate-limited Xero calls per employee, so events arrive seconds apart; polling
# faster would only spin.
POLL_INTERVAL_SECONDS = 0.5
# Opus: A ceiling so a task that dies without publishing a terminal event cannot hold
# a connection open forever. Comfortably longer than a full staff list takes.
MAX_STREAM_SECONDS = 1800


def _frame(event: dict[str, object]) -> str:
    """Encode one event as an SSE data frame."""
    return f"data: {json.dumps(event)}\n\n"


def _event_stream(task_id: str) -> Iterator[str]:
    """Replay the run's events from the start, then follow it until it ends."""
    offset = 0
    deadline = time.monotonic() + MAX_STREAM_SECONDS
    while time.monotonic() < deadline:
        events = payroll_progress.events_since(task_id, offset)
        offset += len(events)
        for event in events:
            yield _frame(event)
            if payroll_progress.is_terminal(event):
                return
        if not events:
            time.sleep(POLL_INTERVAL_SECONDS)
    logger.warning("Payroll posting stream %s hit its time limit with no terminal event", task_id)
    yield _frame(
        {
            "event": "error",
            "message": (
                "The payroll posting run stopped reporting progress. Check Xero for what "
                "was posted before running it again."
            ),
        }
    )


@require_GET
def payroll_post_stream(request: HttpRequest, task_id: str) -> HttpResponseBase:
    """Stream a payroll-posting run's progress to the weekly timesheets page."""
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

    if payroll_progress.get_task(task_id) is None:
        # Opus: Either the id was never registered or its hour has elapsed. Saying so
        # beats streaming an empty log the client would wait on forever.
        return JsonResponse(
            {"detail": f"No payroll posting run {task_id} is in progress."}, status=404
        )

    response = StreamingHttpResponse(_event_stream(task_id), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    # Opus: nginx buffers proxied responses by default, which would hold every event
    # until the run finished.
    response["X-Accel-Buffering"] = "no"
    # Opus: GZipMiddleware compresses streaming responses, batching events into
    # compression blocks; it skips anything already declaring an encoding.
    response["Content-Encoding"] = "identity"
    return response
