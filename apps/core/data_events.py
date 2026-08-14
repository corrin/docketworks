"""Observer seam between a data writer and whatever publishes data versions.

``apps.job`` has to announce the one freshness bump it makes outside the ORM
signals, but core sits BELOW every domain app in the layer contract and so
cannot know that ``apps.operations`` is what listens. The publisher registers
itself from ``OperationsConfig.ready()``; writers only call
``notify_data_changed()``.

An unregistered publisher raises rather than no-opping: silence here is a
permanently stale tab with no error anywhere, which is the failure the push
substrate exists to remove (ADR 0015).
"""

from collections.abc import Callable

_publisher: Callable[[], None] | None = None


def register_publisher(publisher: Callable[[], None]) -> None:
    """Install the one data-change publisher, at app-ready time."""
    global _publisher  # noqa: PLW0603 -- module-level registry; the seam IS the state
    if _publisher is not None and _publisher is not publisher:
        raise RuntimeError(
            f"A data-change publisher is already registered ({_publisher!r}); "
            f"one implementation per concept (ADR 0039)."
        )
    _publisher = publisher


def notify_data_changed() -> None:
    """Announce a write the ORM signals cannot see."""
    if _publisher is None:
        raise RuntimeError(
            "No data-change publisher is registered; apps.operations.ready() installs it."
        )
    _publisher()
