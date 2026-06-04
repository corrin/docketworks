import copy
import hashlib
import json
import re
from typing import Any, Iterable, Optional

from django.http import HttpRequest
from django.utils import timezone

from apps.workflow.models import SearchTelemetryEvent
from apps.workflow.services.error_persistence import persist_app_error

SEARCH_TOKEN_RE = re.compile(r"[a-z0-9]+")
MAX_SEARCH_TELEMETRY_RESULTS = 100


def normalize_search_query(value: str) -> str:
    return " ".join(SEARCH_TOKEN_RE.findall((value or "").lower()))


def stable_event_hash(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class SearchTelemetryService:
    """Best-effort persisted telemetry for search quality analysis."""

    @staticmethod
    def log_search(
        *,
        request: Optional[HttpRequest],
        domain: str,
        source: str,
        query: str,
        result_count: int,
        returned_result_ids: Iterable[Any],
        filters: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
        source_event_hash: Optional[str] = None,
        occurred_at=None,
    ) -> bool:
        if not normalize_search_query(query) and not filters:
            return False

        user = SearchTelemetryService._authenticated_user(request)
        result_ids = [
            str(result_id)
            for result_id in list(returned_result_ids)[:MAX_SEARCH_TELEMETRY_RESULTS]
        ]
        capped_metadata = SearchTelemetryService._cap_metadata_results(metadata or {})
        values = {
            "event_type": SearchTelemetryEvent.EventType.SEARCH,
            "domain": domain,
            "source": source[:100],
            "query": query[:255],
            "normalized_query": normalize_search_query(query)[:255],
            "filters": filters or {},
            "result_count": max(0, int(result_count)),
            "returned_count": len(result_ids),
            "returned_result_ids": result_ids,
            "metadata": capped_metadata,
            "occurred_at": occurred_at or timezone.now(),
            "created_by": user,
        }
        try:
            if source_event_hash:
                _, created = SearchTelemetryEvent.objects.get_or_create(
                    source_event_hash=source_event_hash,
                    defaults=values,
                )
                return created
            else:
                SearchTelemetryEvent.objects.create(**values)
                return True
        except Exception as exc:
            persist_app_error(exc)
            return False

    @staticmethod
    def log_click(
        *,
        request: Optional[HttpRequest],
        domain: str,
        source: str,
        query: str,
        selected_result_id: str,
        selected_label: str = "",
        selected_rank: Optional[int] = None,
        result_count: int = 0,
        filters: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        if not normalize_search_query(query) and not filters:
            return False

        user = SearchTelemetryService._authenticated_user(request)
        try:
            SearchTelemetryEvent.objects.create(
                event_type=SearchTelemetryEvent.EventType.CLICK,
                domain=domain,
                source=source[:100],
                query=query[:255],
                normalized_query=normalize_search_query(query)[:255],
                filters=filters or {},
                result_count=max(0, int(result_count)),
                selected_result_id=str(selected_result_id)[:255],
                selected_label=selected_label[:255],
                selected_rank=selected_rank,
                metadata=SearchTelemetryService._cap_metadata_results(metadata or {}),
                created_by=user,
            )
            return True
        except Exception as exc:
            persist_app_error(exc)
            return False

    @staticmethod
    def _authenticated_user(request: Optional[HttpRequest]):
        user = getattr(request, "user", None) if request else None
        if getattr(user, "is_authenticated", False):
            return user
        return None

    @staticmethod
    def _cap_metadata_results(metadata: dict[str, Any]) -> dict[str, Any]:
        capped_metadata = copy.deepcopy(metadata)
        results = capped_metadata.get("results")
        if isinstance(results, list):
            capped_metadata["results"] = results[:MAX_SEARCH_TELEMETRY_RESULTS]
        return capped_metadata
