"""Constants for the Xero sync pipeline.

Lives in its own module so both ``sync_service`` (the dispatcher) and
``sync_worker`` (the Celery task) can import these without creating a
cycle: dispatcher → worker → service-class would otherwise loop.
"""

SYNC_STATUS_KEY = "xero_sync_status"
LOCK_TIMEOUT = 60 * 60 * 4  # 4 hours
