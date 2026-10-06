"""Where a My time action was made, and whether that is the workshop.

The one decision behind every mark the office sees: an entry's "remote" flag,
a clock time "clocked remotely", and ``trusted`` on every timesheet event.
Coordinates are compared and dropped, never stored.
"""

from math import asin, cos, radians, sin, sqrt
from typing import TypedDict

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults


class EntryLocation(TypedDict):
    """Where the person's phone says it is as it saves."""

    latitude: float
    longitude: float


# Fable: One generous distance and nothing finer. A phone inside a steel shed
# can be a street out, and a wrong mark costs the office a moment's confusion,
# so the circle is drawn to forgive a poor fix rather than to catch a near miss.
WORKSHOP_RADIUS_M = 300
_EARTH_RADIUS_M = 6_371_000


def _metres_between(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    """Great-circle distance between two points, by the haversine formula."""
    d_lat = radians(lat_b - lat_a)
    d_lng = radians(lng_b - lng_a)
    chord = sin(d_lat / 2) ** 2 + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(d_lng / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(sqrt(chord))


def saved_remotely(staff: Staff, location: EntryLocation | None) -> bool:
    """Whether a person's own action lacks a location at the company address: the one trust rule.

    The mark is how the office tells time entered in the workshop from time
    entered somewhere else. A phone that gives no location (refused, or no
    fix) is marked the same as one that is elsewhere. Office staff are not
    marked: they book from desks whose browsers guess their position. A
    company with no address has nowhere to compare against, so marks nothing.
    """
    if staff.is_office_staff:
        return False
    company = CompanyDefaults.get_solo()
    if company.latitude is None or company.longitude is None:
        return False
    if location is None:
        return True
    distance = _metres_between(
        float(company.latitude),
        float(company.longitude),
        location["latitude"],
        location["longitude"],
    )
    return distance > WORKSHOP_RADIUS_M
