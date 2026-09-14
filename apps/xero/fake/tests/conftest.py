"""An SDK client bound to the fake transport, over a store with the organisation's fixtures."""

from collections.abc import Iterator

import pytest
from xero_python.accounting import AccountingApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.payrollnz import PayrollNzApi
from xero_python.rest import RESTClientObject, RESTResponse

from apps.xero.fake.http import json_response
from apps.xero.fake.rest_client import FakeXeroRESTClient
from apps.xero.fake.testing import seed_fixtures
from apps.xero.fake.wire import Json

TENANT = "11111111-1111-1111-1111-111111111111"
THEME = "7889a0ac-262a-40e3-8a63-9a769b1a18af"


@pytest.fixture
def tenant(db: None) -> str:
    """One organisation seeded with what a seed always provides; its tenant id."""
    del db
    seed_fixtures(TENANT)
    return TENANT


@pytest.fixture
def client(tenant: str) -> Iterator[ApiClient]:
    """The real SDK client, its transport replaced exactly as auth._build does under XERO_FAKE."""
    del tenant
    api_client = ApiClient(
        Configuration(oauth2_token=OAuth2Token(client_id="fake", client_secret="fake"))
    )

    @api_client.oauth2_token_getter
    def _token() -> dict[str, object]:
        # No expires_at: valid forever, so the SDK never refreshes through the fake here.
        return {
            "access_token": "fake-access-token",
            "token_type": "Bearer",
            "scope": [],
            "expires_in": 1800,
        }

    api_client.rest_client = FakeXeroRESTClient(api_client.configuration)
    yield api_client


@pytest.fixture
def accounting(client: ApiClient) -> AccountingApi:
    return AccountingApi(client)


@pytest.fixture
def payroll(client: ApiClient) -> PayrollNzApi:
    return PayrollNzApi(client)


class CannedRESTClient(RESTClientObject):
    """Answer every request with one recorded body; the SDK does the rest."""

    def __init__(self, configuration: Configuration, body: Json) -> None:
        super().__init__(configuration)
        self._body = body

    def request(  # noqa: PLR0913, PLR0917 -- the SDK base-class signature
        self,
        method: str,
        url: str,
        query_params: object = None,
        headers: object = None,
        body: object = None,
        post_params: object = None,
        _preload_content: bool = True,
        _request_timeout: object = None,
    ) -> RESTResponse:
        del method, url, query_params, headers, body, post_params, _request_timeout
        return json_response(200, self._body, {})


def sdk_client_answering(body: Json) -> ApiClient:
    """A real SDK client whose transport returns ``body`` to every call."""
    api_client = ApiClient(
        Configuration(oauth2_token=OAuth2Token(client_id="fake", client_secret="fake"))
    )

    @api_client.oauth2_token_getter
    def _token() -> dict[str, object]:
        return {
            "access_token": "fake-access-token",
            "token_type": "Bearer",
            "scope": [],
            "expires_in": 1800,
        }

    api_client.rest_client = CannedRESTClient(api_client.configuration, body)
    return api_client
