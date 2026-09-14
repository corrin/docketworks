"""The fake Xero's organisation: one table per Xero resource (ADR 0060).

A row is the resource as Xero holds it. Every field Xero filters, orders or
keys on is a typed, indexed column, so the query language (query.py) is ORM
filters and never parses a blob; every other field Xero echoes lives in
``attributes``, which nothing queries. ``id`` IS the Xero id: the uniqueness
Xero guarantees is a primary key or a constraint here, not a convention the
handlers remember to keep. Xero's own uniqueness rules are constraints too —
a number per document kind, a name per active contact, a tax type per
organisation, one draft pay run per calendar.

Relational rather than an in-process store because the E2E stack is five
processes (uvicorn, worker, beat, the cleanup command, the PDF inspector)
that all have to agree on what "Xero" holds, and because the restore that
ends every run has to put it back.

``WIRE`` on each model maps a wire key to its column; ``from_wire`` splits a
wire body into columns and attributes and ``to_wire`` joins them back, so a
recording round-trips exactly and a handler computes on typed values.
"""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID, uuid4

from django.db import models

from apps.xero.fake.dates import (
    Json,
    WireShapeError,
    accounting_date,
    accounting_datetime,
    parse_wire_date,
    parse_wire_datetime,
    payroll_date,
    payroll_datetime,
)

ACCOUNTING = "accounting"
PAYROLL = "payrollnz"


