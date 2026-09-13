"""Render a stored ``raw_json`` back into the JSON Xero puts on the wire.

``process_xero_data`` (transforms.py) is the inbound direction: the SDK's
deserialised model, dumped as its ``__dict__``. This is the outbound one, and
it is driven by the same two class attributes the deserialiser reads —
``attribute_map`` for the wire key and ``openapi_types`` for the type — so a
field the SDK does not know cannot be invented here, and a change to the
SDK's idea of the wire moves both directions together.

The two APIs put dates on the wire differently, and the SDK's type names say
which: ``date[ms-format]`` / ``datetime[ms-format]`` are the Accounting API's
``/Date(1518685950940+0000)/``, plain ``date`` / ``datetime`` are Payroll's
ISO-8601 in naive UTC. Rendering the Accounting form is what makes the fake
exercise ``deserialize_date_ms`` — the ladder ADR 0050's payroll bug lived
next to — rather than a shortcut around it.
"""

import importlib
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

from xero_python.models import BaseModel

from apps.xero.transforms import STRIPPED_RAW_KEYS

type Json = dict[str, Json] | list[Json] | str | int | float | bool | Decimal | None

_LIST_PREFIX = "list["


class WireShapeError(ValueError):
    """A stored value does not fit the SDK's declared type for its attribute."""


def to_wire(model: type[BaseModel], raw_json: Mapping[str, object]) -> dict[str, Json]:
    """Return the wire JSON for one stored object of the given SDK model."""
    models_package = importlib.import_module(model.__module__.rsplit(".", 1)[0])
    if not any(_stored_key(model, attribute) in raw_json for attribute in model.openapi_types):
        raise WireShapeError(
            f"the stored body carries none of {model.__name__}'s attributes; it was not "
            "written by process_xero_data"
        )
    wire: dict[str, Json] = {}
    for attribute, type_name in model.openapi_types.items():
        stored_key = _stored_key(model, attribute)
        if stored_key in STRIPPED_RAW_KEYS:
            # clean_json removed these before storing; there is nothing to render.
            continue
        # An absent key is an attribute the SDK has gained since the row was
        # written (1,442 of 2,000 contacts on the 2026-09-13 restore predate
        # Contact.tax_number_type; items predate quantity_available). The
        # deserialiser gives an absent wire key the constructor's None, so
        # that is what the stored body means too.
        value = raw_json.get(stored_key)
        where = f"{_api_family(model)}:{model.__name__}.{attribute}"
        rendered = (
            None if value is None else _to_wire_value(type_name, value, models_package, where)
        )
        if rendered is None:
            # The two APIs disagree here, and the recordings show which way:
            # Accounting omits a field it has no value for, Payroll sends it
            # as an explicit null.
            if _is_payroll(model):
                wire[model.attribute_map[attribute]] = None
            continue
        wire[model.attribute_map[attribute]] = rendered
    return wire


def _stored_key(model: type[BaseModel], attribute: str) -> str:
    """Return the ``__dict__`` key the SDK keeps this attribute under.

    An attribute named to dodge a Python keyword (``Account._class``,
    ``Organisation._class``) is stored as ``self.__class`` inside the model,
    which Python mangles to ``_Account__class`` — and that is the key
    process_xero_data wrote.
    """
    if attribute.startswith("_"):
        return f"_{model.__name__}_{attribute}"
    return f"_{attribute}"


def _is_payroll(model: type[BaseModel]) -> bool:
    return _api_family(model) == "payrollnz"


def _api_family(model: type[BaseModel]) -> str:
    """Return ``accounting`` or ``payrollnz``: the SDK package the model belongs to."""
    return model.__module__.split(".")[1]


def _to_wire_value(type_name: str, value: object, models_package: object, where: str) -> Json:
    """Render one attribute's stored value as the SDK type name says the wire holds it."""
    if type_name.startswith(_LIST_PREFIX):
        if not isinstance(value, list):
            raise WireShapeError(f"{where}: expected a list, got {type(value).__name__}")
        inner = type_name[len(_LIST_PREFIX) : -1]
        return [_to_wire_value(inner, item, models_package, where) for item in value]
    cls = getattr(models_package, type_name, None)
    if isinstance(cls, type) and issubclass(cls, Enum):
        return _enum_value(value, where)
    if isinstance(cls, type) and issubclass(cls, BaseModel):
        if not isinstance(value, Mapping):
            raise WireShapeError(
                f"{where}: expected a {type_name} body, got {type(value).__name__}"
            )
        if _is_null_invention(cls, value):
            return None
        return to_wire(cls, value)
    return _scalar_to_wire(type_name, value, where)


