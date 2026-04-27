from datetime import date
from typing import Dict, Tuple

from django.db.models import Sum

from apps.job.models.costing import CostLine


def booked_hours_by_staff_date(
    start_date: date,
    end_date: date,
) -> Dict[Tuple[str, date], float]:
    """
    Sum time-CostLine quantities per (staff_id, date) for the inclusive
    [start_date, end_date] range.

    Includes both worked time (regular jobs) and leave (special leave jobs):
    anything booked as kind='time' against an actual CostSet counts as
    capacity already consumed. Estimate/quote CostSets are excluded — they
    are hypothetical, not bookings.

    Keys are (staff_id_str, accounting_date). staff_id is the string form of
    Staff.pk as stored in CostLine.meta['staff_id'].
    """
    rows = (
        CostLine.objects.filter(
            kind="time",
            cost_set__kind="actual",
            accounting_date__gte=start_date,
            accounting_date__lte=end_date,
        )
        .values("accounting_date", "meta__staff_id")
        .annotate(total=Sum("quantity"))
    )

    result: Dict[Tuple[str, date], float] = {}
    for row in rows:
        staff_id = row["meta__staff_id"]
        if staff_id is None:
            continue
        result[(staff_id, row["accounting_date"])] = float(row["total"] or 0.0)
    return result
