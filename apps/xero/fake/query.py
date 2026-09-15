"""Xero's query language over the model, parsed once into ORM filters (ADR 0060).

``where`` (Xero's filter grammar: comparisons on a resource's fields joined by
AND/OR, ``Guid("…")``, ``DateTime(y,m,d)``, ``.Contains("…")`` and its
siblings), ``order``, ``page``/``pageSize``, ``IDs``, ``Statuses``,
``InvoiceNumbers``, ``ContactIDs``, ``includeArchived`` and
``If-Modified-Since`` all resolve here to typed queries on the columns
models.py declares. A field or a parameter this module does not implement is
raised, never dropped: a dropped parameter would be a belief about Xero.
"""

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from uuid import UUID

from django.db import models
from django.db.models import Q, QuerySet

from apps.xero.fake.http import FakeRequest, FakeXeroUnhandledRouteError
from apps.xero.fake.models import FakeContact, XeroRecord
from apps.xero.fake.wire import Json

PAGE_SIZE = 100
PAGE_SIZE_MAX = 1000


# ---- the fields a resource can be queried by --------------------------------------


def queryable(model: type[XeroRecord]) -> dict[str, str]:
    """Wire field → ORM path, for every field Xero lets a caller filter or order by."""
    fields: dict[str, str] = {}
    if model.ID_KEY is not None:
        fields[model.ID_KEY] = "id"
    if model.UPDATED_KEY is not None:
        fields[model.UPDATED_KEY] = "updated_date_utc"
    fields.update(model.WIRE)
    if any(field.name == "contact" for field in model._meta.fields):
        # A document is filtered through its contact: Contact.ContactID, Contact.Name.
        fields["Contact.ContactID"] = "contact_id"
        fields.update(
            {f"Contact.{key}": f"contact__{column}" for key, column in FakeContact.WIRE.items()}
        )
    return fields


