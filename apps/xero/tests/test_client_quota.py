"""Quota snapshot writes and the automated-call day-quota floor.

Business case: automated Xero jobs must stop only when a fresh quota snapshot
proves they would burn reserved API calls. False positives stop useful sync;
false negatives burn quota needed for user-triggered invoices.
"""

import contextlib
from datetime import timedelta
from typing import Unpack
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from django.utils import timezone as dj_timezone

from apps.xero.client import RateLimitedRESTClient, quota_floor_breached
from apps.xero.models import XeroApp

from .conftest import XeroAppOverrides, make_xero_app


def _active_app(**overrides: Unpack[XeroAppOverrides]) -> XeroApp:
    overrides.setdefault("is_active", True)
    return make_xero_app(**overrides)


def _set_quota(
    day_remaining: int, minute_remaining: int = 60, snapshot_age_seconds: int = 0
) -> None:
    """Set the active XeroApp's snapshot, creating an active row if needed."""
    snapshot_at = dj_timezone.now() - timedelta(seconds=snapshot_age_seconds)
    if XeroApp.objects.filter(is_active=True).exists():
        XeroApp.objects.filter(is_active=True).update(
            day_remaining=day_remaining,
            minute_remaining=minute_remaining,
            snapshot_at=snapshot_at,
        )
    else:
        _active_app(
            day_remaining=day_remaining,
            minute_remaining=minute_remaining,
            snapshot_at=snapshot_at,
        )


def _bare_client(app_id: UUID | None) -> RateLimitedRESTClient:
    """A client bound to app_id without building a urllib3 pool.

    ``__new__`` side-steps the real ``__init__`` — these tests exercise the
    quota-write logic only, and a real pool needs a live Configuration.
    """
    client = RateLimitedRESTClient.__new__(RateLimitedRESTClient)
    client.app_id = app_id
    client._rate_limit_hits = 0
    return client


@pytest.mark.django_db
class TestQuotaFloorBreached:
    def test_no_active_row_returns_false(self) -> None:
        # Nothing to gate against — fall through and let the call go.
        assert not quota_floor_breached(100)

    def test_missing_snapshot_returns_false(self) -> None:
        # Active row exists but no API call has happened yet.
        _active_app()
        assert not quota_floor_breached(100)

    def test_day_remaining_above_floor_returns_false(self) -> None:
        _set_quota(day_remaining=200)
        assert not quota_floor_breached(100)

    def test_day_remaining_at_floor_returns_true(self) -> None:
        _set_quota(day_remaining=100)
        assert quota_floor_breached(100)

    def test_day_remaining_below_floor_returns_true(self) -> None:
        _set_quota(day_remaining=50)
        assert quota_floor_breached(100)

    def test_day_remaining_none_returns_false(self) -> None:
        # First-call response sometimes omits day_remaining.
        _active_app(
            day_remaining=None,
            minute_remaining=60,
            snapshot_at=dj_timezone.now(),
        )
        assert not quota_floor_breached(100)

    def test_stale_snapshot_returns_false(self) -> None:
        # Snapshot older than the staleness window — let the next call
        # probe Xero fresh; the rolling 24h window has freed quota since.
        _set_quota(day_remaining=10, snapshot_age_seconds=60 * 60)
        assert not quota_floor_breached(100)


