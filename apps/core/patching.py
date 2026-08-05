"""The PATCH write contract: apply exactly the keys the client sent.

One rule, enforced here rather than restated per endpoint: **a partial update
writes only the keys present in the payload**, so a form that posts one field
can never disturb the fields beside it. (Clients preferring full-replacement
semantics simply send every key.)

Deliberately NOT here: normalising blank strings to NULL. Nullable text
*request* fields are declared nullable-and-nonblank in the schema, so ``""``
is a validation 422 before any service sees it and ``null`` is the way to
clear a value. A service-side ``value or None`` shim would let validation drift
field by field and eventually send a blank to a not-blank database constraint.

Because the schema is the single declaration site, adding a nullable field
needs no change here or in any service.
"""

from django.db import models


def apply_patch_fields(
    instance: models.Model,
    payload: dict[str, object],
    *,
    fields: frozenset[str] | set[str],
) -> None:
    """Write the supplied ``fields`` from ``payload`` onto ``instance``.

    Keys absent from ``payload`` are left untouched; supplied values are
    assigned as validated (the schema has already rejected blank strings for
    nullable text columns).
    """
    for field in fields:
        if field in payload:
            setattr(instance, field, payload[field])
