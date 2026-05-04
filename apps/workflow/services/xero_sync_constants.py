"""Constants for the Xero sync pipeline.

Lives in its own module so both ``xero_sync_service`` (the dispatcher) and
``apps.workflow.tasks`` (the worker) can import these without creating a
cycle: dispatcher → worker → service-class would otherwise loop.
"""

SYNC_STATUS_KEY = "xero_sync_status"
LOCK_TIMEOUT = 60 * 60 * 4  # 4 hours
