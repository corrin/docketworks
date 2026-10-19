"""Every default the fake fills in is a value a recording shows Xero filling in (ADR 0060)."""

import pytest

from apps.xero.fake import defaults
from apps.xero.fake.minting import as_list, as_mapping
from apps.xero.fake.seed import recorded_body
from apps.xero.fake.wire import Json


@pytest.mark.parametrize(
    ("recording", "key", "block"),
    [
        ("contact", "Contacts", defaults.CONTACT),
        ("invoice", "Invoices", defaults.INVOICE),
        ("quote", "Quotes", defaults.QUOTE),
        ("purchase_order", "PurchaseOrders", defaults.PURCHASE_ORDER),
    ],
)
def test_defaults_are_keys_xero_returns(recording: str, key: str, block: dict[str, Json]) -> None:
    element = as_mapping(as_list(recorded_body(recording)[key], key)[0], key)
    missing = sorted(set(block) - set(element))
    assert not missing, f"{recording}: the fake fills in {missing}, which Xero did not return"


def test_line_item_defaults_are_keys_xero_returns() -> None:
    invoice = as_mapping(as_list(recorded_body("invoice")["Invoices"], "Invoices")[0], "Invoices")
    line = as_mapping(as_list(invoice["LineItems"], "LineItems")[0], "LineItems")
    assert set(defaults.LINE_ITEM) <= set(line)


@pytest.mark.parametrize(
    ("recording", "key", "block"),
    [
        ("employee_create", "employee", defaults.EMPLOYEE),
        ("salary_and_wage_create", "salaryAndWages", defaults.SALARY_AND_WAGE),
        ("employee_tax_update", "employeeTax", defaults.EMPLOYEE_TAX),
        ("leave_setup_create", "leaveSetup", defaults.LEAVE_SETUP),
        ("employee_leave_type_create", "leaveType", defaults.EMPLOYEE_LEAVE_TYPE),
    ],
)
def test_payroll_defaults_are_keys_xero_returns(
    recording: str, key: str, block: dict[str, Json]
) -> None:
    element = as_mapping(recorded_body(recording)[key], key)
    missing = sorted(set(block) - set(element))
    assert not missing, f"{recording}: the fake fills in {missing}, which Xero did not return"


def test_payroll_nested_defaults_are_keys_xero_returns() -> None:
    employee = as_mapping(recorded_body("employee_create")["employee"], "employee")
    assert set(defaults.EMPLOYEE_ADDRESS) <= set(as_mapping(employee["address"], "address"))
    method = as_mapping(recorded_body("payment_method_create")["paymentMethod"], "paymentMethod")
    account = as_mapping(as_list(method["bankAccounts"], "bankAccounts")[0], "bankAccounts")
    assert set(defaults.BANK_ACCOUNT) <= set(account)
    assigned = as_list(recorded_body("employee_leave_types")["leaveTypes"], "leaveTypes")
    for rule in defaults.LEAVE_SETUP_ASSIGNS.values():
        assert set(rule) <= set(as_mapping(assigned[0], "leaveTypes"))
