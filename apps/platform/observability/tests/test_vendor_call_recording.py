"""What the shared recorder writes.

Business case: the log is the only record of what this install spends on
external vendors, and that spend is what stops payroll posting, stock sync and
quoting when a daily quota runs out. A recorder that silently stops writing
leaves the next "where did it go?" to manual archaeology again.

Each vendor's own seam is tested in that vendor's context, because
``apps.platform`` may not import them (ADR 0055).
"""

import pytest
import requests

from apps.platform.observability.models import VendorCall
from apps.platform.observability.recording import endpoint_of, record_response


class TestEndpointOf:
    def test_strips_the_query_string(self) -> None:
        # Ids and cursors in the query string would split one endpoint into a
        # distinct value per request and defeat every grouping over the table.
        assert endpoint_of("https://api.xero.com/api.xro/2.0/Invoices?page=3") == (
            "/api.xro/2.0/Invoices"
        )


@pytest.mark.django_db
class TestRequestsRecording:
    """The one recorder shared by every ``requests``-based vendor.

    Maps, Xero's token endpoint and the phone provider all reach it, so a
    regression here silently stops recording three vendors at once.
    """

    def _response(self, *, status: int, method: str, url: str) -> requests.Response:
        response = requests.Response()
        response.status_code = status
        response.request = requests.Request(method=method, url=url).prepare()
        return response

    def _fire(self, response: requests.Response) -> None:
        record_response(response, vendor=VendorCall.Vendor.MAPS)

    def test_records_the_call(self) -> None:
        self._fire(
            self._response(
                status=200,
                method="POST",
                url="https://places.googleapis.com/v1/places:searchText",
            )
        )

        row = VendorCall.objects.get()
        assert row.vendor == VendorCall.Vendor.MAPS
        assert row.method == "POST"
        assert row.endpoint == "/v1/places:searchText"
        assert row.status_code == 200

    def test_records_a_refusal_the_vendor_answered(self) -> None:
        # A 429 or 403 spent the vendor's budget as surely as a 200 did.
        # Recording only successes under-counts exactly the failing runs.
        self._fire(
            self._response(
                status=429,
                method="GET",
                url="https://places.googleapis.com/v1/places/abc",
            )
        )

        assert VendorCall.objects.get().status_code == 429
