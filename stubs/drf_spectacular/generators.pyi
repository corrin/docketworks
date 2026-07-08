from typing import TypeAlias

from django.http import HttpRequest

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]

class SchemaGenerator:
    def __init__(self) -> None: ...
    def get_schema(
        self, request: HttpRequest | None = ..., public: bool = ...
    ) -> JsonObject | None: ...
