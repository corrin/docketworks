"""A fake run leaves the record a real one does, and meets the limits a real one meets."""

import logging
from datetime import timedelta

import pytest
from django.utils import timezone
from xero_python.accounting import AccountingApi
from xero_python.exceptions import ApiException

from apps.platform.observability.models import VendorCall
from apps.xero.fake.limits import DAY_LIMIT, MINUTE_LIMIT
from apps.xero.fake.tests.conftest import TENANT

pytestmark = pytest.mark.django_db


def _fill_the_minute(calls: int, *, age: timedelta = timedelta(seconds=0)) -> None:
    VendorCall.objects.bulk_create(
        VendorCall(
            vendor=VendorCall.Vendor.XERO,
            method="GET",
            endpoint="/api.xro/2.0/Organisation",
            occurred_at=timezone.now() - age,
            duration_ms=1,
            status_code=200,
        )
        for _ in range(calls)
    )


def test_a_fake_call_is_recorded_as_a_xero_call_with_moving_meters(
    accounting: AccountingApi,
) -> None:
    accounting.get_organisations(TENANT)
    accounting.get_organisations(TENANT)

    rows = list(VendorCall.objects.order_by("occurred_at"))
    assert [row.vendor for row in rows] == ["xero", "xero"]
    assert rows[0].endpoint == "/api.xro/2.0/Organisation"
    assert (rows[0].day_remaining, rows[1].day_remaining) == (DAY_LIMIT - 1, DAY_LIMIT - 2)
    assert (rows[0].minute_remaining, rows[1].minute_remaining) == (
        MINUTE_LIMIT - 1,
        MINUTE_LIMIT - 2,
    )


def test_a_fake_call_leaves_the_wire_line(
    accounting: AccountingApi, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="apps.xero.wire"):
        accounting.get_organisations(TENANT)
    lines = [r.message for r in caplog.records if r.name == "apps.xero.wire"]
    assert len(lines) == 1
    assert "XERO_WIRE" in lines[0] and "/api.xro/2.0/Organisation" in lines[0]


def test_the_sixty_first_call_in_a_minute_is_xero_s_429(
    accounting: AccountingApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The paced client sleeps Retry-After and retries once; the window is
    # still full, so the retry is refused too and the refusal surfaces.
    slept: list[float] = []
    monkeypatch.setattr("apps.xero.client.time.sleep", slept.append)
    _fill_the_minute(MINUTE_LIMIT)

    with pytest.raises(ApiException) as refused:
        accounting.get_organisations(TENANT)

    assert refused.value.status == 429
    headers = refused.value.headers
    assert headers is not None
    assert headers["X-Rate-Limit-Problem"] == "minute"
    assert 1 <= int(headers["Retry-After"]) <= 60
    assert headers["X-MinLimit-Remaining"] == "0"
    assert slept == [int(headers["Retry-After"])]
    # Both attempts spent a call and both are in the record, as Xero's would be.
    assert VendorCall.objects.filter(status_code=429).count() == 2


def test_calls_older_than_the_window_do_not_count(accounting: AccountingApi) -> None:
    _fill_the_minute(MINUTE_LIMIT, age=timedelta(seconds=61))

    accounting.get_organisations(TENANT)

    row = VendorCall.objects.filter(status_code=200).latest("occurred_at")
    assert row.minute_remaining == MINUTE_LIMIT - 1