def _text(value: Json, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WireShapeError(f"{where}: expected text, got {type(value).__name__}")
    # Xero sends "" where it holds nothing; the column holds NULL (ADR 0040)
    # and renders as an absent key, which the SDK reads the same way.
    return value or None


def _number(value: Json, where: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float | str):
        raise WireShapeError(f"{where}: expected a number, got {type(value).__name__}")
    return Decimal(str(value))


def _integer(value: Json, where: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise WireShapeError(f"{where}: expected an integer, got {type(value).__name__}")
    return value


def _flag(value: Json, where: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise WireShapeError(f"{where}: expected a bool, got {type(value).__name__}")
    return value


def _uuid(value: Json, where: str) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WireShapeError(f"{where}: expected an id, got {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as exc:
        raise WireShapeError(f"{where}: not a UUID: {value!r}") from exc


#: The parser for each column type, most specific first (a DateTimeField is a DateField).
_PARSERS: "tuple[tuple[type[models.Field[object, object]], Callable[[Json, str], object]], ...]" = (
    (models.DateTimeField, parse_wire_datetime),
    (models.DateField, parse_wire_date),
    (models.DecimalField, _number),
    (models.BooleanField, _flag),
    (models.IntegerField, _integer),
    (models.UUIDField, _uuid),
    (models.CharField, _text),
    (models.TextField, _text),
)


class WireJSONEncoder(json.JSONEncoder):
    """Store the wire's numbers as JSON numbers.

    The SDK parses the wire with ``parse_float=Decimal`` and a recording is
    read the same way, so an attribute reaches here as a Decimal; JSON has
    one number type, and ``Decimal("725.09")`` and ``725.09`` parse back to
    the same value under the SDK's reader.
    """

    def default(self, o: object) -> float:
        """Render a Decimal as the number it was on the wire."""
        if isinstance(o, Decimal):
            return float(o)
        raise TypeError(f"{type(o).__name__} is not JSON serialisable")


class WireRow(models.Model):
    """Columns declared by ``WIRE``, everything else in ``attributes``."""

    #: Which API's wire forms this resource uses (dates, nulls).
    API: ClassVar[str]
    #: The wire key of the row's id; None for a resource Xero does not key.
    ID_KEY: ClassVar[str | None] = None
    #: Wire key → column, for every typed column.
    WIRE: ClassVar[Mapping[str, str]] = {}
    #: Wire keys a relation carries (an embedded contact, the lines): read by
    #: ``link``, never kept in ``attributes``.
    RELATION_KEYS: ClassVar[tuple[str, ...]] = ()

    # No default: the fake mints every id it issues and the seed copies every
    # id the mirror holds, so a row reaching the database without one is a
    # bug to crash on, not a gap to fill.
    id = models.UUIDField(primary_key=True, editable=False)
    attributes = models.JSONField(encoder=WireJSONEncoder)

    class Meta:
        abstract = True

    # ---- wire → columns -------------------------------------------------------

    @classmethod
    def split_wire(cls, body: Mapping[str, Json]) -> tuple[dict[str, object], dict[str, Json]]:
        """Return the typed columns a body carries and what remains for ``attributes``."""
        columns: dict[str, object] = {}
        rest: dict[str, Json] = {}
        for key, value in body.items():
            column = cls.WIRE.get(key)
            if column is None:
                if key == cls.ID_KEY or key in cls.RELATION_KEYS or cls._is_derived(key):
                    continue
                rest[key] = value
                continue
            columns[column] = cls._parse(column, value, f"{cls.__name__}.{key}")
        return columns, rest

    @classmethod
    def _is_derived(cls, key: str) -> bool:
        """Recognise a key rendered from a column, never stored: the ``<Date>String`` twins."""
        return (
            cls.API == ACCOUNTING
            and key.endswith("String")
            and cls.WIRE.get(key.removesuffix("String")) is not None
        )

    @classmethod
    def _parse(cls, column: str, value: Json, where: str) -> object:
        field = cls._meta.get_field(column)
        for field_type, parser in _PARSERS:
            if isinstance(field, field_type):
                return None if value is None else parser(value, where)
        raise WireShapeError(f"{where}: no wire parser for {type(field).__name__}")

    # ---- columns → wire -------------------------------------------------------

    def to_wire(self) -> dict[str, Json]:
        """Render the row as Xero puts it on the wire: attributes, then the columns over them."""
        wire: dict[str, Json] = dict(self.attributes)
        if self.ID_KEY is not None:
            wire[self.ID_KEY] = str(self.id)
        for key, column in self.WIRE.items():
            self._render(wire, key, column)
        return wire

    def _render(self, wire: dict[str, Json], key: str, column: str) -> None:
        value = getattr(self, column)
        field = self._meta.get_field(column)
        if value is None:
            # Accounting omits a field it has no value for; Payroll sends an
            # explicit null (recordings/employee.json).
            if self.API == PAYROLL:
                wire[key] = None
            else:
                wire.pop(key, None)
                if isinstance(field, models.DateField):
                    wire.pop(f"{key}String", None)
            return
        if isinstance(field, models.DateTimeField):
            wire[key] = (
                accounting_datetime(value) if self.API == ACCOUNTING else payroll_datetime(value)
            )
        elif isinstance(field, models.DateField):
            if self.API == ACCOUNTING:
                wire[key] = accounting_date(value)
                wire[f"{key}String"] = payroll_date(value)
            else:
                wire[key] = payroll_date(value)
        elif isinstance(field, models.UUIDField):
            wire[key] = str(value)
        else:
            wire[key] = value


class XeroRecord(WireRow):
    """A resource one organisation holds, in the order Xero lists it."""

    #: The wire key of the change stamp; None where Xero sends none.
    UPDATED_KEY: ClassVar[str | None] = None

    tenant_id = models.CharField(max_length=255)
    # Every listing pages in this order: the sync asks for UpdatedDateUTC ASC
    # and advances its cursor to the newest it saw, so an unstable order
    # across pages would skip or repeat objects.
    updated_date_utc = models.DateTimeField()

    class Meta:
        abstract = True
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["tenant_id", "updated_date_utc"], name="%(class)s_tenant_upd"),
        ]

    def __str__(self) -> str:
        return f"{type(self).__name__} {self.id}"

    @classmethod
    def for_tenant(cls, tenant_id: str) -> models.QuerySet[Self]:
        """Return the rows one organisation holds, in Xero's listing order."""
        return cls._default_manager.filter(tenant_id=tenant_id).order_by("updated_date_utc", "id")

    @classmethod
    def held(cls, tenant_id: str, object_id: str) -> Self | None:
        """Return the row, or None when the organisation holds no such id."""
        try:
            key = UUID(object_id)
        # deliberate-swallow: Xero answers a malformed id the same way as an unknown one
        except ValueError:
            return None
        return cls._default_manager.filter(tenant_id=tenant_id, id=key).first()

    @classmethod
    def from_wire(
        cls,
        tenant_id: str,
        body: Mapping[str, Json],
        *,
        updated_date_utc: datetime | None = None,
        **relations: object,
    ) -> Self:
        """Write the resource as Xero now holds it; a second write of an id replaces the first.

        The stamp is ``updated_date_utc`` when given (a write the fake is
        making now), else the body's own ``UPDATED_KEY`` (a mirror row, a
        recording), else now.
        """
        if cls.ID_KEY is None:
            raise WireShapeError(f"{cls.__name__} has no id on the wire; write it with its id")
        row_id = _uuid(body.get(cls.ID_KEY), f"{cls.__name__}.{cls.ID_KEY}")
        if row_id is None:
            raise WireShapeError(f"{cls.__name__}: a body must carry its {cls.ID_KEY}")
        return cls.write(tenant_id, row_id, body, updated_date_utc=updated_date_utc, **relations)

    @classmethod
    def write(
        cls,
        tenant_id: str,
        row_id: UUID,
        body: Mapping[str, Json],
        *,
        updated_date_utc: datetime | None = None,
        **relations: object,
    ) -> Self:
        """Write the resource under a known id (see ``from_wire``); ``relations`` are its owners."""
        columns, attributes = cls.split_wire(body)
        recorded = attributes.pop(cls.UPDATED_KEY, None) if cls.UPDATED_KEY is not None else None
        stamp = updated_date_utc
        if stamp is None and recorded is not None:
            stamp = parse_wire_datetime(recorded, cls.UPDATED_KEY or "")
        if stamp is None:
            stamp = datetime.now(tz=UTC)
        row, _created = cls._default_manager.update_or_create(
            id=row_id,
            defaults={
                "tenant_id": tenant_id,
                "updated_date_utc": stamp,
                "attributes": attributes,
                **columns,
                **relations,
            },
        )
        row.link(body)
        return row

    def link(self, body: Mapping[str, Json]) -> None:
        """Read a resource's relations off the body once the row exists; nothing, by default."""
        del body

    def to_wire(self) -> dict[str, Json]:
        """Render the row with its change stamp in the API's form."""
        wire = super().to_wire()
        if self.UPDATED_KEY is not None:
            wire[self.UPDATED_KEY] = (
                accounting_datetime(self.updated_date_utc)
                if self.API == ACCOUNTING
                else payroll_datetime(self.updated_date_utc)
            )
        return wire


class AccountingRecord(XeroRecord):
    """A resource of the Accounting API: Microsoft dates, absent keys for nulls."""

    API = ACCOUNTING
    UPDATED_KEY: ClassVar[str | None] = "UpdatedDateUTC"

    class Meta(XeroRecord.Meta):
        abstract = True


class PayrollRecord(XeroRecord):
    """A resource of the Payroll NZ API: ISO dates, explicit nulls."""

    API = PAYROLL
    UPDATED_KEY: ClassVar[str | None] = "updatedDateUTC"

    class Meta(XeroRecord.Meta):
        abstract = True


# ---- Accounting --------------------------------------------------------------


class FakeOrganisation(AccountingRecord):
    """GET /Organisation (recordings/organisation.json); one per tenant."""

    ID_KEY = "OrganisationID"
    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {
        "Name": "name",
        "ShortCode": "short_code",
        "BaseCurrency": "base_currency",
        "OrganisationStatus": "status",
    }

    name = models.CharField(max_length=500)
    short_code = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- unset is NULL (ADR 0040)
    base_currency = models.CharField(max_length=3)
    status = models.CharField(max_length=50)

    class Meta(AccountingRecord.Meta):
        db_table = "xero_fake_organisation"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["tenant_id"], name="organisation_one_per_tenant"),
        ]


