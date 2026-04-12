"""Rate-limited Xero REST client.

Subclasses the SDK's RESTClientObject to add:
- Minimum 1s sleep between API calls
- Quota logging on every response (X-DayLimit-Remaining, X-MinLimit-Remaining)
- 429 handling: log + sleep for minute limits, raise for day limits
- Disables urllib3's silent Retry-After sleeping
"""

import logging
import time

import urllib3.util
from xero_python.exceptions import ApiException
from xero_python.rest import RESTClientObject, RESTResponse

from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("xero")

MINIMUM_SLEEP = 1  # seconds between API calls


class RateLimitedRESTClient(RESTClientObject):
    def __init__(self, configuration, pools_size=4, maxsize=None):
        super().__init__(configuration, pools_size=pools_size, maxsize=maxsize)
        self.pool_manager.connection_pool_kw["retries"] = urllib3.util.Retry(
            0, respect_retry_after_header=False
        )
        self._last_call_time = 0.0

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
        """Log remaining API quota from response headers."""
        resp_headers = None
        if hasattr(response, "getheaders"):
            resp_headers = response.getheaders()
        elif hasattr(response, "urllib3_response"):
            resp_headers = response.urllib3_response.headers

        if not resp_headers:
            return

        day_remaining = resp_headers.get("X-DayLimit-Remaining")
        min_remaining = resp_headers.get("X-MinLimit-Remaining")
        if day_remaining is not None:
            logger.debug(
                f"Xero quota: day={day_remaining}, minute={min_remaining}"
            )

    def _handle_rate_limit(self, exc):
        """Handle a 429 rate limit response."""
        resp_headers = {}
        if hasattr(exc, "headers") and exc.headers:
            resp_headers = exc.headers

        retry_after = int(resp_headers.get("Retry-After", 60))
        limit_type = resp_headers.get("X-Rate-Limit-Problem", "unknown")
        day_remaining = resp_headers.get("X-DayLimit-Remaining", "?")
        min_remaining = resp_headers.get("X-MinLimit-Remaining", "?")

        logger.warning(
            f"Xero rate limit hit: {limit_type} limit. "
            f"Retry-After: {retry_after}s. "
            f"Day remaining: {day_remaining}. "
            f"Minute remaining: {min_remaining}."
        )

        if limit_type == "day":
            persist_app_error(exc)
            raise exc

        logger.info(f"Sleeping {retry_after}s for {limit_type} rate limit...")
        time.sleep(retry_after)
