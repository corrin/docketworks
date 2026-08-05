"""Request-schema building blocks shared across the domain apps' wire shapes."""

from typing import Annotated

from pydantic import StringConstraints

#: A nullable text request field. Unset is ``null``; ``""`` is a client error:
#: the columns carry not-blank CHECK constraints, so a blank string
#: would reach the database and surface as an IntegrityError -> 409 instead of
#: a validation 422. Whitespace is stripped BEFORE the length check, so "  " is
#: the same 422 as "". Declaring it here
#: is the single source of truth — the OpenAPI schema and the generated TS
#: client both inherit the constraint, so a new nullable field needs no
#: service-side change at all.
NullableText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None