class FakeContact(AccountingRecord):
    """A contact (recordings/contact.json).

    No uniqueness on the name: the Demo Company's mirror holds an invoice
    whose embedded contact shares its name with another contact, so Xero
    has held two of one name, and a refusal on creating a second is a
    behaviour to record and answer, not a constraint to seed under.
    """

    ID_KEY = "ContactID"
    WIRE: ClassVar[Mapping[str, str]] = {
        "Name": "name",
        "ContactStatus": "status",
        "FirstName": "first_name",
        "LastName": "last_name",
        "EmailAddress": "email_address",
        "AccountNumber": "account_number",
        "IsCustomer": "is_customer",
        "IsSupplier": "is_supplier",
    }

    name = models.CharField(max_length=500)
    status = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- as is_customer
    first_name = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    last_name = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    email_address = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    account_number = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    # Nullable: a document embeds its contact by id, name and email alone
    # (recordings/quote.json), and that is all a seed may hold of one.
    is_customer = models.BooleanField(null=True, blank=True)
    is_supplier = models.BooleanField(null=True, blank=True)

    class Meta(AccountingRecord.Meta):
        db_table = "xero_fake_contact"
        indexes: ClassVar[list[models.Index]] = [
            *AccountingRecord.Meta.indexes,
            models.Index(fields=["tenant_id", "name"], name="contact_tenant_name"),
            models.Index(fields=["tenant_id", "status"], name="contact_tenant_status"),
        ]


class FakeAccount(AccountingRecord):
    """GET /Accounts (recordings/accounts.json); a line's tax defaults to its account's."""

    ID_KEY = "AccountID"
    WIRE: ClassVar[Mapping[str, str]] = {
        "Code": "code",
        "Name": "name",
        "Status": "status",
        "Type": "type",
        "TaxType": "tax_type",
        "Class": "account_class",
    }

    code = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- some system accounts carry none
    name = models.CharField(max_length=500)
    status = models.CharField(max_length=50)
    type = models.CharField(max_length=50)
    tax_type = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    account_class = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040

    class Meta(AccountingRecord.Meta):
        db_table = "xero_fake_account"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # Xero lets an archived and a live account share one code.
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                condition=models.Q(status="ACTIVE", code__isnull=False),
                name="account_code_unique_while_active",
            ),
        ]


