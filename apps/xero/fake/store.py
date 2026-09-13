"""Typed access to the fake's one table, scoped to the organisation a call names."""

import re
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.xero.fake.models import FakeXeroObject
from apps.xero.fake.wire import Json

Kind = FakeXeroObject.Kind

_NUMBER = re.compile(r"^(?P<prefix>.*?)(?P<digits>\d+)$")


def _json_numbers(value: Json) -> Json:
    """Store money as JSON numbers, which is what Xero sends and the SDK parses.

    The routes compute in Decimal and the request parser reads in Decimal;
    the column holds JSON, whose one number type is what ``json_response``
    serialises and ``parse_float=Decimal`` reads back to the same value.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_numbers(item) for item in value]
    return value


class FakeXeroNotFoundError(LookupError):
    """No object of that kind and id in this organisation: a 404 on the wire."""


class FakeXeroStore:
    """The objects one organisation holds, and the operations the routes need on them."""

    def __init__(self, tenant_id: str) -> None:  # noqa: D107 -- one argument, named by the class docstring
        self.tenant_id = tenant_id

    def _rows(self, kind: Kind) -> QuerySet[FakeXeroObject]:
        return FakeXeroObject.objects.filter(tenant_id=self.tenant_id, kind=kind)

    def get(self, kind: Kind, object_id: str) -> FakeXeroObject | None:
        """Return the object, or None when the organisation holds no such id."""
        try:
            key = UUID(object_id)
        # deliberate-swallow: Xero answers a malformed id the same way as an unknown one
        except ValueError:
            return None
        return self._rows(kind).filter(id=key).first()

    def require(self, kind: Kind, object_id: str) -> FakeXeroObject:
        """Return the object, or refuse as Xero does for an id it has never issued."""
        found = self.get(kind, object_id)
        if found is None:
            raise FakeXeroNotFoundError(
                f"{kind} {object_id} is not in organisation {self.tenant_id}"
            )
        return found

    def listing(
        self,
        kind: Kind,
        *,
        modified_since: datetime | None = None,
        parent_id: str | None = None,
        exclude_status: Iterable[str] = (),
        name: str | None = None,
    ) -> QuerySet[FakeXeroObject]:
        """Return the rows a listing route pages over, oldest change first.

        Ordered by ``updated_date_utc`` then id: the sync asks Xero for
        ``UpdatedDateUTC ASC`` and advances its cursor to the newest it saw,
        so an unstable order across pages would skip or repeat objects.
        """
        rows = self._rows(kind)
        if modified_since is not None:
            rows = rows.filter(updated_date_utc__gte=modified_since)
        if parent_id is not None:
            rows = rows.filter(parent_id=UUID(parent_id))
        for status in exclude_status:
            rows = rows.exclude(status=status)
        if name is not None:
            rows = rows.filter(name=name)
        return rows.order_by("updated_date_utc", "id")

    def owned_documents(self, contact_id: str) -> QuerySet[FakeXeroObject]:
        """Return the documents standing against a contact; Xero archives none that has any."""
        return (
            FakeXeroObject.objects.filter(
                tenant_id=self.tenant_id,
                kind__in=[Kind.INVOICE, Kind.CREDIT_NOTE, Kind.QUOTE, Kind.PURCHASE_ORDER],
            )
            .filter(Q(body__Contact__ContactID=contact_id))
            .exclude(status="DELETED")
        )

    def save(  # noqa: PLR0913 -- every column, named; the row is the contract
        self,
        kind: Kind,
        object_id: str,
        body: dict[str, Json],
        *,
        updated_date_utc: datetime,
        number: str | None = None,
        name: str | None = None,
        status: str | None = None,
        parent_id: str | None = None,
    ) -> FakeXeroObject:
        """Write the object as Xero now holds it; a second save of an id replaces the first."""
        row, _created = FakeXeroObject.objects.update_or_create(
            id=UUID(object_id),
            defaults={
                "tenant_id": self.tenant_id,
                "kind": kind,
                "number": number,
                "name": name,
                "status": status,
                "parent_id": UUID(parent_id) if parent_id is not None else None,
                "updated_date_utc": updated_date_utc,
                "body": _json_numbers(body),
            },
        )
        return row

    def next_number(self, kind: Kind, xero_default: str) -> str:
        """Return the number Xero would assign next: one past the highest it holds.

        The prefix and the zero-padding come from the organisation's own
        highest number (INV-0016 → INV-0017), which is how Xero's sequence
        behaves; with nothing of the kind numbered yet, ``xero_default`` is
        Xero's own first number for a new organisation, not a choice of ours.
        """
        highest: tuple[int, str, int] | None = None
        for stored in self._rows(kind).exclude(number=None).values_list("number", flat=True):
            if stored is None:
                continue
            match = _NUMBER.match(stored)
            if match is None:
                continue
            digits = match.group("digits")
            candidate = (int(digits), match.group("prefix"), len(digits))
            if highest is None or candidate > highest:
                highest = candidate
        if highest is None:
            return xero_default
        value, prefix, width = highest
        return f"{prefix}{value + 1:0{width}d}"

    def holds_number(self, kind: Kind, number: str, *, status: str) -> bool:
        """Whether a document of that kind, in that status, already carries the number."""
        return self._rows(kind).filter(number=number, status=status).exists()
