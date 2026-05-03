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


class AlreadyLoggedException(Exception):
    """Exception that indicates the wrapped exception was already persisted."""

    def __init__(
        self,
        original_exception: Exception,
        app_error_id: Optional[str] = None,
    ) -> None:
        self.original = original_exception
        self.app_error_id = app_error_id
        super().__init__(str(original_exception))


class XeroQuotaFloorReached(Exception):
    """Raised when an automated Xero call cannot proceed because the
    day-quota is at or below ``settings.XERO_AUTOMATED_DAY_FLOOR``.

    Callers must treat this as an *aborted* operation, not a successful
    no-op — sync status is "aborted", not "success", and last-sync
    timestamps must NOT advance. Distinct from defects: do not
    ``persist_app_error`` on this; at the floor it would generate 24+
    rows/day of expected operational signal.
    """