class FakeTaxRate(AccountingRecord):
    """GET /TaxRates (recordings/tax_rates.json); keyed by TaxType, no id on the wire."""

    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {
        "Name": "name",
        "TaxType": "tax_type",
        "Status": "status",
        "EffectiveRate": "effective_rate",
    }

    name = models.CharField(max_length=500)
    tax_type = models.CharField(max_length=50)
    status = models.CharField(max_length=50)
    effective_rate = models.DecimalField(max_digits=9, decimal_places=4)

    class Meta(AccountingRecord.Meta):
        db_table = "xero_fake_taxrate"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["tenant_id", "tax_type"], name="taxrate_type_unique"),
        ]


class FakeBrandingTheme(AccountingRecord):
    """GET /BrandingThemes (recordings/branding_themes.json)."""

    ID_KEY = "BrandingThemeID"
    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {"Name": "name", "Type": "type", "SortOrder": "sort_order"}

    name = models.CharField(max_length=500)
    type = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    sort_order = models.IntegerField(null=True, blank=True)

    class Meta(AccountingRecord.Meta):
        db_table = "xero_fake_brandingtheme"


class FakeItem(AccountingRecord):
    """GET/POST /Items (recordings/items.json); Xero keys an item by its Code."""

    ID_KEY = "ItemID"
    WIRE: ClassVar[Mapping[str, str]] = {
        "Code": "code",
        "Name": "name",
        "IsSold": "is_sold",
        "IsPurchased": "is_purchased",
        "IsTrackedAsInventory": "is_tracked_as_inventory",
    }

    code = models.CharField(max_length=255)
    name = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    is_sold = models.BooleanField(null=True, blank=True)
    is_purchased = models.BooleanField(null=True, blank=True)
    is_tracked_as_inventory = models.BooleanField(null=True, blank=True)

    class Meta(AccountingRecord.Meta):
        db_table = "xero_fake_item"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["tenant_id", "code"], name="item_code_unique"),
        ]


_DOCUMENT_WIRE: Mapping[str, str] = {
    "Status": "status",
    "Date": "date",
    "Reference": "reference",
    "CurrencyCode": "currency_code",
    "BrandingThemeID": "branding_theme_id",
    "LineAmountTypes": "line_amount_types",
    "SubTotal": "sub_total",
    "TotalTax": "total_tax",
    "Total": "total",
}


