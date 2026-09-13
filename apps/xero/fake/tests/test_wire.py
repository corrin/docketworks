"""The renderer reproduces Xero's wire bodies from what the SDK stored (ADR 0060).

Business risk covered: the fake answers every E2E iteration run through this
renderer, so a field it drops, a date it formats the other API's way or a
number it emits as text would make the SDK deserialise something Xero never
sends — and the iteration run would pass on it. The recordings are real
tenant answers captured at the transport; each is pushed through the real
SDK, stored the way the app stores it, rendered back, and must be a value-
exact subset of what was recorded.
"""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from xero_python.accounting import AccountingApi
from xero_python.models import BaseModel
from xero_python.payrollnz import PayrollNzApi

from apps.xero.fake.tests.conftest import sdk_client_answering
from apps.xero.fake.wire import Json, WireShapeError, ms_date_now, to_wire
from apps.xero.transforms import process_xero_data

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"
TENANT = "00000000-0000-0000-0000-000000000000"


def _recorded_body(name: str) -> Json:
    document = json.loads((RECORDINGS_DIR / f"{name}.json").read_text(), parse_float=Decimal)
    if not isinstance(document, dict):
        raise TypeError(f"{name}.json is not a recording document")
    body: Json = document["body"]
    return body


# Wire keys the SDK invents: a constructor default that is not None, so a
# deserialised object carries a value Xero never sent (a nested contact's
# HasAttachments: false). Rendering it back is harmless — the SDK would set
# the same value again — but the recording cannot confirm it, so the round
# trip tolerates exactly these, at exactly their default.
_SDK_INVENTED: dict[str, bool] = {
    "HasAttachments": False,
    "HasErrors": False,
    "HasValidationErrors": False,
}


def _assert_subset(rendered: Json, recorded: Json, path: str) -> None:
    """Every key the renderer emits is in the recording with the same value."""
    if isinstance(rendered, dict):
        assert isinstance(recorded, dict), f"{path}: rendered an object, recorded {recorded!r}"
        for key, value in rendered.items():
            if key not in recorded and key in _SDK_INVENTED and value == _SDK_INVENTED[key]:
                continue
            if key not in recorded and value is None:
                # Payroll nulls some absent fields and omits others (an
                # employee's title is omitted, otherGivenNames is null); the
                # SDK reads both as None, so the renderer's null is exact
                # enough and the recording cannot say which Xero would pick.
                continue
            assert key in recorded, f"{path}.{key}: rendered but not recorded"
            _assert_subset(value, recorded[key], f"{path}.{key}")
        return
    if isinstance(rendered, list):
        assert isinstance(recorded, list), f"{path}: rendered a list, recorded {recorded!r}"
        assert len(rendered) == len(recorded), (
            f"{path}: {len(rendered)} vs {len(recorded)} elements"
        )
        for index, (item, expected) in enumerate(zip(rendered, recorded, strict=True)):
            _assert_subset(item, expected, f"{path}[{index}]")
        return
    _assert_scalar(rendered, recorded, path)


def _assert_scalar(rendered: Json, recorded: Json, path: str) -> None:
    if rendered is False and recorded is None:
        # deserialize_bool is bool(data): a Payroll null on a bool field is
        # stored as False, and the SDK reads the fake's False the same way.
        return
    if isinstance(rendered, str) and isinstance(recorded, str) and _is_iso_datetime(rendered):
        # Python pads fractional seconds to six digits; Xero writes three.
        # The SDK parses both to the same instant.
        assert datetime.fromisoformat(rendered) == datetime.fromisoformat(recorded), (
            f"{path}: {rendered} != {recorded}"
        )
        return
    if isinstance(rendered, str) and rendered.startswith("/Date(") and isinstance(recorded, str):
        # Xero writes the offset on some fields and not others
        # (UpdatedDateUTC carries +0000, CreatedDateUTC does not); the SDK
        # reads both as the same instant, so the instant is what must match.
        assert _ms_of(rendered) == _ms_of(recorded), f"{path}: {rendered} != {recorded}"
        return
    if (
        isinstance(rendered, str)
        and isinstance(recorded, Decimal | int)
        and not isinstance(recorded, bool)
    ):
        # The SDK types a few numeric ids as str (a pay slip tax line's
        # globalTaxTypeID) and Xero sends them as numbers; deserialize_str
        # makes "9" of both, so the fake's "9" reads exactly as the wire's 9.
        assert Decimal(rendered) == Decimal(str(recorded)), f"{path}: {rendered!r} != {recorded!r}"
        return
    if isinstance(rendered, Decimal | int | float) and not isinstance(rendered, bool):
        assert isinstance(recorded, Decimal | int | float), f"{path}: {rendered!r} vs {recorded!r}"
        assert Decimal(str(rendered)) == Decimal(str(recorded)), f"{path}: {rendered} != {recorded}"
        return
    assert rendered == recorded, f"{path}: {rendered!r} != {recorded!r}"


