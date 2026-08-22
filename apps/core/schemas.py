"""Schema building blocks shared across the domain apps' wire shapes.

Two axes that a field must keep separate, because conflating them is what let a
field mean "may be omitted" and "may be null" at the same time, so a client
clearing a value got a success response and no change:

- **May it be omitted?** Presence.
- **May it be null?** Value, expressed by the type admitting ``None``.

Writing ``str | None = None`` says both at once, so a field that merely wanted
to be optional also started accepting ``null`` — and every handler then grew an
``is not None`` guard that dropped the value silently and returned 200.

**On a request** presence is a real question: it is expressed by giving the
field a default and read back with ``model_dump(exclude_unset=True)`` /
``model_fields_set``. Use ``NullableText`` when null is meaningful (it clears
the column) and ``omittable()`` when it is not.

**On a response presence is not a question at all.** ninja serialises with
``exclude_unset=False, exclude_defaults=False, exclude_none=False``, so every
declared field is always in the body — a declaration that it might be absent is
simply false, and it costs the client a branch for a case the server cannot
produce. Inherit ``ResponseSchema`` and the declaration matches what the server
does. Nullability stays a real question on a response and stays per-field: say
``| None`` when the producing service can actually return ``None``.

``exclude_none=True`` on an operation would break that, because it makes the
body's KEYS depend on the data: a client must then check presence, check null,
and read the value, for one answer. Four operations used it and none does now —
they send ``null`` instead, which the same client code already had to handle.
"""

from decimal import Decimal
from typing import Annotated, Any, Literal

from ninja import Schema
from pydantic import (
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
)

#: Text that must carry a value when supplied. Whitespace is stripped BEFORE
#: the length check, so "  " is the same 422 as "".
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

#: A nullable text request field. Unset is ``null``; ``""`` is a client error:
#: the columns carry not-blank CHECK constraints, so a blank string
#: would reach the database and surface as an IntegrityError -> 409 instead of
#: a validation 422. Declaring it here
#: is the single source of truth — the OpenAPI schema and the generated TS
#: client both inherit the constraint, so a new nullable field needs no
#: service-side change at all.
NullableText = NonBlankText | None

#: Opus: A quantity: ``Decimal`` in Python, a JSON **number** on the wire.
#:
#: Declaring a bare ``Decimal`` on a Schema does not do this. Pydantic
#: serialises it to a JSON *string* and publishes ``type: string`` with a
#: numeric pattern, which is exactly the shape ADR 0046 calls the review smell —
#: every consumer that is not a display then has to parse it back, and one that
#: forgets renders NaN or sorts "10" before "9".
#:
#: The float appears at the boundary and nowhere else. Precision belongs to the
#: arithmetic, not the transport: hours and money must accumulate as Decimal
#: server-side (summing them as floats is what put binary rounding error into
#: what a person is paid), while a single conversion to a JSON number at the
#: edge is lossless at the magnitudes involved. This mirrors the one deliberate
#: ``float()`` in ``payroll_push``, at the Xero SDK's own field.
Quantity = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float),
    WithJsonSchema({"type": "number"}),
]


def _drop_default(schema: dict[str, Any]) -> None:
    """Remove the default from the published schema.

    The default exists only to make the field optional; it is never read,
    because presence is decided by ``model_fields_set``. Publishing it makes
    the contract lie — four CRM PATCH fields advertised ``default: ""``
    against their own ``minLength: 1``, so the documented default was a value
    the same schema rejects.
    """
    schema.pop("default", None)


def drop_model_defaults(schema: dict[str, Any]) -> None:
    """Strip every property default from a ModelSchema's published shape.

    A schema derived from a model inherits the COLUMN defaults, and they are
    wrong on the wire in both directions. On a response they are meaningless —
    the server always sends a value. On a partial update they misdescribe
    omission, which leaves the stored value alone rather than applying any
    default.

    They are also not merely noise: a Decimal column with ``default=20.00``
    publishes as a string-typed field carrying a NUMERIC default, which
    generates `z.string().default(20)` and fails to compile.
    """
    for prop in schema.get("properties", {}).values():
        prop.pop("default", None)


def always_present(schema: dict[str, Any]) -> None:
    """Declare every property required, whatever gave it a default.

    A response field acquires a default for reasons that have nothing to do
    with the wire — a Django column default, a Python convenience like
    ``success = True``, a ``| None = None`` written to save typing. Pydantic
    reads any of them as "not required" and publishes a field the client must
    treat as possibly absent, which it never is.

    Sets ``required`` rather than editing each property, because the property
    itself is not what is wrong: ``success = True`` is a perfectly good default
    for constructing the object in Python.
    """
    properties = schema.get("properties")
    if not properties:
        return
    schema["required"] = sorted(properties)


def derived_response(schema: dict[str, Any]) -> None:
    """Both corrections a response derived from a Django model needs.

    A ``ModelSchema`` cannot simply inherit ``ResponseSchema``: it already has
    its own base and its own ``model_config``, so the hooks compose here
    instead. Deriving is still worth it — the alternative is transcribing every
    column and re-deriving nothing when one changes.
    """
    drop_model_defaults(schema)
    always_present(schema)


class ResponseSchema(Schema):
    """A schema the server sends. Every declared field is in the body.

    Inheriting this is the whole declaration — there is no per-field syntax,
    because presence is not a per-field decision on the way out.
    """

    model_config = ConfigDict(json_schema_extra=always_present)


AuthErrorCode = Literal["authentication_required", "invalid_credentials"]

AUTHENTICATION_REQUIRED_DETAIL = "Authentication required."
INVALID_CREDENTIALS_DETAIL = "Invalid e-mail or password."


class AuthErrorOut(ResponseSchema):
    """Expected authentication refusal, distinct from domain-level 401s."""

    detail: str
    code: AuthErrorCode
    # Expected refusals are security events, not application faults, so there
    # is deliberately no AppError row to cross-reference.
    error_id: None = None


def auth_error(code: AuthErrorCode) -> AuthErrorOut:
    """Build the one public authentication-refusal shape."""
    detail = (
        AUTHENTICATION_REQUIRED_DETAIL
        if code == "authentication_required"
        else INVALID_CREDENTIALS_DETAIL
    )
    return AuthErrorOut(detail=detail, code=code)


def omittable(default: Any) -> Any:
    """Declare a field whose omission means "leave the stored value alone".

    ``default`` is a placeholder the handler must not read: check
    ``model_fields_set`` (or ``model_dump(exclude_unset=True)``) to learn
    whether the client supplied anything. Give it a value of the field's own
    type — ``""`` for text, ``False`` for a flag, ``None`` for a nullable
    column — so the attribute never contradicts its annotation. On a nullable
    field ``null`` is a real value (it clears the column, ADR 0040) and only
    omission is the no-op; the annotation, not this helper, decides whether
    ``null`` is accepted.

    Returns ``Any`` for the same reason pydantic's own ``Field()`` does: the
    call sits on the right-hand side of an arbitrary annotation, so a concrete
    return type would make every use a type error.
    """
    return Field(default=default, json_schema_extra=_drop_default)