class Document(AccountingRecord):
    """What an invoice, credit note, quote and purchase order share: a contact, lines, totals."""

    #: The wire key of the document's number.
    NUMBER_KEY: ClassVar[str]
    #: Xero's first number for a new organisation, which the sequence continues from.
    FIRST_NUMBER: ClassVar[str]
    #: The listing resource, as in the URL and the envelope key.
    RESOURCE: ClassVar[str]
    RELATION_KEYS: ClassVar[tuple[str, ...]] = ("Contact", "LineItems")

    contact = models.ForeignKey(
        FakeContact, on_delete=models.PROTECT, related_name="%(class)ss", null=True, blank=True
    )
    number = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    status = models.CharField(max_length=50)
    date = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=4000, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    currency_code = models.CharField(max_length=3, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    branding_theme_id = models.UUIDField(null=True, blank=True)
    line_amount_types = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    sub_total = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    total_tax = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    total = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    class Meta(AccountingRecord.Meta):
        abstract = True
        indexes: ClassVar[list[models.Index]] = [
            *AccountingRecord.Meta.indexes,
            models.Index(fields=["tenant_id", "number"], name="%(class)s_tenant_num"),
            models.Index(fields=["tenant_id", "status"], name="%(class)s_tenant_stat"),
        ]

    def __str__(self) -> str:
        return f"{type(self).__name__} {self.number or self.id}"

    def link(self, body: Mapping[str, Json]) -> None:
        """Bind the contact Xero embeds and replace the lines with the ones sent."""
        embedded = body.get("Contact")
        if embedded is not None:
            if not isinstance(embedded, Mapping):
                raise WireShapeError(f"{self.RESOURCE}[].Contact: expected an object")
            self.contact = self._contact_of(embedded)
            self.save(update_fields=["contact"])
        lines = body.get("LineItems")
        if lines is not None:
            if not isinstance(lines, list):
                raise WireShapeError(f"{self.RESOURCE}[].LineItems: expected a list")
            self.lines.all().delete()
            for position, line in enumerate(lines):
                if not isinstance(line, Mapping):
                    raise WireShapeError(f"{self.RESOURCE}[].LineItems[{position}]: not an object")
                self.lines.model.from_wire(self, position, line)

    def _contact_of(self, embedded: Mapping[str, Json]) -> FakeContact:
        """Return the contact a document names, which the organisation must already hold."""
        contact_id = _uuid(embedded.get("ContactID"), f"{self.RESOURCE}[].Contact.ContactID")
        if contact_id is None:
            raise WireShapeError(f"{self.RESOURCE}[].Contact: a document names its contact by id")
        held = FakeContact.objects.filter(tenant_id=self.tenant_id, id=contact_id).first()
        if held is None:
            raise FakeContact.DoesNotExist(
                f"{self.RESOURCE}[].Contact: {self.tenant_id} holds no contact {contact_id}"
            )
        return held

    def to_wire(self) -> dict[str, Json]:
        """Render the document with the contact Xero embeds and its lines in order."""
        wire = super().to_wire()
        if self.contact is not None:
            wire["Contact"] = self.contact.to_wire()
        wire["LineItems"] = [line.to_wire() for line in self.lines.order_by("position")]
        return wire

    @property
    def lines(self) -> models.QuerySet["DocumentLine"]:
        """The document's lines; each concrete document names its own line table."""
        raise NotImplementedError


class FakeInvoice(Document):
    """An invoice or bill (recordings/invoice.json, bills_page.json), by Type."""

    ID_KEY = "InvoiceID"
    NUMBER_KEY = "InvoiceNumber"
    FIRST_NUMBER = "INV-0001"
    RESOURCE = "Invoices"
    WIRE: ClassVar[Mapping[str, str]] = {
        **_DOCUMENT_WIRE,
        "InvoiceNumber": "number",
        "Type": "type",
        "DueDate": "due_date",
        "AmountDue": "amount_due",
        "AmountPaid": "amount_paid",
        "AmountCredited": "amount_credited",
        "FullyPaidOnDate": "fully_paid_on_date",
    }

    type = models.CharField(max_length=50)
    due_date = models.DateField(null=True, blank=True)
    amount_due = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    amount_paid = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    amount_credited = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    fully_paid_on_date = models.DateField(null=True, blank=True)

    class Meta(Document.Meta):
        db_table = "xero_fake_invoice"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # An ACCREC number is unique; a bill carries the supplier's own
            # number, which two suppliers may share.
            models.UniqueConstraint(
                fields=["tenant_id", "number"],
                condition=models.Q(type="ACCREC", number__isnull=False),
                name="invoice_number_unique_per_tenant",
            ),
        ]

    @property
    def lines(self) -> models.QuerySet["FakeInvoiceLine"]:
        """The invoice's lines."""
        return self.invoice_lines.all()


class FakeCreditNote(Document):
    """GET /CreditNotes (recordings/credit_notes_page.json)."""

    ID_KEY = "CreditNoteID"
    NUMBER_KEY = "CreditNoteNumber"
    FIRST_NUMBER = "CN-0001"
    RESOURCE = "CreditNotes"
    WIRE: ClassVar[Mapping[str, str]] = {
        **_DOCUMENT_WIRE,
        "CreditNoteNumber": "number",
        "Type": "type",
        "RemainingCredit": "remaining_credit",
    }

    type = models.CharField(max_length=50)
    remaining_credit = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    class Meta(Document.Meta):
        db_table = "xero_fake_creditnote"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["tenant_id", "number"],
                condition=models.Q(type="ACCRECCREDIT", number__isnull=False),
                name="creditnote_number_unique_per_tenant",
            ),
        ]

    @property
    def lines(self) -> models.QuerySet["FakeCreditNoteLine"]:
        """The creditnote's lines."""
        return self.creditnote_lines.all()


class FakeQuote(Document):
    """GET/PUT/POST /Quotes (recordings/quote.json)."""

    ID_KEY = "QuoteID"
    NUMBER_KEY = "QuoteNumber"
    FIRST_NUMBER = "QU-0001"
    RESOURCE = "Quotes"
    WIRE: ClassVar[Mapping[str, str]] = {
        **_DOCUMENT_WIRE,
        "QuoteNumber": "number",
        "ExpiryDate": "expiry_date",
    }

    expiry_date = models.DateField(null=True, blank=True)

    class Meta(Document.Meta):
        db_table = "xero_fake_quote"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["tenant_id", "number"],
                condition=models.Q(number__isnull=False),
                name="quote_number_unique_per_tenant",
            ),
        ]

    @property
    def lines(self) -> models.QuerySet["FakeQuoteLine"]:
        """The quote's lines."""
        return self.quote_lines.all()


