"""Kanban column taxonomy.

Simplified kanban structure: 6 main columns with 1:1 status mapping (no
sub-columns; column = status). Hidden statuses: special, rejected (archived
gets its own fetch path).
"""

from dataclasses import dataclass
from typing import ClassVar, TypedDict


@dataclass
class KanbanColumn:
    """A kanban column — simplified structure without sub-categories."""

    column_id: str
    column_title: str
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
            column_title="Draft",
            status_key="draft",
            color_theme="yellow",
            badge_color_class="bg-yellow-500",
        ),
        "awaiting_approval": KanbanColumn(
            column_id="awaiting_approval",
            column_title="Awaiting Approval",
            status_key="awaiting_approval",
            color_theme="orange",
            badge_color_class="bg-orange-500",
        ),
        "approved": KanbanColumn(
            column_id="approved",
            column_title="Approved",
            status_key="approved",
            color_theme="green",
            badge_color_class="bg-green-500",
        ),
        "in_progress": KanbanColumn(
            column_id="in_progress",
            column_title="In Progress",
            status_key="in_progress",
            color_theme="blue",
            badge_color_class="bg-blue-500",
        ),
        "unusual": KanbanColumn(
            column_id="unusual",
            column_title="Unusual",
            status_key="unusual",
            color_theme="purple",
            badge_color_class="bg-purple-500",
        ),
        "recently_completed": KanbanColumn(
            column_id="recently_completed",
            column_title="Recently Completed",
            status_key="recently_completed",
            color_theme="emerald",
            badge_color_class="bg-emerald-500",
        ),
        "archived": KanbanColumn(
            column_id="archived",
            column_title="Archived",
            status_key="archived",
            color_theme="gray",
            badge_color_class="bg-gray-500",
        ),
    }

    # Status to column mapping for quick lookup - simplified 1:1 mapping
    STATUS_TO_COLUMN_MAP: ClassVar[dict[str, str]] = {
        # New status structure - 1:1 mapping (column = status)
        "draft": "draft",
        "awaiting_approval": "awaiting_approval",
        "approved": "approved",
        "in_progress": "in_progress",
        "unusual": "unusual",
        "recently_completed": "recently_completed",
        "archived": "archived",
        # Legacy status mappings kept from v1 (pre-migration rows)
        "quoting": "awaiting_approval",
        "accepted_quote": "approved",
        "awaiting_materials": "in_progress",
        "awaiting_staff": "in_progress",
        "awaiting_site_availability": "in_progress",
        "on_hold": "unusual",
        "completed": "recently_completed",
        # Hidden statuses (not shown on kanban): special, rejected
    }

    @classmethod
    def get_column_for_status(cls, status: str) -> str:
        """Return the kanban column id for a job status."""
        return cls.STATUS_TO_COLUMN_MAP.get(status, "draft")

    @classmethod
    def get_column_info_for_status(cls, status: str) -> KanbanColumn | None:
        """Return the column information for a status, if mapped."""
        column_id = cls.get_column_for_status(status)
        return cls.COLUMN_STRUCTURE.get(column_id)

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

        if column_info:
            return {
                "label": column_info.column_title,
                "color_class": column_info.badge_color_class,
            }

        # Fallback for unknown statuses
        return {"label": status.replace("_", " ").title(), "color_class": "bg-gray-400"}

    @classmethod
    def is_status_hidden_from_kanban(cls, status: str) -> bool:
        """Report whether a status is hidden from kanban display."""
        hidden_statuses = {"special", "rejected"}
        return status in hidden_statuses
