from typing import TypeAlias

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


class FiftyPerPagePagination(PageNumberPagination):
    page_size = 50


class PageSizePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data: list[JsonValue]) -> Response:
        request = self.request
        if request is None:
            raise RuntimeError("Paginator request is not initialized")
        page = self.page
        if page is None:
            raise RuntimeError("Paginator page is not initialized")

        page_size = self.get_page_size(request) or self.page_size
        count = page.paginator.count
        return Response(
            {
                "results": data,
                "count": count,
                "page": page.number,
                "page_size": page_size,
                "total_pages": page.paginator.num_pages,
            }
        )

    def get_paginated_response_schema(self, schema: JsonObject) -> JsonObject:
        return {
            "type": "object",
            "required": ["results", "count", "page", "page_size", "total_pages"],
            "properties": {
                "results": schema,
                "count": {"type": "integer", "example": 123},
                "page": {"type": "integer", "example": 1},
                "page_size": {"type": "integer", "example": self.page_size},
                "total_pages": {"type": "integer", "example": 3},
            },
        }
