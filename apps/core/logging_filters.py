"""Logging filters for noise that is traffic, not failure."""

import logging


class SuppressTracebackFilter(logging.Filter):
    """Keep the log record, drop its traceback.

    Django already answers a bad Host header with 400 and logs it to
    ``django.security.DisallowedHost``. v1 tried to quieten the traceback with
    a middleware whose ``process_exception`` never ran: that hook fires only
    for exceptions raised by the view, and ``DisallowedHost`` comes out of
    ``CommonMiddleware.process_request``, above it. The status code was
    Django's all along; only the traceback was ever the problem, and a filter
    is where a traceback is removed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Strip exception state so the handler prints the message alone."""
        record.exc_info = None
        record.exc_text = None
        return True
