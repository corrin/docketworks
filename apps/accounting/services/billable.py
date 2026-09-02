"""The accounting reports' single definition of a billable time line.

Billable means the line's meta flag is set AND the job is not the shop
company's — shop work never bills. One home (ADR 0039) because the KPI
calendar and staff-performance reports must agree; the timesheet screens
deliberately use a different definition (no shop exclusion — recorded
cross-domain divergence in rewrite-history).
"""

from uuid import UUID

from apps.job.models.costing import CostLine


def is_billable_line(line: CostLine, shop_company_id: UUID | None) -> bool:
    """Whether this actual time line counts as billable work.

    v1 compared a KeyTextTransform annotation to the string "true", which
    matched both a JSON boolean true and a JSON string "true"; the direct
    meta read accepts the same two encodings.
    """
    flag: object = line.meta.get("is_billable") if line.meta else None
    if flag is not True and flag != "true":
        return False
    return line.cost_set.job.company_id != shop_company_id
