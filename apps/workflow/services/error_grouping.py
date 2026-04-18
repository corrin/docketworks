import hashlib
from typing import Any, Dict, Type

from django.db.models import Count, Max, Min, OuterRef, QuerySet, Subquery

from apps.workflow.models import AppError, XeroError


def _fingerprint(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _paginate(limit: int, offset: int) -> tuple[int, int]:
    if limit <= 0:
        limit = 1
    limit = min(limit, 200)
    offset = max(offset, 0)
    return limit, offset


def _group_payload(
    queryset: QuerySet[AppError],
    *,
    group_field: str,
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    model = queryset.model

    # Subquery is intentionally unfiltered: latest_id is an informational
    # pointer to the most-recent row by timestamp for this message.
    latest_id_sq = (
        model.objects.filter(**{group_field: OuterRef(group_field)})
        .order_by("-timestamp")
        .values("id")[:1]
    )

    aggregated = (
        queryset.values(group_field)
        .annotate(
            occurrence_count=Count("id"),
            first_seen=Min("timestamp"),
            last_seen=Max("timestamp"),
            severity=Max("severity"),
            app=Max("app"),
            latest_id=Subquery(latest_id_sq),
        )
        .order_by("-last_seen")
    )
    total = aggregated.count()
    rows = list(aggregated[offset : offset + limit])

    results = [
        {
            "fingerprint": _fingerprint(row[group_field]),
            "message": row[group_field],
            "occurrence_count": row["occurrence_count"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "severity": row["severity"],
            "app": row["app"],
            "latest_id": row["latest_id"],
        }
        for row in rows
    ]

    next_offset = str(offset + limit) if offset + limit < total else None
    prev_offset = str(max(offset - limit, 0)) if offset > 0 else None

    return {
        "count": total,
        "next": next_offset,
        "previous": prev_offset,
        "results": results,
    }


def _build_queryset(
    model: Type[AppError],
    *,
    app: str | None,
    severity: int | None,
    resolved: bool | None,
    job_id: str | None,
    user_id: str | None,
) -> QuerySet[AppError]:
    queryset: QuerySet[AppError] = model.objects.all()
    if resolved is None:
        queryset = queryset.filter(resolved=False)
    else:
        queryset = queryset.filter(resolved=resolved)
    if app:
        queryset = queryset.filter(app__icontains=app.strip())
    if severity is not None:
        queryset = queryset.filter(severity=severity)
    if job_id:
        queryset = queryset.filter(job_id=job_id)
    if user_id:
        queryset = queryset.filter(user_id=user_id)
    return queryset


def list_grouped_app_errors(
    *,
    limit: int = 50,
    offset: int = 0,
    app: str | None = None,
    severity: int | None = None,
    resolved: bool | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    limit, offset = _paginate(limit, offset)
    queryset = _build_queryset(
        AppError,
        app=app,
        severity=severity,
        resolved=resolved,
        job_id=job_id,
        user_id=user_id,
    )
    return _group_payload(queryset, group_field="message", limit=limit, offset=offset)


def list_grouped_xero_errors(
    *,
    limit: int = 50,
    offset: int = 0,
    app: str | None = None,
    severity: int | None = None,
    resolved: bool | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    limit, offset = _paginate(limit, offset)
    queryset = _build_queryset(
        XeroError,
        app=app,
        severity=severity,
        resolved=resolved,
        job_id=job_id,
        user_id=user_id,
    )
    return _group_payload(queryset, group_field="message", limit=limit, offset=offset)
