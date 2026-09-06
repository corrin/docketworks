"""Rate-limited Xero REST client.

Subclasses the SDK's RESTClientObject to add:
- Minimum 1s sleep between API calls
- Threshold-based quota logging with periodic summaries
- 429 handling: log + sleep for minute limits, raise for day limits
- Disables urllib3's silent Retry-After sleeping
"""

import logging
import threading
import time
from datetime import timedelta
from typing import Any

import urllib3.util
from urllib3 import HTTPResponse
from xero_python.api_client.configuration import Configuration
from xero_python.exceptions import ApiException
from xero_python.rest import RESTClientObject, RESTResponse

from apps.core.errors import persist_app_error

logger = logging.getLogger(__name__)

MINIMUM_SLEEP = 1  # seconds between API calls
SUMMARY_INTERVAL_SECONDS = 300
MINUTE_WARNING_THRESHOLDS = (10, 5, 1)
DAY_WARNING_THRESHOLDS = (
    4000,
    3000,
    2000,
    1000,
    750,
    500,
    300,
    200,
    100,
    50,
    10,
)
# Xero's day quota is a rolling 24h window — old calls age out continuously.
# A snapshot saying day_remaining <= floor from N hours ago is stale: the
# rolling window has freed roughly (N/24) * 5000 calls since it was written.
# Treat snapshots older than this as unknown so the next call probes Xero
# fresh; without this, one 429 pins the gate closed in this process for the
# remaining 23h+ of cache TTL.
QUOTA_STALE_AFTER_SECONDS = 30 * 60


class XeroQuotaFloorReached(Exception):  # noqa: N818 -- state signal, not a defect; "Error" would misname it
    """The day quota is at or below CompanyDefaults.xero_automated_day_floor.

    An automated Xero call cannot proceed. Callers must treat this as an
    *aborted* operation, not a successful no-op — sync status is "aborted",
    not "success", and last-sync timestamps must NOT advance. Distinct from
    defects: do not
    ``persist_app_error`` on this; at the floor it would generate 24+
    rows/day of expected operational signal.
    """


class XeroSyncDisabled(Exception):  # noqa: N818 -- state signal, not a defect; "Error" would misname it
    """``CompanyDefaults.enable_xero_sync`` is False, so no sync may run.

    Sits beside ``XeroQuotaFloorReached`` because it is the same kind of
    signal: an operational refusal every caller must treat as an *aborted*
    run, never a successful empty one. The sync engine raises it; callers
    report it (the command as a ``CommandError``, the worker as an
    ``aborted`` marker) instead of re-reading the gate for themselves.
    """


class XeroSyncLockLost(Exception):  # noqa: N818 -- state signal, not a defect; "Error" would misname it
    """Another run owns the sync lock, so this one must stop writing.

    Raised when a lease renewal finds the key held by someone else: the run
    paused past LOCK_TIMEOUT, a successor acquired the lock, and continuing
    would be the concurrent sync the lock exists to prevent. Same family as
    the two above — an aborted run, not a defect and not a success.
    """


def quota_floor_breached(floor: int) -> bool:
    """Report whether Xero's freshest day-quota reading is at or below ``floor``.

    Reads the newest recorded Xero call inside ``QUOTA_STALE_AFTER_SECONDS``.
    Returns False when there is no such reading — no call yet, or responses
    that carried no quota header — so an unknown quota never gates.

    The reading is not scoped to the active ``XeroApp``, and a credential swap
    therefore leaves at most one aged reading from the previous app in view.
    An app foreign key on the log was rejected: ADR 0055 forbids a business
    key from platform to an integration adapter model. The exposure is bounded
    instead — the newest row wins, so the first call under new credentials
    supersedes it, and the staleness window clears it regardless.
    """
    # Local import: client.py is imported at app boot, models may not be ready.
    from apps.platform.observability.models import VendorCall  # noqa: PLC0415
    from apps.platform.observability.queries import latest_day_remaining  # noqa: PLC0415

    remaining = latest_day_remaining(
        vendor=VendorCall.Vendor.XERO,
        not_older_than=timedelta(seconds=QUOTA_STALE_AFTER_SECONDS),
    )
    if remaining is None:
        return False
    return remaining <= floor


