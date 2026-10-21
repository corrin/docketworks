"""Kanban column taxonomy.

Simplified kanban structure: 6 main columns with 1:1 status mapping (no
sub-columns; column = status). `special` badges as Unusual; archived gets its
own fetch path.
"""

from dataclasses import dataclass
from typing import ClassVar, TypedDict

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy


@dataclass
class KanbanColumn:
    """A kanban column — simplified structure without sub-categories."""

    column_id: str
    column_title: Promise
    status_key: str  # Direct 1:1 mapping to job status
    color_theme: str
    badge_color_class: str


class BadgeInfo(TypedDict):
    """Badge display information for a status."""

    label: str
    color_class: str


class KanbanCategorizationService:
    """Centralised kanban categorization logic (column = status, 1:1)."""

    # Define the simplified column structure (column = status)
    COLUMN_STRUCTURE: ClassVar[dict[str, KanbanColumn]] = {
        "draft": KanbanColumn(
            column_id="draft",
            column_title=gettext_lazy("Draft"),
            status_key="draft",
            color_theme="yellow",
            badge_color_class="bg-yellow-500",
        ),
        "awaiting_approval": KanbanColumn(
            column_id="awaiting_approval",
            column_title=gettext_lazy("Awaiting Approval"),
            status_key="awaiting_approval",
            color_theme="orange",
            badge_color_class="bg-orange-500",
        ),
        "approved": KanbanColumn(
            column_id="approved",
            column_title=gettext_lazy("Approved"),
            status_key="approved",
            color_theme="green",
            badge_color_class="bg-green-500",
        ),
        "in_progress": KanbanColumn(
            column_id="in_progress",
            column_title=gettext_lazy("In Progress"),
            status_key="in_progress",
            color_theme="blue",
            badge_color_class="bg-blue-500",
        ),
        "unusual": KanbanColumn(
            column_id="unusual",
            column_title=gettext_lazy("Unusual"),
            status_key="unusual",
            color_theme="purple",
            badge_color_class="bg-purple-500",
        ),
        "recently_completed": KanbanColumn(
            column_id="recently_completed",
            column_title=gettext_lazy("Recently Completed"),
            status_key="recently_completed",
            color_theme="emerald",
            badge_color_class="bg-emerald-500",
        ),
        "archived": KanbanColumn(
            column_id="archived",
            column_title=gettext_lazy("Archived"),
            status_key="archived",
            color_theme="gray",
            badge_color_class="bg-gray-500",
        ),
    }

    # Every Job.JOB_STATUS_CHOICES key, column = status. `special` has no
    # column of its own; it badges as Unusual.
    STATUS_TO_COLUMN_MAP: ClassVar[dict[str, str]] = {
        "draft": "draft",
        "awaiting_approval": "awaiting_approval",
        "approved": "approved",
        "in_progress": "in_progress",
        "unusual": "unusual",
        "special": "unusual",
        "recently_completed": "recently_completed",
        "archived": "archived",
    }

    @classmethod
    def get_column_for_status(cls, status: str) -> str:
        """Return the kanban column id for a job status."""
        return cls.STATUS_TO_COLUMN_MAP[status]

    @classmethod
    def get_column_info_for_status(cls, status: str) -> KanbanColumn:
        """Return the column information for a status."""
        return cls.COLUMN_STRUCTURE[cls.get_column_for_status(status)]

    @classmethod
    def get_all_columns(cls) -> list[KanbanColumn]:
        """Return all kanban columns in display order."""
        return [
            cls.COLUMN_STRUCTURE["draft"],
            cls.COLUMN_STRUCTURE["awaiting_approval"],
            cls.COLUMN_STRUCTURE["approved"],
            cls.COLUMN_STRUCTURE["in_progress"],
            cls.COLUMN_STRUCTURE["unusual"],
            cls.COLUMN_STRUCTURE["recently_completed"],
            cls.COLUMN_STRUCTURE["archived"],
        ]

    @classmethod
    def get_column_by_id(cls, column_id: str) -> KanbanColumn | None:
        """Return a specific column by its id."""
        return cls.COLUMN_STRUCTURE.get(column_id)

    @classmethod
    def get_badge_info(cls, status: str) -> BadgeInfo:
        """Return badge display information (label + colour class) for a status."""
        column_info = cls.get_column_info_for_status(status)
        return {
            "label": str(column_info.column_title),
            "color_class": column_info.badge_color_class,
        }
