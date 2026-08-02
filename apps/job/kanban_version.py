"""Opaque version contract for incremental Kanban reconciliation."""

from dataclasses import dataclass
from datetime import UTC, datetime

from django.utils import timezone

_EMPTY_TIMESTAMP = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class KanbanDatasetVersion:
    """Typed representation of the Job dataset version sent to clients."""

    updated_at: datetime
    created_at: datetime
    count: int

    @classmethod
    def from_values(
        cls,
        *,
        updated_at: datetime | None,
        created_at: datetime | None,
        count: int,
    ) -> "KanbanDatasetVersion":
        """Build a version from raw values, validating awareness and count."""
        if count < 0:
            raise ValueError("Kanban version count cannot be negative")
        if updated_at is not None and timezone.is_naive(updated_at):
            raise ValueError("Kanban updated_at version must be timezone-aware")
        if created_at is not None and timezone.is_naive(created_at):
            raise ValueError("Kanban created_at version must be timezone-aware")

        return cls(
            updated_at=(updated_at or _EMPTY_TIMESTAMP).astimezone(UTC),
            created_at=(created_at or _EMPTY_TIMESTAMP).astimezone(UTC),
            count=count,
        )

    def encode(self) -> str:
        """Encode the version for transport as an opaque string."""
        updated = self.updated_at.isoformat(timespec="microseconds")
        created = self.created_at.isoformat(timespec="microseconds")
        return f"{updated}|{created}|{self.count}"

    @classmethod
    def decode(cls, value: str) -> "KanbanDatasetVersion":
        """Decode and validate a previously emitted version."""
        try:
            updated_value, created_value, count_value = value.split("|")
            return cls.from_values(
                updated_at=datetime.fromisoformat(updated_value),
                created_at=datetime.fromisoformat(created_value),
                count=int(count_value),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid Kanban version") from exc