class RateLimitedRESTClient(RESTClientObject):
    """RESTClientObject with pacing, quota tracking and 429 handling (see module docstring)."""

    def __init__(  # noqa: D107 -- narrows the SDK constructor; class docstring covers it
        self,
        configuration: Configuration,
        pools_size: int = 4,
        maxsize: int | None = None,
    ) -> None:
        super().__init__(configuration, pools_size=pools_size, maxsize=maxsize)
        self.pool_manager.connection_pool_kw["retries"] = urllib3.util.Retry(
            0, respect_retry_after_header=False
        )
        # One in-flight Xero call per client: the 1s minimum interval is a
        # per-app limit, and unsynchronised threads could all pass the elapsed
        # check together.
        self._pacing_lock = threading.Lock()
        self._last_call_time = 0.0
        self._summary_started_at = time.time()
        self._request_count = 0
        self._low_water_minute_remaining: int | None = None
        self._low_water_day_remaining: int | None = None
        self._minute_warning_band: int | None = None
        self._day_warning_band: int | None = None
        self._rate_limit_hits = 0

    def request(  # noqa: PLR0913, PLR0917 -- the SDK base-class signature; not ours to shrink
        self,
        method: str,
        url: str,
        query_params: Any = None,
        headers: Any = None,
        body: Any = None,
        post_params: Any = None,
        _preload_content: bool = True,
        _request_timeout: Any = None,
    ) -> RESTResponse | HTTPResponse:
        """Rate-paced ``RESTClientObject.request``; retries once on minute-limit 429s."""
        with self._pacing_lock:
            return self._paced_request(
                method,
                url,
                query_params=query_params,
                headers=headers,
                body=body,
                post_params=post_params,
                _preload_content=_preload_content,
                _request_timeout=_request_timeout,
            )

    def _paced_request(  # noqa: PLR0913, PLR0917 -- mirrors the SDK signature it forwards
        self,
        method: str,
        url: str,
        query_params: Any = None,
        headers: Any = None,
        body: Any = None,
        post_params: Any = None,
        _preload_content: bool = True,
        _request_timeout: Any = None,
    ) -> RESTResponse | HTTPResponse:
        # Enforce minimum sleep between calls
        elapsed = time.time() - self._last_call_time
        if elapsed < MINIMUM_SLEEP:
            time.sleep(MINIMUM_SLEEP - elapsed)

        def attempt() -> RESTResponse | HTTPResponse:
            """One request to Xero, timed and recorded whatever the outcome.

            The two attempts share this rather than repeating the SDK call:
            when they were written out twice, the retry's failure path was the
            copy that lost its recording, which is the drift one implementation
            prevents (ADR 0039). ``RESTClientObject.request(self, ...)`` and not
            ``super()`` — zero-argument ``super()`` reads the first argument of
            the frame it runs in, and a nested function does not have one.
            """
            started = time.perf_counter()
            try:
                response = RESTClientObject.request(
                    self,
                    method,
                    url,
                    query_params=query_params,
                    headers=headers,
                    body=body,
                    post_params=post_params,
                    _preload_content=_preload_content,
                    _request_timeout=_request_timeout,
                )
            # A refused call has already spent its share of the quota, and its
            # response carries the headers saying how much is left. Recorded
            # here, then re-raised untouched: recording only successes would
            # blind the log at exactly the moment the budget runs out.
            except ApiException as exc:
                self._last_call_time = time.time()
                self._record_call(method, url, started, exc.status, exc.headers or {})
                raise
            self._last_call_time = time.time()
            self._record_call(method, url, started, response.status, self._headers_of(response))
            return response

        try:
            r = attempt()
        # deliberate-swallow: non-429 re-raises immediately; a day-limit 429
        # re-raises inside _handle_rate_limit; only the minute-limit 429 is
        # absorbed, by sleeping Retry-After and retrying once — the absorb IS
        # the rate-limit contract
        except ApiException as exc:
            if exc.status != 429:
                raise
            self._handle_rate_limit(exc)
            # Retry once after sleeping (only for minute limits — day limits
            # raise above). v1 skipped pacing and quota bookkeeping on the
            # retried response — exactly the calls made under rate pressure,
            # when the record matters most.
            retried = attempt()
            self._log_quota(retried)
            return retried
        else:
            self._log_quota(r)
            return r

    @staticmethod
    def _headers_of(response: RESTResponse | HTTPResponse) -> dict[str, str]:
        """Read response headers from either shape the SDK hands back."""
        # _preload_content=False (token refresh) hands back the raw urllib3
        # response; the SDK wrapper carries the same headers via getheaders().
        if isinstance(response, RESTResponse):
            return response.getheaders()
        return dict(response.headers)

    def _record_call(
        self,
        method: str,
        url: str,
        started: float,
        status: int | None,
        resp_headers: dict[str, str],
    ) -> None:
        """Write the observability row for one Xero request.

        ``status`` is optional because the SDK's ``ApiException.status`` is:
        it derives from the response object, which a transport-level failure
        may not have. An unknown status is worth a row without one — the call
        still spent quota — rather than no row at all.
        """
        # Local import: client.py is imported at app boot, models may not be ready.
        from apps.platform.observability.models import VendorCall  # noqa: PLC0415
        from apps.platform.observability.recording import (  # noqa: PLC0415
            VendorCallRecord,
            record_vendor_call,
        )

        record_vendor_call(
            VendorCallRecord(
                vendor=VendorCall.Vendor.XERO,
                method=method,
                url=url,
                duration_ms=int((time.perf_counter() - started) * 1000),
                status_code=status,
                day_remaining=self._parse_int(resp_headers.get("X-DayLimit-Remaining")),
                minute_remaining=self._parse_int(resp_headers.get("X-MinLimit-Remaining")),
            )
        )

    def _log_quota(self, response: RESTResponse | HTTPResponse) -> None:
        """Log quota state without spamming the hot path."""
        resp_headers = self._headers_of(response)
        if not resp_headers:
            return

        day_remaining = resp_headers.get("X-DayLimit-Remaining")
        min_remaining = resp_headers.get("X-MinLimit-Remaining")
        self._record_quota(day_remaining, min_remaining)

    def _handle_rate_limit(self, exc: ApiException) -> None:
        """Handle a 429 rate limit response."""
        resp_headers: dict[str, str] = exc.headers or {}

        # RFC 7231 also permits an HTTP-date here; a non-numeric value falls
        # back to 60s rather than raising out of the 429 handler. Clamped:
        # Xero's minute-limit waits are <=60s, so a huge value is bad data,
        # not an instruction to block a worker thread for hours.
        retry_after = min(self._parse_int(resp_headers.get("Retry-After")) or 60, 300)
        limit_type = resp_headers.get("X-Rate-Limit-Problem", "unknown")
        day_remaining = resp_headers.get("X-DayLimit-Remaining", "?")
        min_remaining = resp_headers.get("X-MinLimit-Remaining", "?")
        self._rate_limit_hits += 1

        logger.warning(
            "Xero rate limit hit: %s limit. Retry-After: %ss."
            " Day remaining: %s. Minute remaining: %s.",
            limit_type,
            retry_after,
            day_remaining,
            min_remaining,
        )

        if limit_type == "day":
            persist_app_error(exc)
            raise exc

        logger.info("Sleeping %ss for %s rate limit...", retry_after, limit_type)
        time.sleep(retry_after)

    def _record_quota(self, day_remaining: str | None, min_remaining: str | None) -> None:
        self._request_count += 1
        day_value = self._parse_int(day_remaining)
        minute_value = self._parse_int(min_remaining)

        if day_value is not None:
            if self._low_water_day_remaining is None or day_value < self._low_water_day_remaining:
                self._low_water_day_remaining = day_value
            self._maybe_log_threshold_warning(
                quota_name="day",
                remaining=day_value,
                thresholds=DAY_WARNING_THRESHOLDS,
            )

        if minute_value is not None:
            if (
                self._low_water_minute_remaining is None
                or minute_value < self._low_water_minute_remaining
            ):
                self._low_water_minute_remaining = minute_value
            self._maybe_log_threshold_warning(
                quota_name="minute",
                remaining=minute_value,
                thresholds=MINUTE_WARNING_THRESHOLDS,
            )

        now = time.time()
        if now - self._summary_started_at >= SUMMARY_INTERVAL_SECONDS:
            self._log_summary(now)

    def _maybe_log_threshold_warning(
        self, quota_name: str, remaining: int, thresholds: tuple[int, ...]
    ) -> None:
        warning_band = next((value for value in thresholds if remaining <= value), None)
        band_attr = f"_{quota_name}_warning_band"
        last_band: int | None = getattr(self, band_attr)

        if warning_band is None:
            if last_band is not None and remaining > last_band:
                setattr(self, band_attr, None)
            return

        if last_band == warning_band:
            return

        logger.warning("Xero %s quota low: remaining=%s", quota_name, remaining)
        setattr(self, band_attr, warning_band)

    def _log_summary(self, now: float) -> None:
        window_seconds = max(int(now - self._summary_started_at), 1)
        logger.info(
            "Xero traffic summary: requests=%s window=%ss minute_quota_low=%s"
            " day_quota_low=%s 429s=%s",
            self._request_count,
            window_seconds,
            self._low_water_minute_remaining,
            self._low_water_day_remaining,
            self._rate_limit_hits,
        )
        self._summary_started_at = now
        self._request_count = 0
        self._low_water_minute_remaining = None
        self._low_water_day_remaining = None
        self._rate_limit_hits = 0

    @staticmethod
    def _parse_int(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        # deliberate-swallow: quota headers are optional and sometimes malformed; None means
        # "no new reading" and the stored snapshot is left alone
        except ValueError:
            return None