class FakePurchaseOrder(Document):
    """GET/POST /PurchaseOrders (recordings/purchase_order.json); a DELETED one keeps its number."""

    ID_KEY = "PurchaseOrderID"
    NUMBER_KEY = "PurchaseOrderNumber"
    FIRST_NUMBER = "PO-0001"
    RESOURCE = "PurchaseOrders"
    WIRE: ClassVar[Mapping[str, str]] = {
        **_DOCUMENT_WIRE,
        "PurchaseOrderNumber": "number",
        "Type": "type",
        "DeliveryDate": "delivery_date",
    }

    type = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    delivery_date = models.DateField(null=True, blank=True)

    class Meta(Document.Meta):
        db_table = "xero_fake_purchaseorder"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["tenant_id", "number"],
                condition=models.Q(number__isnull=False),
                name="purchaseorder_number_unique_per_tenant",
            ),
        ]

    @property
    def lines(self) -> models.QuerySet["FakePurchaseOrderLine"]:
        """The purchaseorder's lines."""
        return self.purchaseorder_lines.all()


class DocumentLine(WireRow):
    """One line of a document, in the order it was sent; totals are computed from these."""

    API = ACCOUNTING
    ID_KEY = "LineItemID"
    WIRE: ClassVar[Mapping[str, str]] = {
        "Description": "description",
        "Quantity": "quantity",
        "UnitAmount": "unit_amount",
        "AccountCode": "account_code",
        "TaxType": "tax_type",
        "TaxAmount": "tax_amount",
        "LineAmount": "line_amount",
        "ItemCode": "item_code",
    }

    position = models.IntegerField()
    description = models.TextField(null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    quantity = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    unit_amount = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    account_code = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    tax_type = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    tax_amount = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    line_amount = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    item_code = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 -- ADR 0040

    class Meta:
        abstract = True
        ordering: ClassVar[list[str]] = ["position"]

    def __str__(self) -> str:
        return f"{type(self).__name__} {self.id}"

    @classmethod
    def from_wire(cls, document: Document, position: int, body: Mapping[str, Json]) -> Self:
        """Write one line of a document as Xero holds it."""
        line_id = _uuid(body.get(cls.ID_KEY), f"LineItems[{position}].LineItemID")
        if line_id is None:
            # Xero mints a line's id on the first write and keeps it after.
            line_id = uuid4()
        columns, attributes = cls.split_wire(body)
        return cls._default_manager.create(
            id=line_id, document=document, position=position, attributes=attributes, **columns
        )


class FakeInvoiceLine(DocumentLine):
    """One line of an invoice."""

    document = models.ForeignKey(
        FakeInvoice, on_delete=models.CASCADE, related_name="invoice_lines"
    )

    class Meta(DocumentLine.Meta):
        db_table = "xero_fake_invoiceline"


class FakeCreditNoteLine(DocumentLine):
    """One line of a creditnote."""

    document = models.ForeignKey(
        FakeCreditNote, on_delete=models.CASCADE, related_name="creditnote_lines"
    )

    class Meta(DocumentLine.Meta):
        db_table = "xero_fake_creditnoteline"


class FakeQuoteLine(DocumentLine):
    """One line of a quote."""

    document = models.ForeignKey(FakeQuote, on_delete=models.CASCADE, related_name="quote_lines")

    class Meta(DocumentLine.Meta):
        db_table = "xero_fake_quoteline"


class FakePurchaseOrderLine(DocumentLine):
    """One line of a purchaseorder."""

    document = models.ForeignKey(
        FakePurchaseOrder, on_delete=models.CASCADE, related_name="purchaseorder_lines"
    )

    class Meta(DocumentLine.Meta):
        db_table = "xero_fake_purchaseorderline"


class FakeHistoryRecord(AccountingRecord):
    """PUT/GET /{resource}/{id}/History (recordings/invoice_history.json); no id on the wire."""

    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {
        "Changes": "changes",
        "DateUTC": "date_utc",
        "User": "user",
        "Details": "details",
    }

    # The document a note is against, by the resource in its URL; a note can
    # stand against any document kind, so this is a key into whichever table.
    resource = models.CharField(max_length=50)
    document_id = models.UUIDField()
    changes = models.CharField(max_length=255)
    date_utc = models.DateTimeField()
    user = models.CharField(max_length=255)
    details = models.CharField(max_length=4000, null=True, blank=True)  # noqa: DJ001 -- ADR 0040

    class Meta(AccountingRecord.Meta):
        db_table = "xero_fake_historyrecord"
        indexes: ClassVar[list[models.Index]] = [
            *AccountingRecord.Meta.indexes,
            models.Index(fields=["tenant_id", "resource", "document_id"], name="history_document"),
        ]


class FakeAttachment(AccountingRecord):
    """PUT /{resource}/{id}/Attachments/{name}: the bytes are kept by size only."""

    ID_KEY = "AttachmentID"
    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {
        "FileName": "file_name",
        "MimeType": "mime_type",
        "ContentLength": "content_length",
        "IncludeOnline": "include_online",
        "Url": "url",
    }

    resource = models.CharField(max_length=50)
    document_id = models.UUIDField()
    file_name = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=255)
    content_length = models.IntegerField()
    include_online = models.BooleanField()
    url = models.CharField(max_length=5000)

    class Meta(AccountingRecord.Meta):
        db_table = "xero_fake_attachment"
        indexes: ClassVar[list[models.Index]] = [
            *AccountingRecord.Meta.indexes,
            models.Index(
                fields=["tenant_id", "resource", "document_id"], name="attachment_document"
            ),
        ]


