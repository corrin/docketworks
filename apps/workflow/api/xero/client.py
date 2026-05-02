"""Rate-limited Xero REST client.

Subclasses the SDK's RESTClientObject to add:
- Minimum 1s sleep between API calls
- Threshold-based quota logging with periodic summaries
- 429 handling: log + sleep for minute limits, raise for day limits
- Disables urllib3's silent Retry-After sleeping
"""

import logging
import time

import urllib3.util
from django.core.cache import cache
from xero_python.exceptions import ApiException
from xero_python.rest import RESTClientObject

from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("xero")

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
QUOTA_CACHE_KEY = "xero_quota_snapshot"
QUOTA_CACHE_TIMEOUT_SECONDS = 60 * 60 * 24


def quota_floor_breached(floor: int) -> bool:
    """Return True iff a snapshot reports day_remaining at or below ``floor``.

    Reads the quota snapshot maintained by ``RateLimitedRESTClient`` after every
    Xero API call. A missing snapshot or a missing ``day_remaining`` value
    returns False — automated callers fall through and let the next response
    populate the cache.
    """
    snapshot = cache.get(QUOTA_CACHE_KEY)
    if not snapshot:
        return False
    day_remaining = snapshot.get("day_remaining")
    if day_remaining is None:
        return False
    return day_remaining <= floor


class RateLimitedRESTClient(RESTClientObject):
    def __init__(self, configuration, pools_size=4, maxsize=None):
        super().__init__(configuration, pools_size=pools_size, maxsize=maxsize)
        self.pool_manager.connection_pool_kw["retries"] = urllib3.util.Retry(
            0, respect_retry_after_header=False
        )
        self._last_call_time = 0.0
        self._summary_started_at = time.time()
        self._request_count = 0
        self._low_water_minute_remaining = None
        self._low_water_day_remaining = None
        self._minute_warning_band = None
        self._day_warning_band = None
        self._rate_limit_hits = 0

    def request(
        self,
        method,
        url,
        query_params=None,
        headers=None,
        body=None,
        post_params=None,
        _preload_content=True,
        _request_timeout=None,
    ):
        # Enforce minimum sleep between calls
        elapsed = time.time() - self._last_call_time
        if elapsed < MINIMUM_SLEEP:
            time.sleep(MINIMUM_SLEEP - elapsed)

        try:
            r = super().request(
                method,
                url,
                query_params=query_params,
                headers=headers,
                body=body,
                post_params=post_params,
                _preload_content=_preload_content,
                _request_timeout=_request_timeout,
            )
            self._last_call_time = time.time()
            self._log_quota(r)
            return r
        except ApiException as exc:
            self._last_call_time = time.time()
            if exc.status != 429:
                raise
            self._handle_rate_limit(exc)
            # Retry once after sleeping (only for minute limits — day limits raise above)
            return super().request(
                method,
                url,
                query_params=query_params,
                headers=headers,
                body=body,
                post_params=post_params,
                _preload_content=_preload_content,
                _request_timeout=_request_timeout,
            )

    def _log_quota(self, response):
        """Log quota state without spamming the hot path."""
        resp_headers = None
        if hasattr(response, "getheaders"):
            resp_headers = response.getheaders()
        elif hasattr(response, "urllib3_response"):
            resp_headers = response.urllib3_response.headers

        if not resp_headers:
            return

        day_remaining = resp_headers.get("X-DayLimit-Remaining")
        min_remaining = resp_headers.get("X-MinLimit-Remaining")
        self._record_quota(day_remaining, min_remaining)

    def _handle_rate_limit(self, exc):
        """Handle a 429 rate limit response."""
        resp_headers = {}
        if hasattr(exc, "headers") and exc.headers:
            resp_headers = exc.headers

        retry_after = int(resp_headers.get("Retry-After", 60))
        limit_type = resp_headers.get("X-Rate-Limit-Problem", "unknown")
        day_remaining = resp_headers.get("X-DayLimit-Remaining", "?")
        min_remaining = resp_headers.get("X-MinLimit-Remaining", "?")
        self._rate_limit_hits += 1

        logger.warning(
            f"Xero rate limit hit: {limit_type} limit. "
            f"Retry-After: {retry_after}s. "
            f"Day remaining: {day_remaining}. "
            f"Minute remaining: {min_remaining}."
        )

        # 429 responses carry the same quota headers as 2xx responses — write
        # them to the snapshot so quota_floor_breached() can short-circuit
        # subsequent automated calls. Without this, the snapshot only updates
        # on success and the gate stays unarmed precisely when it's needed.
        self._store_quota_snapshot(
            self._parse_int(day_remaining), self._parse_int(min_remaining)
        )

        if limit_type == "day":
            persist_app_error(exc)
            raise exc

        logger.info(f"Sleeping {retry_after}s for {limit_type} rate limit...")
        time.sleep(retry_after)

    def _record_quota(self, day_remaining, min_remaining):
        self._request_count += 1
        day_value = self._parse_int(day_remaining)
        minute_value = self._parse_int(min_remaining)
        self._store_quota_snapshot(day_value, minute_value)

        if day_value is not None:
            if (
                self._low_water_day_remaining is None
                or day_value < self._low_water_day_remaining
            ):
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

    def _maybe_log_threshold_warning(self, quota_name, remaining, thresholds):
        warning_band = next((value for value in thresholds if remaining <= value), None)
        band_attr = f"_{quota_name}_warning_band"
        last_band = getattr(self, band_attr)

        if warning_band is None:
            if last_band is not None and remaining > last_band:
                setattr(self, band_attr, None)
            return

        if last_band == warning_band:
            return

        logger.warning("Xero %s quota low: remaining=%s", quota_name, remaining)
        setattr(self, band_attr, warning_band)

    def _log_summary(self, now):
        window_seconds = max(int(now - self._summary_started_at), 1)
        logger.info(
            "Xero traffic summary: requests=%s window=%ss minute_quota_low=%s day_quota_low=%s 429s=%s",
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
    def _parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _store_quota_snapshot(day_remaining, minute_remaining):
        cache.set(
            QUOTA_CACHE_KEY,
            {
                "timestamp": time.time(),
                "day_remaining": day_remaining,
                "minute_remaining": minute_remaining,
            },
            timeout=QUOTA_CACHE_TIMEOUT_SECONDS,
        )
