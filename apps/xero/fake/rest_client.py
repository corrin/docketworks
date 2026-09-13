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
from apps.xero.fake.http import request_from_sdk
from apps.xero.fake.router import dispatch


def assert_fake_permitted() -> None:
    """Refuse to exist anywhere a fabricated Xero id could reach real data.

    The database name is the one signal (ADR 0048): a production database is
    refused, anything else — a development database, or the scrub copy an
    instance verifies its release on (ADR 0064) — may carry the fake. The
    tenant the copy is bound to does not matter, because no call leaves the
    fake and the copy is emptied after the run; the sync and seed commands
    that DO reach the organisation keep their own tenant refusal
    (``assert_not_production_target``).
    """
    assert_not_production_database(
        "the fake Xero would mint ids the real organisation has never issued "
        "straight into a production mirror."
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
