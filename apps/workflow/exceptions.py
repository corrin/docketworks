from typing import List, Optional


class XeroValidationError(Exception):
    """Exception raised when a Xero object is missing required fields.

    Args:
        missing_fields: Names of the missing attributes.
        entity: The entity type, such as "invoice".
        xero_id: Identifier for the record in Xero.
    """

    def __init__(
        self, missing_fields: List[str], entity: str, xero_id: Optional[str]
    ) -> None:
        self.missing_fields = missing_fields
        self.entity = entity
        self.xero_id = xero_id
        message = f"Missing fields {missing_fields} for {entity} {xero_id}"
        super().__init__(message)


class XeroQuotaFloorReached(Exception):
    """Raised when an automated Xero call cannot proceed because the
    day-quota is at or below CompanyDefaults.xero_automated_day_floor.

    Callers must treat this as an *aborted* operation, not a successful
    no-op — sync status is "aborted", not "success", and last-sync
    timestamps must NOT advance. Distinct from defects: do not
    ``persist_app_error`` on this; at the floor it would generate 24+
    rows/day of expected operational signal.
    """


class XeroSyncAlreadyRunningError(Exception):
    """Raised by ``XeroSyncService.start_sync`` when another sync is
    already holding the cross-process lock. Callers receive the active
    task_id (so they can include it in a 409/log message) without having
    to inspect the lock themselves.
    """

    def __init__(self, active_task_id: Optional[str]) -> None:
        self.active_task_id = active_task_id
        super().__init__(f"Sync already in progress (task_id={active_task_id})")


class NoValidXeroTokenError(Exception):
    """Raised by ``XeroSyncService.start_sync`` when the lock was
    acquired but no valid Xero token is available — distinct channel
    from "lock held" so callers can react differently (Beat: log error;
    view: HTTP 401)."""
