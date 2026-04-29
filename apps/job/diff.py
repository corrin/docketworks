"""
CostSet Diff Engine

Compares an existing CostSet with a list of DraftLines and generates diff operations.
Follows clean code principles:
- Single Responsibility Principle
- Early return and guard clauses
- Clear separation of concerns
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from django.utils import timezone

from apps.job.importers.draft import DraftLine
from apps.job.models import CostLine, CostSet


@dataclass
class DiffResult:
    """Result of comparing a CostSet with DraftLines"""

    to_add: List[DraftLine]
    to_update: List[Tuple[CostLine, DraftLine]]
    to_delete: List[CostLine]

    @property
    def has_changes(self) -> bool:
        """Check if there are any changes to apply"""
        return bool(self.to_add or self.to_update or self.to_delete)

    @property
    def summary(self) -> Dict[str, int]:
        """Get summary of changes"""
        return {
            "additions": len(self.to_add),
            "updates": len(self.to_update),
            "deletions": len(self.to_delete),
            "total_changes": len(self.to_add)
            + len(self.to_update)
            + len(self.to_delete),
        }


def diff_costset(old: CostSet, drafts: List[DraftLine]) -> DiffResult:
    """
    Compare an existing CostSet with a list of DraftLine.

    Args:
        old: Existing CostSet to compare against
        drafts: List of DraftLine objects from import/parse

    Returns:
        DiffResult containing:
        - to_add: DraftLines that have no matching CostLine in old
        - to_update: pairs (old_line, draft) where key match but any field differs
        - to_delete: CostLines in old that have no matching draft

    Matching key: (kind, desc, ext_refs matching logic)
    """
    # Early return for empty inputs
    if not drafts:
        return DiffResult(to_add=[], to_update=[], to_delete=list(old.cost_lines.all()))

    # Build mapping of existing cost lines by their unique key
    old_lines_map = _build_cost_line_map(old.cost_lines.all())
    visited_keys: Set[str] = set()

    # Lists to collect diff results
    to_add: List[DraftLine] = []
    to_update: List[Tuple[CostLine, DraftLine]] = []

    # Process each draft line
    for draft in drafts:
        draft_key = _generate_key_for_draft(draft)

        # Check if this draft has a matching cost line
        if draft_key in old_lines_map:
            old_line = old_lines_map[draft_key]
            visited_keys.add(draft_key)

            # Check if any fields differ
            if _lines_differ(old_line, draft):
                to_update.append((old_line, draft))
        else:
            # No matching cost line found - this is a new item
            to_add.append(draft)

    # Find cost lines that weren't visited (need to be deleted)
    to_delete = [
        old_line for key, old_line in old_lines_map.items() if key not in visited_keys
    ]

    return DiffResult(to_add=to_add, to_update=to_update, to_delete=to_delete)


def _build_cost_line_map(cost_lines) -> Dict[str, CostLine]:
    """
    Build a dictionary mapping unique keys to CostLine objects.

    Args:
        cost_lines: QuerySet or iterable of CostLine objects

    Returns:
        Dictionary with keys as unique identifiers and values as CostLine objects
    """
    lines_map = {}

    for line in cost_lines:
        key = _generate_key_for_cost_line(line)
        lines_map[key] = line

    return lines_map


def _generate_key_for_cost_line(cost_line: CostLine) -> str:
    """
    Generate a unique key for a CostLine for matching purposes.

    Key components:
    1. kind (time/material/adjust)
    2. desc (description)
    3. external references (for tracking time entries, material entries, etc.)

    Args:
        cost_line: CostLine object

    Returns:
        String key for matching
    """
    # Base key from kind and description
    base_key = f"{cost_line.kind}:{cost_line.desc}"
    # Add external reference if available
    ext_ref = _extract_external_reference(cost_line.ext_refs, cost_line.kind)
    if ext_ref:
        return f"{base_key}:ext_ref=source_row_{ext_ref}"

    return base_key


def _generate_key_for_draft(draft: DraftLine) -> str:
    """
    Generate a unique key for a DraftLine for matching purposes.

    Args:
        draft: DraftLine object

    Returns:
        String key for matching
    """
    # Base key from kind and description
    base_key = f"{draft.kind}:{draft.desc}"

    # Add source row as external reference for tracking
    if draft.source_row:
        return f"{base_key}:ext_ref=source_row_{draft.source_row}"

    return base_key


def _extract_external_reference(ext_refs: Dict, kind: str) -> Optional[str]:
    """
    Extract the relevant external reference based on the kind of cost line.

    Args:
        ext_refs: Dictionary of external references
        kind: Type of cost line (time/material/adjust)

    Returns:
        External reference string or None
    """
    # Early return for empty ext_refs
    if not ext_refs:
        return None

    # Use match-case for clean flow control
    match kind:
        case "time":
            return ext_refs.get("time_entry_id") or ext_refs.get("source_row")
        case "material":
            return ext_refs.get("material_entry_id") or ext_refs.get("source_row")
        case "adjust":
            return ext_refs.get("adjustment_entry_id") or ext_refs.get("source_row")
        case _:
            # Fallback for unknown kinds
            return ext_refs.get("source_row")


def _lines_differ(cost_line: CostLine, draft: DraftLine) -> bool:
    """
    Check if a CostLine differs from a DraftLine in any significant field.

    Args:
        cost_line: Existing CostLine
        draft: DraftLine to compare against

    Returns:
        True if any fields differ, False if they match
    """
    # Compare quantity with precision tolerance
    if abs(cost_line.quantity - draft.quantity) > Decimal("0.001"):
        return True

    # Compare unit costs with precision tolerance
    if abs(cost_line.unit_cost - draft.unit_cost) > Decimal("0.01"):
        return True

    # Compare unit revenue with precision tolerance
    if abs(cost_line.unit_rev - draft.unit_rev) > Decimal("0.01"):
        return True

    # Compare metadata (if draft has meta data)
    if draft.meta and cost_line.meta != draft.meta:
        return True

    # All fields match
    return False


def apply_diff(cost_set: CostSet, diff_result: DiffResult) -> CostSet:
    """
    Apply the diff result to create a new CostSet with updated data.

    Args:
        cost_set: Original CostSet to base new version on
        diff_result: Result from diff_costset function

    Returns:
        New CostSet with incremented revision and applied changes
    """
    # Early return if no changes
    if not diff_result.has_changes:
        return cost_set

    # Create new CostSet with incremented revision
    new_cost_set = CostSet.objects.create(
        job=cost_set.job,
        kind=cost_set.kind,
        rev=cost_set.rev + 1,
        summary={},  # Will be updated after lines are created
    )

    # Copy existing lines that weren't deleted and apply updates
    _apply_existing_lines(cost_set, new_cost_set, diff_result)

    # Add new lines
    _apply_new_lines(new_cost_set, diff_result.to_add)

    # Update summary
    _update_cost_set_summary(new_cost_set)

    return new_cost_set


def _apply_existing_lines(
    old_cost_set: CostSet, new_cost_set: CostSet, diff_result: DiffResult
) -> None:
    """Apply existing lines with updates to the new cost set"""
    # Build sets for quick lookup
    lines_to_delete = set(diff_result.to_delete)
    lines_to_update = {old_line: draft for old_line, draft in diff_result.to_update}

    for old_line in old_cost_set.cost_lines.all():
        # Skip lines marked for deletion
        if old_line in lines_to_delete:
            continue

        # Check if this line needs updating
        if old_line in lines_to_update:
            draft = lines_to_update[old_line]
            _create_cost_line_from_draft(
                new_cost_set, draft, old_line.ext_refs, old_line.xero_pay_item
            )
        else:
            # Copy line as-is
            _copy_cost_line(old_line, new_cost_set)


def _apply_new_lines(cost_set: CostSet, new_drafts: List[DraftLine]) -> None:
    """Add new lines from drafts to the cost set"""
    for draft in new_drafts:
        _create_cost_line_from_draft(cost_set, draft)


def _create_cost_line_from_draft(
    cost_set: CostSet,
    draft: DraftLine,
    existing_ext_refs: Optional[Dict] = None,
    xero_pay_item=None,
) -> CostLine:
    """
    Create a CostLine from a DraftLine.

    Args:
        cost_set: CostSet to add the line to
        draft: DraftLine to convert
        existing_ext_refs: Existing external references to preserve
        xero_pay_item: XeroPayItem to assign (for time entries)

    Returns:
        Created CostLine object
    """
    # Prepare external references
    ext_refs = existing_ext_refs.copy() if existing_ext_refs else {}

    # Add source information if available
    if draft.source_row:
        ext_refs["source_row"] = str(draft.source_row)
    if draft.source_sheet:
        ext_refs["source_sheet"] = draft.source_sheet

    return CostLine.objects.create(
        cost_set=cost_set,
        kind=draft.kind,
        desc=draft.desc,
        quantity=draft.quantity,
        unit_cost=draft.unit_cost,
        unit_rev=draft.unit_rev,
        accounting_date=timezone.localdate(),
        ext_refs=ext_refs,
        meta=draft.meta,
        xero_pay_item=xero_pay_item,
    )


def _copy_cost_line(old_line: CostLine, new_cost_set: CostSet) -> CostLine:
    """Copy a CostLine to a new CostSet"""
    return CostLine.objects.create(
        cost_set=new_cost_set,
        kind=old_line.kind,
        desc=old_line.desc,
        quantity=old_line.quantity,
        unit_cost=old_line.unit_cost,
        unit_rev=old_line.unit_rev,
        accounting_date=old_line.accounting_date,
        ext_refs=old_line.ext_refs,
        meta=old_line.meta,
        xero_pay_item=old_line.xero_pay_item,
    )


def _update_cost_set_summary(cost_set: CostSet) -> None:
    """Update the cost set summary with aggregated data from its lines"""
    cost_lines = cost_set.cost_lines.all()

    total_cost = sum(line.total_cost for line in cost_lines)
    total_rev = sum(line.total_rev for line in cost_lines)
    total_hours = sum(
        float(line.quantity) for line in cost_lines if line.kind == "time"
    )

    cost_set.summary = {
        "cost": float(total_cost),
        "rev": float(total_rev),
        "hours": total_hours,
    }
    cost_set.save()