def _is_null_invention(model: type[BaseModel], stored: Mapping[str, object]) -> bool:
    """Recognise the object the SDK builds from a null on the wire.

    ``deserialize_model`` answers ``null`` with ``model("")``: an instance
    whose first attribute is the empty string and every other None
    (``problem: null`` on every Payroll answer, and the recordings show it).
    Xero sent nothing, so nothing is rendered.
    """
    first_attribute = next(iter(model.openapi_types))
    return stored.get(_stored_key(model, first_attribute)) == "" and all(
        stored.get(_stored_key(model, attribute)) in (None, "") for attribute in model.openapi_types
    )


def _text_to_wire(value: object, where: str) -> str | None:
    text = _as_str(value, where)
    if text == "None" and where.startswith("payrollnz:"):
        # deserialize_str is str(data), so a Payroll null (Payroll sends its
        # nulls explicitly) is stored as the text "None". The wire had
        # nothing there, and a fake that served the text would hand the app
        # a truthy string Xero never sends.
        return None
    return text


def _scalar_to_wire(type_name: str, value: object, where: str) -> Json:
    if type_name == "str":
        return _text_to_wire(value, where)
    if type_name == "bool":
        if not isinstance(value, bool):
            raise WireShapeError(f"{where}: expected a bool, got {type(value).__name__}")
        return value
    if type_name == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise WireShapeError(f"{where}: expected an int, got {type(value).__name__}")
        return value
    if type_name == "float":
        # process_xero_data stores the SDK's Decimals as their string form
        # (serialize_xero_object has no Decimal branch), so "725.09" comes
        # back here and must leave as the number Xero sent.
        return _as_decimal(value, where)
    if type_name in {"date[ms-format]", "datetime[ms-format]"}:
        return _ms_date(_as_str(value, where), where)
    if type_name in {"date", "datetime"}:
        return _naive_utc_iso(_as_str(value, where))
    raise WireShapeError(f"{where}: no wire rendering for SDK type {type_name!r}")


def _as_str(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise WireShapeError(f"{where}: expected a str, got {type(value).__name__}")
    return value


def _as_decimal(value: object, where: str) -> Decimal:
    if isinstance(value, bool):
        raise WireShapeError(f"{where}: expected a number, got a bool")
    if isinstance(value, Decimal | int | float | str):
        return Decimal(str(value))
    raise WireShapeError(f"{where}: expected a number, got {type(value).__name__}")


def _enum_value(value: object, where: str) -> str:
    # serialize_xero_object walks an Enum member's __dict__, so a stored enum
    # is {"_value_": "AUTHORISED", "_name_": ..., "_sort_order_": ...}; the
    # wire carries the value alone.
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        member_value = value.get("_value_")
        if isinstance(member_value, str):
            return member_value
    raise WireShapeError(f"{where}: expected an enum value, got {value!r}")


def _ms_date(iso: str, where: str) -> str:
    """Accounting API form: milliseconds since the epoch, UTC, in Microsoft's wrapper."""
    # Anything longer than a bare date is a datetime, whatever separates the
    # two halves: some mirrored rows hold str(datetime), with a space.
    parsed = (
        datetime.fromisoformat(iso)
        if len(iso) > len("YYYY-MM-DD")
        else datetime.combine(date.fromisoformat(iso), datetime.min.time())
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if not iso or parsed is None:
        raise WireShapeError(f"{where}: not an ISO date: {iso!r}")
    return f"/Date({int(parsed.timestamp() * 1000)}+0000)/"


def _naive_utc_iso(iso: str) -> str:
    """Render the Payroll form: ISO-8601 with no offset.

    Xero sends naive UTC; the SDK's deserialiser is what added the ``+00:00``
    on the way in.
    """
    return iso.removesuffix("+00:00")


def ms_date_now(moment: datetime) -> str:
    """Render one aware instant in the Accounting API form, for values the fake mints."""
    if moment.tzinfo is None:
        raise WireShapeError("a minted timestamp must be timezone-aware")
    return f"/Date({int(moment.timestamp() * 1000)}+0000)/"