# ---- Payroll NZ -----------------------------------------------------------------


class FakePayRunCalendar(PayrollRecord):
    """GET /PayRunCalendars (recordings/pay_run_calendars.json)."""

    ID_KEY = "payrollCalendarID"
    WIRE: ClassVar[Mapping[str, str]] = {
        "name": "name",
        "calendarType": "calendar_type",
        "periodStartDate": "period_start_date",
        "periodEndDate": "period_end_date",
        "paymentDate": "payment_date",
    }

    name = models.CharField(max_length=255)
    calendar_type = models.CharField(max_length=50)
    period_start_date = models.DateField()
    period_end_date = models.DateField()
    payment_date = models.DateField()

    class Meta(PayrollRecord.Meta):
        db_table = "xero_fake_payruncalendar"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"], name="payruncalendar_name_unique"
            ),
        ]


class FakeEmployee(PayrollRecord):
    """GET /Employees, /Employees/{id} (recordings/employee.json)."""

    ID_KEY = "employeeID"
    WIRE: ClassVar[Mapping[str, str]] = {
        "firstName": "first_name",
        "lastName": "last_name",
        "email": "email",
        "dateOfBirth": "date_of_birth",
        "startDate": "start_date",
        "endDate": "end_date",
        "payrollCalendarID": "payroll_calendar_id",
        "jobTitle": "job_title",
        "employmentType": "employment_type",
        "createdDateUTC": "created_date_utc",
    }

    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    email = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    date_of_birth = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    payroll_calendar_id = models.UUIDField(null=True, blank=True)
    job_title = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    employment_type = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    created_date_utc = models.DateTimeField(null=True, blank=True)

    class Meta(PayrollRecord.Meta):
        db_table = "xero_fake_employee"
        indexes: ClassVar[list[models.Index]] = [
            *PayrollRecord.Meta.indexes,
            models.Index(fields=["tenant_id", "email"], name="employee_tenant_email"),
        ]


class FakeSalaryAndWage(PayrollRecord):
    """GET /Employees/{id}/SalaryAndWages (recordings/salary_and_wages.json)."""

    ID_KEY = "salaryAndWagesID"
    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {
        "earningsRateID": "earnings_rate_id",
        "effectiveFrom": "effective_from",
        "status": "status",
        "paymentType": "payment_type",
        "ratePerUnit": "rate_per_unit",
        "annualSalary": "annual_salary",
        "numberOfUnitsPerWeek": "units_per_week",
        "numberOfUnitsPerDay": "units_per_day",
        "daysPerWeek": "days_per_week",
    }

    employee = models.ForeignKey(FakeEmployee, on_delete=models.CASCADE, related_name="salaries")
    earnings_rate_id = models.UUIDField()
    effective_from = models.DateField()
    status = models.CharField(max_length=50)
    payment_type = models.CharField(max_length=50)
    rate_per_unit = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    annual_salary = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    units_per_week = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    units_per_day = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    days_per_week = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    class Meta(PayrollRecord.Meta):
        db_table = "xero_fake_salaryandwage"


class FakeWorkingPattern(PayrollRecord):
    """GET /Employees/{id}/Working-Patterns[/{pattern}] (recordings/working_pattern.json)."""

    ID_KEY = "payeeWorkingPatternID"
    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {"effectiveFrom": "effective_from"}

    employee = models.ForeignKey(FakeEmployee, on_delete=models.CASCADE, related_name="patterns")
    effective_from = models.DateField()

    class Meta(PayrollRecord.Meta):
        db_table = "xero_fake_workingpattern"


class FakeLeaveType(PayrollRecord):
    """GET /LeaveTypes (recordings/leave_types.json)."""

    ID_KEY = "leaveTypeID"
    WIRE: ClassVar[Mapping[str, str]] = {
        "name": "name",
        "isActive": "is_active",
        "isPaidLeave": "is_paid_leave",
        "typeOfUnits": "type_of_units",
    }

    name = models.CharField(max_length=255)
    is_active = models.BooleanField()
    is_paid_leave = models.BooleanField()
    type_of_units = models.CharField(max_length=50)

    class Meta(PayrollRecord.Meta):
        db_table = "xero_fake_leavetype"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["tenant_id", "name"], name="leavetype_name_unique"),
        ]


