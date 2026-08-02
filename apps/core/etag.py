"""Shared HTTP ETag helpers for updated-at versioned resources (ADR 0003).

The ONE etag implementation in v2. v1 carried three files: this generic module
(``apps/workflow/etag.py``) plus two thin wrappers that only bound the resource
label — ``apps/job/etag.py`` (``"job"``) and ``apps/purchasing/etag.py``
(``"po"``). The wrappers delegated here and added no behaviour, so v2 keeps
only the generic functions; domain code passes its resource label directly
(e.g. ``generate_updated_at_etag("job", job.id, job.updated_at)``).
"""

from datetime import UTC, datetime
from uuid import UUID

from django.utils import timezone
from django.utils.http import parse_etags, quote_etag


class PreconditionFailedError(Exception):
    """Raised when an optimistic-concurrency precondition is not met.

    v1 home: ``apps/workflow/exceptions.py``. Lives beside the ETag helpers in
    v2 because the OCC contract (ADR 0003) is one concept: services raise this
    under ``select_for_update`` and the API envelope answers 412.
    """


def updated_at_etag_value(
    resource: str,
    resource_id: UUID,
    updated_at: datetime,
) -> str:
    """Return the opaque value for a full-precision resource ETag."""
    if timezone.is_naive(updated_at):
        raise ValueError("ETag timestamps must be timezone-aware")

    timestamp = updated_at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return f"{resource}:{resource_id}:{timestamp}"


def generate_updated_at_etag(
    resource: str,
    resource_id: UUID,
    updated_at: datetime,
) -> str:
    """Return a strong ETag suitable for both If-Match and If-None-Match."""
    return quote_etag(updated_at_etag_value(resource, resource_id, updated_at))


def if_match_satisfied(header: str, current_etag: str) -> bool:
    """Apply the application's exact-current-version mutation contract."""
    return current_etag in parse_etags(header)


def if_none_match_satisfied(header: str, current_etag: str) -> bool:
    """Apply RFC weak comparison semantics for conditional GET requests."""
    candidates = parse_etags(header)
    if "*" in candidates:
        return True

    current_weak_value = current_etag.removeprefix("W/")
    return any(candidate.removeprefix("W/") == current_weak_value for candidate in candidates)
