"""The transport the SDK is given under ``XERO_FAKE``: every call answered locally.

Installed by ``apps.xero.auth._build`` in place of ``RateLimitedRESTClient``.
Same seam, same signature, same exception on a non-2xx, so nothing above the
transport can tell — which is the point: the SDK deserialises the fake's
bytes exactly as it would Xero's.
"""

from urllib3 import HTTPResponse
from xero_python.api_client.configuration import Configuration
from xero_python.exceptions import HTTPStatusException
from xero_python.rest import RESTClientObject, RESTResponse

from apps.core.environment import assert_not_production_database
from apps.core.models import CompanyDefaults
from apps.xero.fake.http import request_from_sdk
from apps.xero.fake.router import dispatch
from apps.xero.operator_guards import is_production_tenant


def assert_fake_permitted() -> None:
    """Refuse to exist anywhere a fabricated Xero id could reach real data.

    settings.py already refuses ``XERO_FAKE`` outside DEBUG; the two checks
    that need the database — a production database name, a production
    tenant — are made here, where the fake is installed. ``get_tenant_id``
    is not called: it refreshes the token, which would build this client,
    which would call this.
    """
    assert_not_production_database(
        "the fake Xero would mint ids the real organisation has never issued "
        "straight into a production mirror."
    )
    tenant_id = CompanyDefaults.get_solo().xero_tenant_id
    if tenant_id and is_production_tenant(tenant_id):
        raise ValueError(
            f"XERO_FAKE is set but this installation is bound to production tenant {tenant_id}; "
            "the fake exists for a development organisation only."
        )


class FakeXeroRESTClient(RESTClientObject):
    """``RESTClientObject`` whose every request is answered by the route table."""

    def __init__(self, configuration: Configuration) -> None:  # noqa: D107 -- narrows the SDK constructor; class docstring covers it
        assert_fake_permitted()
        super().__init__(configuration)

    def request(  # noqa: PLR0913, PLR0917 -- the SDK base-class signature; not ours to shrink
        self,
        method: str,
        url: str,
        query_params: object = None,
        headers: object = None,
        body: object = None,
        post_params: object = None,
        _preload_content: bool = True,
        _request_timeout: object = None,
    ) -> RESTResponse | HTTPResponse:
        """Answer from the store; raise as the SDK's transport does on a non-2xx."""
        del _request_timeout
        response = dispatch(request_from_sdk(method, url, query_params, headers, body, post_params))
        if not 200 <= response.status <= 299:
            raise HTTPStatusException(http_resp=response)
        if not _preload_content:
            # The token refresh asks for the raw urllib3 response (rest.py:244).
            return response.urllib3_response
        return response
