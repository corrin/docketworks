"""Search telemetry models, ported from v1's ``apps/workflow/models/``.

The model left v1's ``workflow`` app, so it pins
``Meta.db_table = "workflow_searchtelemetryevent"`` per the v2 porting rules.
"""

from .search_telemetry_event import SearchTelemetryEvent

__all__ = [
    "SearchTelemetryEvent",
]
