"""One paid call answers "which tenant, and how much day quota is left".

Business case: an unattended E2E run that starts with too little Xero quota
fails half an hour in, when the suite's first refused call lands. Spending one
call up front to read the quota is what makes the refusal arrive before the
half hour rather than after it.
"""

from collections.abc import Iterator
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest
from xero_python.accounting.models import Organisation, Organisations

from apps.xero.quota import XeroQuotaReading, XeroQuotaUnreportedError, read_day_quota

TENANT = "tenant-123"


class _FakeAccountingApi:
    """Answers get_organisations with the headers a tenant-scoped call carries."""

    headers: ClassVar[dict[str, str]] = {}
    calls: ClassVar[list[dict[str, object]]] = []

    def __init__(self, api_client: object) -> None:
        self.api_client = api_client

    def get_organisations(
        self, xero_tenant_id: str, *, _return_http_data_only: bool = True
    ) -> tuple[Organisations, int, dict[str, str]]:
        _FakeAccountingApi.calls.append(
            {"tenant": xero_tenant_id, "data_only": _return_http_data_only}
        )
        body = Organisations(organisations=[Organisation(name="Demo Company")])
        return body, 200, dict(_FakeAccountingApi.headers)


@pytest.fixture(autouse=True)
def _fake_sdk() -> Iterator[None]:
    _FakeAccountingApi.headers = {
        "X-DayLimit-Remaining": "843",
        "X-MinLimit-Remaining": "58",
        "X-AppMinLimit-Remaining": "9990",
    }
    _FakeAccountingApi.calls = []
    with (
        patch("apps.xero.quota.AccountingApi", _FakeAccountingApi),
        patch("apps.xero.quota.get_api_client", return_value=MagicMock()),
        patch("apps.xero.quota.get_tenant_id", return_value=TENANT),
    ):
        yield


def test_reading_names_the_tenant_and_both_remaining_counts() -> None:
    reading = read_day_quota()

    assert reading == XeroQuotaReading(
        organisation_name="Demo Company", day_remaining=843, minute_remaining=58
    )


def test_reading_asks_the_connected_tenant_for_the_headers_not_just_the_body() -> None:
    # The SDK discards headers by default; a refactor that dropped the flag
    # would still get a body and an organisation name, and no quota at all.
    read_day_quota()

    assert _FakeAccountingApi.calls == [{"tenant": TENANT, "data_only": False}]


def test_missing_day_header_is_refused_not_read_as_zero_or_unknown() -> None:
    # A tenant-scoped 200 always carries the header; its absence means the
    # call did not reach the tenant API, and a gate must not guess from that.
    del _FakeAccountingApi.headers["X-DayLimit-Remaining"]

    with pytest.raises(XeroQuotaUnreportedError, match="X-DayLimit-Remaining"):
        read_day_quota()
