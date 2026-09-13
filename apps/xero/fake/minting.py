"""What the fake decides for itself when the application writes: ids, numbers, timestamps, totals.

A write's answer is ``defaults ⊕ request ⊕ minted``. The defaults come from
recordings (defaults.py); the request is the application's own payload; this
module is the third part, the values Xero would compute rather than accept.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from apps.xero.fake import defaults
from apps.xero.fake.store import FakeXeroStore, Kind
from apps.xero.fake.wire import Json, ms_date_now

_CENT = Decimal("0.01")
_DATE_FIELDS = ("Date", "DueDate", "ExpiryDate", "DeliveryDate", "ExpectedArrivalDate")


class MintingError(ValueError):
    """The request cannot be turned into a document: a shape Xero would refuse too."""


def now_utc() -> datetime:
    """One clock for everything the fake stamps."""
    return datetime.now(tz=UTC)


def new_id() -> str:
    """Mint an id Xero has never issued and never will: uniqueness is the point."""
    return str(uuid4())


def as_mapping(value: Json, where: str) -> dict[str, Json]:
    """Narrow one JSON value to an object, naming the place if it is not one."""
    if not isinstance(value, dict):
        raise MintingError(f"{where}: expected an object, got {type(value).__name__}")
    return value


def as_list(value: Json, where: str) -> list[Json]:
    """Narrow one JSON value to a list, naming the place if it is not one."""
    if not isinstance(value, list):
        raise MintingError(f"{where}: expected a list, got {type(value).__name__}")
    return value


def text(body: Mapping[str, Json], key: str) -> str | None:
    """Read a string field, None when absent; any other type is a shape the fake refuses."""
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MintingError(f"{key}: expected text, got {type(value).__name__}")
    return value


def money(value: Json, where: str) -> Decimal:
    """Read a number as sent on the wire, as a Decimal."""
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float | str):
        raise MintingError(f"{where}: expected a number, got {type(value).__name__}")
    return Decimal(str(value))


def date_fields(body: dict[str, Json]) -> dict[str, Json]:
    """Xero's two spellings of every date it stores: the Microsoft form and ``<Field>String``.

    The application sends ``"2026-09-09"``; Xero answers with
    ``/Date(1789...+0000)/`` and ``DateString: "2026-09-09T00:00:00"``
    (recordings/invoice.json), and the SDK's ``date[ms-format]`` parser reads
    only the first.
    """
    rendered: dict[str, Json] = {}
    for field in _DATE_FIELDS:
        raw = body.get(field)
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise MintingError(f"{field}: expected an ISO date, got {type(raw).__name__}")
        try:
            day = date.fromisoformat(raw[:10])
        except ValueError as exc:
            raise MintingError(f"{field}: not an ISO date: {raw!r}") from exc
        midnight = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        rendered[field] = ms_date_now(midnight)
        rendered[f"{field}String"] = f"{day.isoformat()}T00:00:00"
    return rendered


def tax_rate_for(store: FakeXeroStore, tax_type: str) -> Decimal:
    """Look up the organisation's effective rate for a TaxType in the seeded tax rates."""
    for row in store.listing(Kind.TAX_RATE):
        if row.body.get("TaxType") == tax_type:
            return money(row.body.get("EffectiveRate"), f"TaxRates[{tax_type}].EffectiveRate")
    raise MintingError(f"the organisation has no tax rate of type {tax_type!r}")


def account_tax_type(store: FakeXeroStore, account_code: str) -> str:
    """Resolve the tax type Xero applies to a line that names an account and no TaxType.

    The application sends AccountCode alone (provider._build_line_items) and
    the recorded invoice comes back with TaxType and TaxAmount filled from the
    account's default; an account code the organisation does not hold is a
    refusal, as it is in Xero.
    """
    for row in store.listing(Kind.ACCOUNT):
        if row.number == account_code:
            tax_type = text(row.body, "TaxType")
            if tax_type is None:
                raise MintingError(f"account {account_code} has no default TaxType")
            return tax_type
    raise MintingError(f"the organisation has no account with code {account_code!r}")


def totalled_lines(
    store: FakeXeroStore, lines: list[Json], line_amount_types: str
) -> tuple[list[Json], dict[str, Json]]:
    """Return the lines as Xero stores them and the document totals they add up to.

    Per-line rounding to the cent, half up, then summed: that is the order
    Xero applies (a document's TotalTax is the sum of its rounded line tax
    amounts, recordings/invoice.json), so a fake that rounded the sum would
    disagree by a cent on exactly the invoices people check by hand.
    """
    exclusive = line_amount_types.upper() == "EXCLUSIVE"
    no_tax = line_amount_types.upper() == "NOTAX"
    stored: list[Json] = []
    sub_total = Decimal(0)
    total_tax = Decimal(0)
    for index, raw in enumerate(lines):
        line = as_mapping(raw, f"LineItems[{index}]")
        quantity = money(line.get("Quantity", 1), f"LineItems[{index}].Quantity")
        unit_amount = money(line.get("UnitAmount", 0), f"LineItems[{index}].UnitAmount")
        line_amount = (quantity * unit_amount).quantize(_CENT, rounding=ROUND_HALF_UP)
        tax_type = text(line, "TaxType")
        if tax_type is None:
            account_code = text(line, "AccountCode")
            if account_code is None:
                raise MintingError(f"LineItems[{index}]: a line names a TaxType or an AccountCode")
            tax_type = account_tax_type(store, account_code)
        rate = Decimal(0) if no_tax else tax_rate_for(store, tax_type)
        if exclusive:
            tax_amount = (line_amount * rate / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
            excl = line_amount
        else:
            tax_amount = (line_amount * rate / (100 + rate)).quantize(_CENT, rounding=ROUND_HALF_UP)
            excl = line_amount - tax_amount
        stored.append(
            {
                **defaults.LINE_ITEM,
                **line,
                "LineItemID": text(line, "LineItemID") or new_id(),
                "TaxType": tax_type,
                "LineAmount": line_amount,
                "TaxAmount": tax_amount,
            }
        )
        sub_total += excl
        total_tax += tax_amount
    return stored, {"SubTotal": sub_total, "TotalTax": total_tax, "Total": sub_total + total_tax}


def embedded_contact(store: FakeXeroStore, request_contact: Json, where: str) -> dict[str, Json]:
    """Embed the contact Xero holds in a document, not the one that was sent.

    A document names its contact by id; Xero answers with the contact's own
    record (recordings/invoice.json carries the full contact under
    ``Contact``), and refuses an id it does not hold.
    """
    sent = as_mapping(request_contact, where)
    contact_id = text(sent, "ContactID")
    if contact_id is None:
        raise MintingError(f"{where}: a document must name its contact by ContactID")
    return dict(store.require(Kind.CONTACT, contact_id).body)
