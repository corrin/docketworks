"""Build the response objects the SDK's transport hands back, without a socket."""

import json
from collections.abc import Mapping
from decimal import Decimal

import urllib3
from xero_python.rest import RESTResponse

from apps.xero.fake.wire import Json


def _json_default(value: object) -> float:
    if isinstance(value, Decimal):
        # JSON has one number type; Decimal("725.09") and 725.09 parse back
        # to the same Decimal under the SDK's parse_float=Decimal.
        return float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def json_response(status: int, body: Json, headers: Mapping[str, str]) -> RESTResponse:
    """Wrap a JSON body exactly as urllib3 would have delivered it."""
    data = json.dumps(body, default=_json_default).encode()
    return raw_response(status, data, {"Content-Type": "application/json", **headers})


def raw_response(status: int, data: bytes, headers: Mapping[str, str]) -> RESTResponse:
    """Wrap bytes as the SDK's RESTResponse; the PDF route and errors use this."""
    return RESTResponse(
        urllib3.HTTPResponse(body=data, status=status, headers=dict(headers), preload_content=True)
    )
