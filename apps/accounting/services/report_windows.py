"""The one way a report turns a date range into a datetime window.

Every report parameter is a DATE and every event column is a DATETIME, so each
report has to decide what the end date means. There is only one defensible
answer — the range a user picks is inclusive, so the window must run to the end
of the end day — and getting it wrong is invisible: the report returns rows,
just not the last day's, and the total looks plausible.

It was wrong once already. ``job_movement_service`` had its own ``_midnight``
and applied it to BOTH bounds, so the final day of every range was missing
while the same service reported an inclusive day count; these helpers lived as
private staticmethods on ``SalesPipelineService`` where nothing else could
reach them. One home, so the next report cannot invent a third answer
(ADR 0039).
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

# NZ-local: the business operates here, and every date parameter is interpreted
# as an NZ-local boundary. Not settings.TIME_ZONE via get_current_timezone():
# that follows the request's activated timezone, and a report's window must not
# shift with the caller.
NZ_TZ = ZoneInfo("Pacific/Auckland")


def start_of_local_day(d: date) -> datetime:
    """Return the first instant of ``d``, NZ-local."""
    return datetime.combine(d, time.min, tzinfo=NZ_TZ)


def end_of_local_day(d: date) -> datetime:
    """Return the last instant of ``d``, NZ-local.

    ``time.max``, so a ``__lte`` filter includes the whole day. Midnight here
    would exclude everything the user did on the day they asked for.
    """
    return datetime.combine(d, time.max, tzinfo=NZ_TZ)


def local_day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Return the inclusive NZ-local window covering ``start`` through ``end``."""
    return start_of_local_day(start), end_of_local_day(end)
