"""Compatibility fixes for nullable fields in Xero Payroll NZ responses.

The generated SDK marks fields required even though Xero legitimately returns
them as null.  v1 patched these setters once when payroll support was imported;
keep that proven boundary here so every payroll call can use typed responses.
"""

from xero_python.payrollnz import Employee, Employment, SalaryAndWage, TimesheetLine

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