# ---- where ---------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""
    (?P<space>\s+)
    | (?P<string>"(?:[^"\\]|\\.)*")
    | (?P<number>-?\d+(?:\.\d+)?)
    | (?P<op>==|!=|>=|<=|>|<|&&|\|\|)
    | (?P<paren>[()])
    | (?P<comma>,)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
    """,
    re.VERBOSE,
)
_LOOKUPS = {"==": "", "!=": "", ">": "__gt", ">=": "__gte", "<": "__lt", "<=": "__lte"}
# Xero compares text without regard to case: a name asked for in lower case
# finds the contact (recordings/contacts_by_name_other_case.json), so every
# text lookup is the case-insensitive one and ToLower()/ToUpper() change nothing.
_METHODS = {"Contains": "icontains", "StartsWith": "istartswith", "EndsWith": "iendswith"}
_CASE_FOLDS = ("ToLower", "ToUpper")


class _Tokens:
    def __init__(self, expression: str) -> None:
        self.expression = expression
        self.items: list[tuple[str, str]] = []
        position = 0
        while position < len(expression):
            matched = _TOKEN.match(expression, position)
            if matched is None:
                raise FakeXeroUnhandledRouteError(
                    f"where filter {expression!r}: cannot read from position {position}"
                )
            position = matched.end()
            kind = matched.lastgroup
            if kind is None:
                raise FakeXeroUnhandledRouteError(f"where filter {expression!r}: no token")
            if kind != "space":
                self.items.append((kind, matched.group(kind)))
        self.index = 0

    def peek(self) -> tuple[str, str] | None:
        return self.items[self.index] if self.index < len(self.items) else None

    def take(self, kind: str, value: str | None = None) -> str:
        token = self.peek()
        if token is None or token[0] != kind or (value is not None and token[1] != value):
            raise FakeXeroUnhandledRouteError(
                f"where filter {self.expression!r}: expected {value or kind}, got {token}"
            )
        self.index += 1
        return token[1]

    def accept(self, kind: str, value: str | None = None) -> bool:
        token = self.peek()
        if token is None or token[0] != kind or (value is not None and token[1] != value):
            return False
        self.index += 1
        return True


class _Where:
    """Recursive descent over Xero's filter grammar, yielding one Q."""

    def __init__(self, expression: str, fields: Mapping[str, str], model: type[XeroRecord]):
        self.tokens = _Tokens(expression)
        self.fields = fields
        self.model = model
        self.expression = expression

    def parse(self) -> Q:
        query = self._or()
        if self.tokens.peek() is not None:
            raise FakeXeroUnhandledRouteError(
                f"where filter {self.expression!r}: trailing {self.tokens.peek()}"
            )
        return query

    def _or(self) -> Q:
        left = self._and()
        while self.tokens.accept("ident", "OR") or self.tokens.accept("op", "||"):
            left = left | self._and()
        return left

    def _and(self) -> Q:
        left = self._unary()
        while self.tokens.accept("ident", "AND") or self.tokens.accept("op", "&&"):
            left = left & self._unary()
        return left

    def _unary(self) -> Q:
        if self.tokens.accept("paren", "("):
            inner = self._or()
            self.tokens.take("paren", ")")
            return inner
        return self._comparison()

    def _comparison(self) -> Q:
        name = self.tokens.take("ident")
        parts = name.split(".")
        method: str | None = None
        case_fold = False
        # A field may carry a case fold and a method: Name.ToLower().Contains("x").
        while parts and (parts[-1] in _CASE_FOLDS or parts[-1] in _METHODS):
            trailing = parts.pop()
            if trailing in _CASE_FOLDS:
                case_fold = True
                self.tokens.take("paren", "(")
                self.tokens.take("paren", ")")
            else:
                method = trailing
        field = ".".join(parts)
        path = self.fields.get(field)
        if path is None:
            raise FakeXeroUnhandledRouteError(
                f"where filter {self.expression!r}: {self.model.__name__} has no field {field!r} "
                f"(the fake queries {sorted(self.fields)})"
            )
        if method is not None:
            return self._method_query(path, method, case_fold=case_fold)
        operator = self.tokens.take("op")
        if operator not in _LOOKUPS:
            raise FakeXeroUnhandledRouteError(
                f"where filter {self.expression!r}: {operator!r} is not a comparison"
            )
        value = self._value(path)
        if value is None:
            if operator not in ("==", "!="):
                raise FakeXeroUnhandledRouteError(f"where filter {self.expression!r}: null ordered")
            query = Q(**{f"{path}__isnull": True})
            return query if operator == "==" else ~query
        del case_fold
        lookup = _LOOKUPS[operator]
        if isinstance(value, str) and operator in ("==", "!="):
            lookup = "__iexact"
        query = Q(**{f"{path}{lookup}": value})
        return ~query if operator == "!=" else query

    def _method_query(self, path: str, method: str, *, case_fold: bool) -> Q:
        """``Field.Contains("x")``, optionally compared to a bool: ``…==false`` negates."""
        self.tokens.take("paren", "(")
        argument = self._value(path)
        self.tokens.take("paren", ")")
        del case_fold
        query = Q(**{f"{path}__{_METHODS[method]}": argument})
        negated = False
        if self.tokens.accept("op", "=="):
            negated = self.tokens.take("ident").lower() == "false"
        elif self.tokens.accept("op", "!="):
            negated = self.tokens.take("ident").lower() == "true"
        return ~query if negated else query

    def _value(self, path: str) -> object:
        token = self.tokens.peek()
        if token is None:
            raise FakeXeroUnhandledRouteError(f"where filter {self.expression!r}: value missing")
        kind, text = token
        self.tokens.index += 1
        if kind == "string":
            return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if kind == "number":
            return Decimal(text)
        if kind != "ident":
            raise FakeXeroUnhandledRouteError(
                f"where filter {self.expression!r}: unexpected {text!r} as a value"
            )
        lowered = text.lower()
        if lowered in ("true", "false"):
            return lowered == "true"
        if lowered == "null":
            return None
        if text == "Guid":
            self.tokens.take("paren", "(")
            raw = self.tokens.take("string")[1:-1]
            self.tokens.take("paren", ")")
            return UUID(raw)
        if text == "DateTime":
            return self._date_time(path)
        raise FakeXeroUnhandledRouteError(
            f"where filter {self.expression!r}: {text!r} is not a value the fake reads"
        )

    def _date_time(self, path: str) -> date | datetime:
        self.tokens.take("paren", "(")
        parts = [int(self.tokens.take("number"))]
        while self.tokens.accept("comma"):
            parts.append(int(self.tokens.take("number")))
        self.tokens.take("paren", ")")
        year, month, day, hour, minute, second = (parts + [0] * 6)[:6]
        moment = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
        field = self.model._meta.get_field(path.split("__", maxsplit=1)[0])
        if isinstance(field, models.DateTimeField):
            return moment
        return moment.date()


def where(model: type[XeroRecord], expression: str) -> Q:
    """Parse one ``where`` expression against the resource's queryable fields."""
    return _Where(expression, queryable(model), model).parse()


# ---- order, ids, paging, the header ---------------------------------------------------


