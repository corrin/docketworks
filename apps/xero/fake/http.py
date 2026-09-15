"""The transport-level shapes: a request as the SDK sends it, a response as urllib3 delivers it."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

import urllib3
from xero_python.rest import RESTResponse

from apps.xero.fake.wire import Json

TENANT_HEADER = "xero-tenant-id"


class FakeXeroRequestError(ValueError):
    """The SDK sent something the fake cannot read; a bug on one side or the other."""


class FakeXeroUnhandledRouteError(NotImplementedError):
    """A call, a parameter or a filter the fake has no answer for: never a guess, always this."""


@dataclass(frozen=True)
class FakeRequest:
    """One call as it reached the transport, before any socket would have opened."""

    method: str
    host: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    json_body: Json
    raw_body: bytes | None
    form: dict[str, str] = field(default_factory=dict)

    def header(self, name: str) -> str | None:
        """Return one header regardless of the case the SDK sent it in."""
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None

    @property
    def tenant_id(self) -> str:
        """The organisation this call addresses; every Accounting and Payroll route carries it."""
        tenant_id = self.header(TENANT_HEADER)
        if not tenant_id:
            raise FakeXeroRequestError(f"{self.method} {self.path} carries no {TENANT_HEADER}")
        return tenant_id

    def flag(self, name: str) -> bool:
        """Read a boolean query parameter as the SDK spells it (``str(True)`` is ``"True"``)."""
        return self.query.get(name, "").lower() == "true"


def query_dict(query_params: object) -> dict[str, str]:
    """Normalise the SDK's query shapes: it passes a list of pairs, or nothing."""
    if query_params is None:
        return {}
    if isinstance(query_params, Mapping):
        return {str(key): str(value) for key, value in query_params.items()}
    if isinstance(query_params, list):
        return {str(key): str(value) for key, value in query_params}
    raise FakeXeroRequestError(f"unexpected query_params shape: {type(query_params).__name__}")


def request_from_sdk(  # noqa: PLR0913, PLR0917 -- one argument per thing RESTClientObject.request receives
    method: str,
    url: str,
    query_params: object,
    headers: object,
    body: object,
    post_params: object,
) -> FakeRequest:
    """Read what ``RESTClientObject.request`` was handed into one typed value."""
    if not url.startswith("https://"):
        raise FakeXeroRequestError(f"not an https URL: {url}")
    host, _, path = url.removeprefix("https://").partition("/")
    if headers is not None and not isinstance(headers, Mapping):
        raise FakeXeroRequestError(f"unexpected headers shape: {type(headers).__name__}")
    header_map = {str(key): str(value) for key, value in (headers or {}).items()}
    json_body: Json = None
    raw_body: bytes | None = None
    if isinstance(body, dict | list):
        # The SDK serialises a JSON body to a plain dict or list and lets the
        # transport json.dumps it; reading it here as JSON keeps the fake on
        # the wire representation (Decimals for numbers) the SDK would parse.
        json_body = json.loads(json.dumps(body), parse_float=Decimal)
    elif isinstance(body, bytes):
        raw_body = body
    elif isinstance(body, str):
        raw_body = body.encode()
    elif body is not None:
        raise FakeXeroRequestError(f"unexpected body shape: {type(body).__name__}")
    return FakeRequest(
        method=method.upper(),
        host=host,
        path=f"/{path}",
        query=query_dict(query_params),
        headers=header_map,
        json_body=json_body,
        raw_body=raw_body,
        form=query_dict(post_params),
    )


def _json_default(value: object) -> float:
    if isinstance(value, Decimal):
        # JSON has one number type; Decimal("725.09") and 725.09 parse back
        # to the same Decimal under the SDK's parse_float=Decimal.
        return float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def json_response(status: int, body: Json, headers: Mapping[str, str]) -> RESTResponse:
    """Wrap a JSON body exactly as urllib3 would have delivered it."""
    data = json.dumps(body, default=_json_default).encode()
    return raw_response(
        status, data, {"Content-Type": "application/json; charset=utf-8", **headers}
    )


def raw_response(status: int, data: bytes, headers: Mapping[str, str]) -> RESTResponse:
    """Wrap bytes as the SDK's RESTResponse; the PDF route and errors use this."""
    return RESTResponse(
        urllib3.HTTPResponse(body=data, status=status, headers=dict(headers), preload_content=True)
    )