class FakeEarningsRate(PayrollRecord):
    """GET /EarningsRates (recordings/earnings_rates.json)."""

    ID_KEY = "earningsRateID"
    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {
        "name": "name",
        "earningsType": "earnings_type",
        "rateType": "rate_type",
        "typeOfUnits": "type_of_units",
        "currentRecord": "current_record",
        "ratePerUnit": "rate_per_unit",
        "fixedAmount": "fixed_amount",
        "multipleOfOrdinaryEarningsRate": "multiple_of_ordinary_earnings_rate",
    }

    name = models.CharField(max_length=255)
    earnings_type = models.CharField(max_length=50)
    rate_type = models.CharField(max_length=50)
    type_of_units = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    current_record = models.BooleanField()
    rate_per_unit = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    fixed_amount = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    multiple_of_ordinary_earnings_rate = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )

    class Meta(PayrollRecord.Meta):
        db_table = "xero_fake_earningsrate"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["tenant_id", "name"], name="earningsrate_name_unique"),
        ]


class FakePayRun(PayrollRecord):
    """GET /PayRuns (recordings/pay_runs.json); Xero holds one draft per calendar."""

    ID_KEY = "payRunID"
    UPDATED_KEY = None
    WIRE: ClassVar[Mapping[str, str]] = {
        "payrollCalendarID": "payroll_calendar_id",
        "periodStartDate": "period_start_date",
        "periodEndDate": "period_end_date",
        "paymentDate": "payment_date",
        "payRunStatus": "status",
        "payRunType": "type",
        "calendarType": "calendar_type",
        "totalCost": "total_cost",
        "totalPay": "total_pay",
        "postedDateTime": "posted_date_time",
    }

    payroll_calendar_id = models.UUIDField()
    period_start_date = models.DateField()
    period_end_date = models.DateField()
    payment_date = models.DateField()
    status = models.CharField(max_length=50)
    type = models.CharField(max_length=50)
    calendar_type = models.CharField(max_length=50)
    total_cost = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    total_pay = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    posted_date_time = models.DateTimeField(null=True, blank=True)

    class Meta(PayrollRecord.Meta):
        db_table = "xero_fake_payrun"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["tenant_id", "payroll_calendar_id"],
                condition=models.Q(status="Draft"),
                name="payrun_one_draft_per_calendar",
            ),
        ]


class FakePaySlip(PayrollRecord):
    """GET /PaySlips?PayRunID= (recordings/pay_slips.json); one per employee per run."""

    ID_KEY = "paySlipID"
    UPDATED_KEY = None
    RELATION_KEYS: ClassVar[tuple[str, ...]] = ("payRunID",)
    WIRE: ClassVar[Mapping[str, str]] = {
        "employeeID": "employee_id",
        "firstName": "first_name",
        "lastName": "last_name",
        "totalEarnings": "total_earnings",
        "grossEarnings": "gross_earnings",
        "totalPay": "total_pay",
    }

    pay_run = models.ForeignKey(FakePayRun, on_delete=models.CASCADE, related_name="slips")
    # The employee's Xero id, not a relation: a posted run's slips name
    # employees the organisation may since have ended and the mirror no
    # longer holds.
    employee_id = models.UUIDField()
    first_name = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    last_name = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 -- ADR 0040
    total_earnings = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    gross_earnings = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    total_pay = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    class Meta(PayrollRecord.Meta):
        db_table = "xero_fake_payslip"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["pay_run", "employee_id"], name="payslip_one_per_employee_per_run"
            ),
        ]

    def to_wire(self) -> dict[str, Json]:
        """Render the slip with the pay run it belongs to."""
        wire = super().to_wire()
        wire["payRunID"] = str(self.pay_run_id)
        return wire


#: Every table the fake holds, in dependency order: the seed empties them in reverse.
RESOURCES: tuple[type[XeroRecord], ...] = (
    FakeOrganisation,
    FakeContact,
    FakeAccount,
    FakeTaxRate,
    FakeBrandingTheme,
    FakeItem,
    FakeInvoice,
    FakeCreditNote,
    FakeQuote,
    FakePurchaseOrder,
    FakeHistoryRecord,
    FakeAttachment,
    FakePayRunCalendar,
    FakeEmployee,
    FakeSalaryAndWage,
    FakeWorkingPattern,
    FakeLeaveType,
    FakeEarningsRate,
    FakePayRun,
    FakePaySlip,
)
