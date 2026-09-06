"""What the vendor-call log records for Xero, and the day-quota floor it gates on.

Business case: automated Xero jobs must stop only when a fresh reading proves
they would burn API calls reserved for interactive work. False positives stop
useful sync; false negatives burn the quota a user needs to send an invoice.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from xero_python.exceptions import ApiException

from apps.platform.observability.models import VendorCall
from apps.xero.client import RateLimitedRESTClient, quota_floor_breached

from .conftest import record_xero_quota


@pytest.mark.django_db
class TestQuotaFloorBreached:
    def test_no_reading_returns_false(self) -> None:
        # A refactor that treated "we have never called Xero" as "no quota
        # left" would gate every sync on a fresh install. Unknown is not empty.
        assert not quota_floor_breached(100)

    def test_day_remaining_above_floor_returns_false(self) -> None:
        record_xero_quota(day_remaining=200)
        assert not quota_floor_breached(100)

    def test_day_remaining_at_floor_returns_true(self) -> None:
        record_xero_quota(day_remaining=100)
        assert quota_floor_breached(100)

    def test_day_remaining_below_floor_returns_true(self) -> None:
        record_xero_quota(day_remaining=50)
        assert quota_floor_breached(100)

    def test_reading_without_day_header_returns_false(self) -> None:
        # Xero omits X-DayLimit-Remaining on some responses. Dropping the
        # is-null filter would make that absence read as zero and gate.
        record_xero_quota(day_remaining=None)
        assert not quota_floor_breached(100)

    def test_stale_reading_returns_false(self) -> None:
        # Dropping the staleness predicate would let one 429 pin the gate
        # closed for the rest of the rolling window, long after it freed.
        record_xero_quota(day_remaining=10, age_seconds=60 * 60)
        assert not quota_floor_breached(100)

    def test_newest_reading_wins(self) -> None:
        # An ordering slip here reads the oldest row and gates on quota that
        # has since been spent, or refuses to gate on quota that has not.
        record_xero_quota(day_remaining=500, age_seconds=120)
        record_xero_quota(day_remaining=10)
        assert quota_floor_breached(100)


@pytest.mark.django_db
class TestPacedRequestRecording:
    """Every outcome of a Xero request becomes exactly one row.

    Recording only 2xx responses would leave the log blind at exactly the
    point the budget runs out, which is the question the log exists to
    answer — so the refused calls are the ones these tests pin down.
    """

    def _client(self) -> RateLimitedRESTClient:
        client = RateLimitedRESTClient.__new__(RateLimitedRESTClient)
        client._last_call_time = 0.0
        client._summary_started_at = time.time()
        client._request_count = 0
        client._rate_limit_hits = 0
        client._low_water_minute_remaining = None
        client._low_water_day_remaining = None
        client._minute_warning_band = None
        client._day_warning_band = None
        return client

    @staticmethod
    def _headers(day: str, minute: str) -> dict[str, str]:
        return {"X-DayLimit-Remaining": day, "X-MinLimit-Remaining": minute}

    @staticmethod
    def _refusal(status: int, headers: dict[str, str]) -> ApiException:
        """An ApiException shaped the way the SDK builds one.

        ``headers`` is a read-only property over ``http_resp.getheaders()``,
        so the response has to carry them — assigning to the exception is
        what the SDK does not allow.
        """
        http_resp = MagicMock()
        http_resp.getheaders.return_value = headers
        return ApiException(status=status, http_resp=http_resp)

    def test_success_records_the_reported_meters(self) -> None:
        response = MagicMock()
        response.status = 200
        response.headers = self._headers("4321", "55")
        with patch("apps.xero.client.RESTClientObject.request", return_value=response):
            self._client()._paced_request("GET", "https://api.xero.com/api.xro/2.0/Invoices?page=2")

        row = VendorCall.objects.get()
        assert row.vendor == VendorCall.Vendor.XERO
        assert row.method == "GET"
        # The query string is stripped: leaving it in would split one endpoint
        # into a distinct value per page and defeat the grouping.
        assert row.endpoint == "/api.xro/2.0/Invoices"
        assert row.day_remaining == 4321
        assert row.minute_remaining == 55
        assert row.status_code == 200

    def test_refused_call_is_recorded_before_it_raises(self) -> None:
        # A 400 spends quota like any other call. Recording only successes
        # would silently under-count a sync that is failing on every page.
        exc = self._refusal(400, self._headers("4000", "50"))
        with (
            patch("apps.xero.client.RESTClientObject.request", side_effect=exc),
            pytest.raises(ApiException),
        ):
            self._client()._paced_request("POST", "https://api.xero.com/api.xro/2.0/Contacts")

        row = VendorCall.objects.get()
        assert row.status_code == 400
        assert row.day_remaining == 4000

    def test_day_limit_429_is_recorded_and_arms_the_gate(self) -> None:
        # The most important row in the table: the call that exhausted the
        # day. It raises by contract, so a recorder placed after the request
        # instead of around it would lose exactly this one.
        exc = self._refusal(
            429,
            {
                "Retry-After": "60",
                "X-Rate-Limit-Problem": "day",
                "X-DayLimit-Remaining": "0",
                "X-MinLimit-Remaining": "60",
            },
        )
        with (
            patch("apps.xero.client.RESTClientObject.request", side_effect=exc),
            patch("apps.xero.client.persist_app_error", return_value=None),
            pytest.raises(ApiException),
        ):
            self._client()._paced_request("GET", "https://api.xero.com/api.xro/2.0/Invoices")

        row = VendorCall.objects.get()
        assert row.status_code == 429
        assert row.day_remaining == 0
        assert quota_floor_breached(100)

    def test_minute_limit_429_records_both_the_refusal_and_the_retry(self) -> None:
        # The retry is a second real call against the quota. Counting it as
        # one would under-report every minute-limited sync.
        refusal = self._refusal(
            429,
            {"Retry-After": "1", "X-Rate-Limit-Problem": "minute", "X-MinLimit-Remaining": "0"},
        )
        retried = MagicMock()
        retried.status = 200
        retried.headers = self._headers("3999", "59")
        with (
            patch("apps.xero.client.RESTClientObject.request", side_effect=[refusal, retried]),
            patch("apps.xero.client.time.sleep"),
        ):
            self._client()._paced_request("GET", "https://api.xero.com/api.xro/2.0/Invoices")

        assert [row.status_code for row in VendorCall.objects.order_by("occurred_at")] == [429, 200]
