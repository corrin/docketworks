"""The accounting reports' single definition of a billable time line.

Billable means the line's meta flag is set AND the job is not the shop
company's — shop work never bills. One home (ADR 0039) because the KPI
calendar and staff-performance reports must agree; the timesheet screens
deliberately use a different definition (no shop exclusion — a cross-domain
divergence ported as-is; unifying them is an owner decision nobody has asked
for).
"""

from uuid import UUID

from apps.job.models.costing import CostLine


def is_billable_line(line: CostLine, shop_company_id: UUID | None) -> bool:
    """Whether this actual time line counts as billable work.

    Every actual time line carries a boolean ``is_billable``: the entry writer
    sets it and the meta schema allows nothing else (0 of 13,709 rows differ,
    2026-11-04). A line without one is a data bug and raises.
    """
    if line.meta["is_billable"] is not True:
        return False
    return line.cost_set.job.company_id != shop_company_id
