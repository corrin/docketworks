"""The wire forms of a date, an instant and a number, for both of Xero's APIs.

Imported by the model and the renderer alike, so it reaches nothing that
reaches the model (transforms.py imports auth, which imports the models).

The two APIs put dates on the wire differently: Accounting sends
``/Date(1518685950940+0000)/`` and a ``<Field>String`` twin, Payroll sends
ISO-8601 in naive UTC.
"""

import re
from datetime import UTC, date, datetime
from decimal import Decimal

type Json = dict[str, Json] | list[Json] | str | int | float | bool | Decimal | None


class WireShapeError(ValueError):
    """A value does not fit the SDK's declared type for its attribute."""


_MS_DATE = re.compile(r"^/Date\((?P<millis>-?\d+)(?P<offset>[+-]\d{4})?\)/$")


def ms_date_now(moment: datetime) -> str:
    """Render one aware instant in the Accounting API form."""
    if moment.tzinfo is None:
        raise WireShapeError("a minted timestamp must be timezone-aware")
    return f"/Date({int(moment.timestamp() * 1000)}+0000)/"


def accounting_datetime(moment: datetime) -> str:
    """Accounting's instant: ``/Date(ms+0000)/``."""
    return ms_date_now(moment)


def accounting_date(day: date) -> str:
    """Accounting's date: midnight UTC in the Microsoft form (recordings/invoice.json)."""
    return ms_date_now(datetime.combine(day, datetime.min.time(), tzinfo=UTC))


def payroll_datetime(moment: datetime) -> str:
    """Payroll's instant: ISO-8601 in naive UTC, whole seconds (recordings/employee.json)."""
    if moment.tzinfo is None:
        raise WireShapeError("a stored timestamp must be timezone-aware")
    return moment.astimezone(UTC).replace(tzinfo=None, microsecond=0).isoformat()


def payroll_date(day: date) -> str:
    """Payroll's date, and Accounting's ``<Date>String`` twin: ``YYYY-MM-DDT00:00:00``."""
    return f"{day.isoformat()}T00:00:00"


def parse_wire_datetime(value: Json, where: str) -> datetime:
    """Read an instant in any form the wire carries it: Microsoft, ISO with or without offset."""
    if not isinstance(value, str) or not value:
        raise WireShapeError(f"{where}: expected a timestamp, got {value!r}")
    matched = _MS_DATE.match(value)
    if matched is not None:
        return datetime.fromtimestamp(int(matched["millis"]) / 1000, tz=UTC)
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z"))
    except ValueError as exc:
        raise WireShapeError(f"{where}: not a timestamp: {value!r}") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_wire_date(value: Json, where: str) -> date:
    """Read a date in any form the wire carries it: Microsoft midnight, ISO date, ISO datetime."""
    if isinstance(value, str) and len(value) == len("YYYY-MM-DD"):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise WireShapeError(f"{where}: not a date: {value!r}") from exc
    return parse_wire_datetime(value, where).date()
