"""The typed SDK boundary for Xero Payroll NZ.

Two jobs, one home. First, compatibility fixes for nullable fields: the
generated SDK marks fields required even though Xero legitimately returns
them as null.  v1 patched these setters once when payroll support was
imported; keep that proven boundary here so every payroll call can use typed
responses.

Second, building the payroll client and resolving the connected tenant
(``payroll_api`` / ``connected_tenant``).  payroll_push and payroll_leave each
carried a private copy of both, differing only in error text — the sibling
shape ADR 0039 exists to prevent, and the reason a posting run could verify
the dispatched tenant once and then re-resolve a different one mid-run.
"""

from xero_python.payrollnz import (
    Employee,
    Employment,
    PayrollNzApi,
    SalaryAndWage,
    TimesheetLine,
)

from apps.xero.auth import get_api_client, get_tenant_id


def payroll_api() -> PayrollNzApi:
    """Build the Payroll NZ client (the tenant travels per call, not in the client)."""
    return PayrollNzApi(get_api_client())


def connected_tenant() -> str:
    """Return the connected tenant id, refusing an unconfigured install.

    Fable: This reads the cross-process cache in ``constants.tenant_cache``,
    which can answer with the PREVIOUS tenant for up to five minutes after an
    organisation swap. It is therefore for resolving a tenant ONCE at a
    boundary (a provider method, a dispatch check) — inside a run the resolved
    id is threaded as an argument, never re-read from here (ADR 0024).
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("No Xero tenant ID configured for payroll")
    return str(tenant_id)


_NULLABLE_RESPONSE_FIELDS = (
    (Employee, "date_of_birth"),
    (SalaryAndWage, "annual_salary"),
    (SalaryAndWage, "status"),
    (Employment, "engagement_type"),
    (TimesheetLine, "date"),
    (TimesheetLine, "earnings_rate_id"),
    (TimesheetLine, "number_of_units"),
)


def _allow_none(model: type, field: str) -> None:
    descriptor = getattr(model, field, None)
    if not isinstance(descriptor, property):
        raise TypeError(
            f"{model.__name__}.{field} is not a property in this xero-python build; "
            "re-check the payroll SDK compatibility patch."
        )
    if getattr(descriptor.fset, "_docketworks_allows_none", False):
        return

    private_name = f"_{field}"

    def setter(instance: object, value: object) -> None:
        object.__setattr__(instance, private_name, value)

    setter._docketworks_allows_none = True  # type: ignore[attr-defined]
    setattr(model, field, descriptor.setter(setter))


for _model, _field in _NULLABLE_RESPONSE_FIELDS:
    _allow_none(_model, _field)