# Each recording, called through the SDK method the application uses for that
# route. What comes back is the typed model; process_xero_data stores it the
# way every mirror row is stored; to_wire renders it back.
_ACCOUNTING_ROUTES: dict[str, Callable[[AccountingApi], BaseModel]] = {
    "organisation": lambda api: api.get_organisations(TENANT),
    "tax_rates": lambda api: api.get_tax_rates(TENANT),
    "branding_themes": lambda api: api.get_branding_themes(TENANT),
    "accounts": lambda api: api.get_accounts(TENANT),
    "items": lambda api: api.get_items(TENANT),
    "contacts_page": lambda api: api.get_contacts(TENANT, page=1, page_size=2),
    "contact": lambda api: api.get_contact(TENANT, "any"),
    "contacts_by_name": lambda api: api.get_contacts(TENANT, where='Name=="any"'),
    "invoices_page": lambda api: api.get_invoices(TENANT, page=1),
    "invoice": lambda api: api.get_invoice(TENANT, "any"),
    "invoice_history": lambda api: api.get_invoice_history(TENANT, "any"),
    "bills_page": lambda api: api.get_invoices(TENANT, where='Type=="ACCPAY"'),
    "credit_notes_page": lambda api: api.get_credit_notes(TENANT, page=1),
    "quotes_page": lambda api: api.get_quotes(TENANT, page=1),
    "quote": lambda api: api.get_quote(TENANT, "any"),
    "purchase_orders_page": lambda api: api.get_purchase_orders(TENANT, page=1),
    "purchase_order": lambda api: api.get_purchase_order(TENANT, "any"),
}
_PAYROLL_ROUTES: dict[str, Callable[[PayrollNzApi], BaseModel]] = {
    "employees_page": lambda api: api.get_employees(TENANT, page=1),
    "employee": lambda api: api.get_employee(TENANT, "any"),
    "salary_and_wages": lambda api: api.get_employee_salary_and_wages(TENANT, "any"),
    "working_patterns": lambda api: api.get_employee_working_patterns(TENANT, "any"),
    "working_pattern": lambda api: api.get_employee_working_pattern(TENANT, "any", "any"),
    "leave_types": lambda api: api.get_leave_types(TENANT),
    "earnings_rates": lambda api: api.get_earnings_rates(TENANT),
    "pay_runs": lambda api: api.get_pay_runs(TENANT),
    "pay_slips": lambda api: api.get_pay_slips(TENANT, "any"),
}


def _is_iso_datetime(value: str) -> bool:
    return len(value) > 10 and value[4] == "-" and value[10] == "T" and value[:4].isdigit()


def _ms_of(ms_date: str) -> int:
    return int(ms_date.removeprefix("/Date(").split("+")[0].rstrip(")/"))


def _entity_key(recorded: Json) -> str:
    """The envelope key whose value is the entity or list the route returns."""
    assert isinstance(recorded, dict)
    envelope = {"Id", "Status", "ProviderName", "DateTimeUTC", "id", "providerName"}
    envelope |= {"dateTimeUTC", "httpStatusCode", "pagination", "problem", "SummarizeErrors"}
    candidates = [key for key in recorded if key not in envelope]
    assert len(candidates) == 1, f"ambiguous entity key: {candidates}"
    return candidates[0]


@pytest.mark.parametrize("name", sorted(_ACCOUNTING_ROUTES))
def test_accounting_recordings_round_trip(name: str) -> None:
    recorded = _recorded_body(name)
    response = _ACCOUNTING_ROUTES[name](AccountingApi(sdk_client_answering(recorded)))
    rendered = to_wire(type(response), process_xero_data(response))
    key = _entity_key(recorded)
    assert key in rendered, f"{name}: the renderer emitted no {key}"
    _assert_subset(rendered, recorded, name)


@pytest.mark.parametrize("name", sorted(_PAYROLL_ROUTES))
def test_payroll_recordings_round_trip(name: str) -> None:
    recorded = _recorded_body(name)
    response = _PAYROLL_ROUTES[name](PayrollNzApi(sdk_client_answering(recorded)))
    rendered = to_wire(type(response), process_xero_data(response))
    key = _entity_key(recorded)
    assert key in rendered, f"{name}: the renderer emitted no {key}"
    _assert_subset(rendered, recorded, name)


def test_every_json_recording_has_a_round_trip_or_a_reason() -> None:
    # A recording nobody round-trips is a shape the fake could serve wrong.
    # These three carry no model: a 404 is text/html, the past-the-end 400 is
    # raised by the SDK before deserialising, and a PDF is bytes.
    unmodelled = {"invoice_not_found", "employees_past_end", "quote_pdf"}
    on_disk = {path.stem for path in RECORDINGS_DIR.glob("*.json")}
    assert on_disk == set(_ACCOUNTING_ROUTES) | set(_PAYROLL_ROUTES) | unmodelled


class TestMintedValues:
    def test_a_minted_timestamp_is_the_accounting_form(self) -> None:
        moment = datetime(2026, 9, 13, 3, 13, 48, 733000, tzinfo=UTC)
        assert ms_date_now(moment) == "/Date(1789269228733+0000)/"

    def test_a_naive_minted_timestamp_is_refused(self) -> None:
        with pytest.raises(WireShapeError, match="timezone-aware"):
            ms_date_now(datetime(2026, 9, 13))  # noqa: DTZ001 -- the naive input is the case


class TestShapeRefusals:
    """A stored value that does not fit the SDK's type is a bug to see, not a null to send."""

    def test_a_missing_attribute_is_refused(self) -> None:
        from xero_python.accounting import Phone  # noqa: PLC0415 -- the smallest model

        with pytest.raises(WireShapeError, match=r"Phone\.phone_type is absent"):
            to_wire(Phone, {})

    def test_a_string_where_a_bool_belongs_is_refused(self) -> None:
        from xero_python.accounting import Contact  # noqa: PLC0415

        stored: Mapping[str, object] = {f"_{attr}": None for attr in Contact.openapi_types}
        with pytest.raises(WireShapeError, match=r"Contact\.is_supplier: expected a bool"):
            to_wire(Contact, {**stored, "_is_supplier": "yes"})