def order(model: type[XeroRecord], expression: str) -> list[str]:
    """Parse ``order=Field [ASC|DESC][, …]`` into ``order_by`` arguments."""
    fields = queryable(model)
    ordering: list[str] = []
    for clause in expression.split(","):
        words = clause.split()
        if not words or len(words) > 2:
            raise FakeXeroUnhandledRouteError(f"order {expression!r}: cannot read {clause!r}")
        path = fields.get(words[0])
        if path is None:
            raise FakeXeroUnhandledRouteError(
                f"order {expression!r}: {model.__name__} has no field {words[0]!r}"
            )
        direction = words[1].upper() if len(words) == 2 else "ASC"
        if direction not in ("ASC", "DESC"):
            raise FakeXeroUnhandledRouteError(f"order {expression!r}: {words[1]!r} is not ASC/DESC")
        ordering.append(f"{'-' if direction == 'DESC' else ''}{path}")
    # Xero's paging is stable within an order; the id breaks ties.
    ordering.append("id")
    return ordering


def modified_since(request: FakeRequest) -> datetime | None:
    """Read the ``If-Modified-Since`` header, in either form the spec allows."""
    header = request.header("If-Modified-Since")
    if header is None:
        return None
    try:
        parsed = datetime.fromisoformat(header)
    # deliberate-swallow: the SDK sends If-Modified-Since as ISO-8601 and the spec
    # allows RFC 1123; the second parser is the other accepted form
    except ValueError:
        parsed = parsedate_to_datetime(header)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _ids(raw: str, parameter: str) -> list[UUID]:
    try:
        return [UUID(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise FakeXeroUnhandledRouteError(f"{parameter}={raw!r}: not ids") from exc


#: The listing parameters the fake implements, by query key, and the column each narrows.
_ID_LISTS = {"IDs": "id", "ContactIDs": "contact_id"}
_TEXT_LISTS = {"Statuses": "status", "InvoiceNumbers": "number"}
_HANDLED = frozenset({"where", "order", "page", "pageSize", "includeArchived", "summarizeErrors"})


def listing[T: XeroRecord](
    model: type[T], request: FakeRequest, *, extra: Iterable[str] = ()
) -> QuerySet[T]:
    """Return the rows a listing route pages over: the tenant's, narrowed and ordered as asked.

    ``extra`` names the query keys a route handles itself (a quote's Status,
    a pay slip's PayRunID); anything else the request carries that this
    function does not implement is raised.
    """
    rows = model.for_tenant(request.tenant_id)
    for key, raw in request.query.items():
        if key in _HANDLED or key in extra:
            continue
        if key in _ID_LISTS:
            rows = rows.filter(**{f"{_ID_LISTS[key]}__in": _ids(raw, key)})
        elif key in _TEXT_LISTS:
            rows = rows.filter(**{f"{_TEXT_LISTS[key]}__in": [s.strip() for s in raw.split(",")]})
        else:
            raise FakeXeroUnhandledRouteError(
                f"{request.method} {request.path}: the fake does not implement {key}={raw!r}"
            )
    since = modified_since(request)
    if since is not None:
        rows = rows.filter(updated_date_utc__gte=since)
    expression = request.query.get("where")
    if expression is not None:
        rows = rows.filter(where(model, expression))
    ordering = request.query.get("order")
    if ordering is not None:
        rows = rows.order_by(*order(model, ordering))
    return rows


class PastTheEnd(Exception):  # noqa: N818 -- a routed outcome, not a defect
    """Payroll's answer to a page beyond the last: 400 InvalidRequest."""


def page[T: XeroRecord](
    request: FakeRequest, rows: QuerySet[T], *, default_size: int = PAGE_SIZE
) -> tuple[list[T], dict[str, Json] | None]:
    """Slice a listing as Xero pages it, with the ``pagination`` block when a page was asked for.

    Without ``page`` the whole listing is the answer, as it is on Xero.
    """
    raw_page = request.query.get("page")
    if raw_page is None:
        return list(rows), None
    number = int(raw_page)
    size = min(int(request.query.get("pageSize", default_size)), PAGE_SIZE_MAX)
    if number < 1 or size < 1:
        raise FakeXeroUnhandledRouteError(f"page={raw_page} pageSize={size}: not a page")
    count = rows.count()
    page_count = max(1, -(-count // size))
    if number > page_count and request.path.startswith("/payroll.xro/"):
        raise PastTheEnd
    offset = (number - 1) * size
    block: dict[str, Json] = {
        "page": number,
        "pageSize": size,
        "pageCount": page_count,
        "itemCount": count,
    }
    return list(rows[offset : offset + size]), block
