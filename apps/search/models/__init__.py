"""Search telemetry model exports.

The model pins ``workflow_searchtelemetryevent`` because data restores depend
on that stable database identifier.
"""

from .search_telemetry_event import SearchTelemetryEvent

__all__ = [
    "SearchTelemetryEvent",
]
