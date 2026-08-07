"""Request-schema building blocks shared across the domain apps' wire shapes.

Two axes that a request field must keep separate, because conflating them is
what let a field mean "may be omitted" and "may be null" at the same time, so a
client clearing a value got a success response and no change:

- **May it be omitted?** Presence, expressed by giving the field a default and
  read back with ``model_dump(exclude_unset=True)`` / ``model_fields_set``.
- **May it be null?** Value, expressed by the type admitting ``None``.

Writing ``str | None = None`` says both at once, so a field that merely wanted
to be optional also started accepting ``null`` — and every handler then grew an
``is not None`` guard that dropped the value silently and returned 200. Use
``NullableText`` when null is meaningful (it clears the column) and
``omittable()`` when it is not.
"""

from typing import Annotated, Any

from pydantic import Field, StringConstraints

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


def omittable(default: Any) -> Any:
    """Declare a field that may be omitted but must never be sent as ``null``.

    ``default`` is a placeholder the handler must not read: check
    ``model_fields_set`` (or ``model_dump(exclude_unset=True)``) to learn
    whether the client supplied anything. Give it a value of the field's own
    type — ``""`` for text, ``False`` for a flag — so the attribute never
    contradicts its annotation.

    Returns ``Any`` for the same reason pydantic's own ``Field()`` does: the
    call sits on the right-hand side of an arbitrary annotation, so a concrete
    return type would make every use a type error.
    """
    return Field(default=default, json_schema_extra=_drop_default)
