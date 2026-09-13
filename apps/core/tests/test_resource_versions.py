"""Compression must not remove the token required to edit a resource."""

import pytest
from django.http import HttpRequest, HttpResponse
from django.middleware.gzip import GZipMiddleware

from apps.core.middleware import ResourceVersionMiddleware


@pytest.mark.parametrize("kind", ["job", "po", "stocktake"])
def test_compressed_resource_keeps_its_strong_version(kind: str) -> None:
    """Missing middleware support must fail before a compressed editor reaches the browser."""
    version = f'"{kind}:11111111-1111-1111-1111-111111111111:3"'
    request = HttpRequest()
    request.META["HTTP_ACCEPT_ENCODING"] = "gzip"

    def view(_request: HttpRequest) -> HttpResponse:
        response = HttpResponse("counted stock line " * 80)
        response["ETag"] = version
        return response

    response = GZipMiddleware(view).process_response(
        request, ResourceVersionMiddleware(view)(request)
    )
    assert response["Content-Encoding"] == "gzip"
    assert response["ETag"] == f"W/{version}"
    assert response.headers.get("X-Resource-Version") == version