@pytest.mark.django_db
class TestRateLimit429WritesToBoundRow:
    """Without this, the snapshot only updates on 2xx — and the gate stays
    unarmed precisely when it's most needed (right after Xero just told us
    the day quota is exhausted). Quota writes target the row whose
    credentials made the call (via app_id), not the active row at the
    moment of write.
    """

    def _run_handle_rate_limit(
        self,
        *,
        app_id: UUID,
        day_remaining: int,
        minute_remaining: int,
        problem: str,
    ) -> None:
        # A minimal fake exception matching what the SDK passes in.
        exc = MagicMock()
        exc.headers = {
            "Retry-After": "60",
            "X-Rate-Limit-Problem": problem,
            "X-DayLimit-Remaining": str(day_remaining),
            "X-MinLimit-Remaining": str(minute_remaining),
        }

        client = _bare_client(app_id)
        # The day-limit branch re-raises by contract; that path is not under
        # test here, so swallow it.
        with contextlib.suppress(Exception):
            client._handle_rate_limit(exc)

    def test_minute_limit_429_writes_snapshot_to_bound_row(self) -> None:
        row = _active_app()
        with patch("apps.xero.client.time.sleep"):
            self._run_handle_rate_limit(
                app_id=row.id,
                day_remaining=42,
                minute_remaining=0,
                problem="minute",
            )
        row.refresh_from_db()
        assert row.day_remaining == 42
        assert row.minute_remaining == 0
        assert row.snapshot_at is not None

    def test_day_limit_429_writes_snapshot_and_last_429_at(self) -> None:
        row = _active_app()
        with patch("apps.xero.client.persist_app_error", return_value=None):
            self._run_handle_rate_limit(
                app_id=row.id,
                day_remaining=0,
                minute_remaining=60,
                problem="day",
            )
        row.refresh_from_db()
        assert row.day_remaining == 0
        assert row.last_429_at is not None

    def test_writes_to_bound_row_not_active_row(self) -> None:
        # Construct a client bound to row B's id while row A is currently
        # active. The 429 must update B, not A.
        a = _active_app(client_id="c-a", label="A")
        b = make_xero_app(label="B", client_id="c-b", is_active=False)
        with patch("apps.xero.client.time.sleep"):
            self._run_handle_rate_limit(
                app_id=b.id,
                day_remaining=99,
                minute_remaining=5,
                problem="minute",
            )
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.day_remaining is None
        assert b.day_remaining == 99


@pytest.mark.django_db
class TestStoreQuotaSnapshotWritesToBoundRow:
    """The 2xx path: _store_quota_snapshot updates the bound row's quota
    fields directly.

    Business case: the quota badge and automated-sync gate must track the
    Xero app whose credentials made the call, otherwise an app swap can show
    healthy quota while the active worker is actually exhausted.
    """

    def test_2xx_updates_bound_row(self) -> None:
        row = _active_app()
        _bare_client(row.id)._store_quota_snapshot(4321, 55)

        row.refresh_from_db()
        assert row.day_remaining == 4321
        assert row.minute_remaining == 55
        assert row.snapshot_at is not None

    def test_no_app_id_silently_skips(self) -> None:
        # Pre-existing row stays untouched when client has no app_id.
        row = _active_app()
        _bare_client(None)._store_quota_snapshot(1234, 10)

        row.refresh_from_db()
        assert row.day_remaining is None

    def test_both_none_leaves_stored_values_untouched(self) -> None:
        # Token refreshes hit identity.xero.com, which returns no quota
        # headers — the heartbeat runs every 5 min, so a clobber here means
        # the badge reads "—" almost all the time.
        row = _active_app()
        before = dj_timezone.now() - timedelta(hours=1)
        XeroApp.objects.filter(id=row.id).update(
            day_remaining=500, minute_remaining=58, snapshot_at=before
        )
        _bare_client(row.id)._store_quota_snapshot(None, None)

        row.refresh_from_db()
        assert row.day_remaining == 500
        assert row.minute_remaining == 58
        assert row.snapshot_at == before

    def test_partial_reading_updates_only_present_field(self) -> None:
        # A minute-limit 429 carries X-MinLimit-Remaining but not the day
        # header — record the minute count without wiping the day count.
        row = _active_app()
        XeroApp.objects.filter(id=row.id).update(day_remaining=500, minute_remaining=58)
        _bare_client(row.id)._store_quota_snapshot(None, 0)

        row.refresh_from_db()
        assert row.day_remaining == 500
        assert row.minute_remaining == 0
        assert row.snapshot_at is not None
