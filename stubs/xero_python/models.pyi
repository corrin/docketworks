from typing import Any, ClassVar

class BaseModel:
    # Fable: the two class attributes every generated model carries. The
    # deserialiser reads them to map wire keys onto attributes; the fake Xero
    # reads the same two to map attributes back onto wire keys, so a field
    # neither side knows cannot be invented by either.
    openapi_types: ClassVar[dict[str, str]]
    attribute_map: ClassVar[dict[str, str]]
    def to_dict(self) -> dict[str, Any]: ...
