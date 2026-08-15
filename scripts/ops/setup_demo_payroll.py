#!/usr/bin/env python
"""Set up employee payroll details for the Xero Demo Company org.

Updates EXISTING Xero employees (Staff rows holding a xero_user_id) with:

- Tax code: M (main employment), ESCT rate 17.5%, a syntactically valid FAKE
  IRD number
- KiwiSaver: active member with 3% employee, 3% employer contributions
- Leave: 160 hours annual leave, 80 hours sick leave per year
- Bank account (pre-validated NZ format, FAKE)

The data is fake by construction and the run is guarded against production
targets. Employee creation itself stays with the Phase 4 payroll-employee
port (apps/timesheet/services/payroll_employee_sync.py); when that lands,
the write helpers here must merge into it rather than remain a sibling.

Usage:
    uv run python -m scripts.ops.setup_demo_payroll            # dry run
    uv run python -m scripts.ops.setup_demo_payroll --execute
"""

import sys
import time

from scripts.bootstrap import setup_django

setup_django()

from xero_python.payrollnz import (  # noqa: E402 -- Django must be configured first
    BankAccount,
    EmployeeLeaveSetup,
    EmployeeTax,
    PaymentMethod,
    PayrollNzApi,
    TaxCode,
)

from apps.accounts.models import Staff  # noqa: E402
from apps.xero.auth import get_api_client, get_tenant_id  # noqa: E402
from apps.xero.operator_guards import (  # noqa: E402
    assert_not_production_target,
    assert_xero_writes_enabled,
)

# Pause between Xero API calls to avoid rate limiting.
API_PAUSE_SECONDS = 3

# Pre-validated NZ bank accounts (ANZ branch 01-0242). Fake but format-valid,
# which is what Xero's bank-account validation requires.
BANK_ACCOUNTS = [
    "01-0242-1588000-000",
    "01-0242-1596000-000",
    "01-0242-1668000-000",
    "01-0242-1676000-000",
    "01-0242-1684000-000",
    "01-0242-1692000-000",
    "01-0242-1748000-000",
    "01-0242-1756000-000",
    "01-0242-1764000-000",
    "01-0242-1772000-000",
]

# NZ IRD check-digit weights (IR "resident withholding tax" spec, as
# implemented by python-stdnum's stdnum.nz.ird). python-stdnum itself is
# deliberately NOT a v2 dependency yet — it arrives with the Phase 4
# payroll-employee port (see apps/timesheet/services/payroll_employee_sync.py)
# — and adding a project dependency for one demo-data script is not justified
# (ADR 0032 recorded reason). Replace this with stdnum when Phase 4 lands.
_IRD_PRIMARY_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)
_IRD_SECONDARY_WEIGHTS = (7, 4, 3, 2, 5, 2, 7, 6)


def _ird_check_digit(base8: str) -> str:
    """Compute the IRD check digit for an 8-digit base ("10" means invalid base)."""
    s = -sum(w * int(n) for w, n in zip(_IRD_PRIMARY_WEIGHTS, base8, strict=True)) % 11
    if s != 10:
        return str(s)
    s = -sum(w * int(n) for w, n in zip(_IRD_SECONDARY_WEIGHTS, base8, strict=True)) % 11
    return str(s)


def generate_ird_number(employee_num: int) -> str:
    """Generate a syntactically valid FAKE NZ IRD number, formatted XX-XXX-XXX."""
    # Base in range 04900000-14999999 produces valid 9-digit IRDs; bases whose
    # check digit computes to "10" are invalid and skipped.
    base = 4900000 + (employee_num * 100)
    while True:
        base_str = str(base).zfill(8)
        check_digit = _ird_check_digit(base_str)
        if check_digit != "10":
            full = base_str + check_digit
            return "-".join([full[:-6], full[-6:-3], full[-3:]])
        base += 1


def get_bank_account(index: int) -> str:
    """Get a pre-validated fake NZ bank account number."""
    return BANK_ACCOUNTS[index % len(BANK_ACCOUNTS)]


def setup_employee_tax(payroll_api: PayrollNzApi, employee_id: str, ird_number: str) -> None:
    """Set employee tax details including KiwiSaver."""
    ird_clean = ird_number.replace("-", "").zfill(9)
    tax = EmployeeTax(
        ird_number=ird_clean,
        tax_code=TaxCode.M,
        esct_rate_percentage=17.5,
        is_eligible_for_kiwi_saver=True,
        kiwi_saver_contributions="MakeContributions",
        kiwi_saver_employee_contribution_rate_percentage=3.0,
        kiwi_saver_employer_contribution_rate_percentage=3.0,
        kiwi_saver_employer_salary_sacrifice_contribution_rate_percentage=0.0,
    )
    payroll_api.update_employee_tax(
        xero_tenant_id=get_tenant_id(),
        employee_id=employee_id,
        employee_tax=tax,
    )
    time.sleep(API_PAUSE_SECONDS)


def setup_employee_leave(payroll_api: PayrollNzApi, employee_id: str) -> None:
    """Set employee leave entitlements."""
    leave_setup = EmployeeLeaveSetup(
        include_holiday_pay=False,
        holiday_pay_opening_balance=0.0,
        annual_leave_opening_balance=160.0,
        sick_leave_to_accrue_annually=80.0,
        sick_leave_maximum_to_accrue=80.0,
        sick_leave_opening_balance=80.0,
    )
    try:
        payroll_api.create_employee_leave_setup(
            xero_tenant_id=get_tenant_id(),
            employee_id=employee_id,
            employee_leave_setup=leave_setup,
        )
    except Exception as e:
        # deliberate-swallow: leave setup is create-only in Xero's API; on a
        # re-run "already setup" is the expected steady state, not a failure.
        if "already setup" not in str(e).lower():
            raise
        print(f"  Leave already set up for employee {employee_id}")
    time.sleep(API_PAUSE_SECONDS)


def setup_employee_bank(payroll_api: PayrollNzApi, employee_id: str, bank_account: str) -> None:
    """Set the employee's wages bank account."""
    parts = bank_account.split("-")
    if len(parts) != 4:
        raise ValueError(f"Invalid bank account format: {bank_account}")

    sort_code = f"{parts[0]}{parts[1]}"
    account_number = f"{parts[0]}{parts[1]}{parts[2]}{parts[3]}"

    bank = BankAccount(
        account_name="Wages",
        account_number=account_number,
        sort_code=sort_code,
        calculation_type="Balance",
    )
    payment = PaymentMethod(
        payment_method="Electronically",
        bank_accounts=[bank],
    )
    payroll_api.create_employee_payment_method(
        xero_tenant_id=get_tenant_id(),
        employee_id=employee_id,
        payment_method=payment,
    )
    time.sleep(API_PAUSE_SECONDS)


def main() -> None:
    execute = "--execute" in sys.argv
    print(f"Mode: {'EXECUTE' if execute else 'DRY RUN'}")

    if execute:
        assert_xero_writes_enabled("setup_demo_payroll")
        assert_not_production_target()

    staff_list = list(Staff.objects.filter(date_left__isnull=True, xero_user_id__isnull=False))
    print(f"Found {len(staff_list)} staff with Xero IDs")

    if not staff_list:
        return

    payroll_api = PayrollNzApi(get_api_client())
    results = {"tax": [0, 0], "leave": [0, 0], "bank": [0, 0]}

    for i, staff in enumerate(staff_list):
        ird = generate_ird_number(i + 1)
        bank = get_bank_account(i + 1)
        print(f"{staff.first_name} {staff.last_name}: IRD={ird} Bank={bank}")

        if not execute:
            continue

        xero_user_id = staff.xero_user_id
        if not xero_user_id:
            raise ValueError(f"Staff {staff.email} matched the filter but has no xero_user_id")

        # Each leg in its own try: one employee's refusal must not stop the
        # sweep, and the per-leg counters below are the run's report.
        try:
            setup_employee_tax(payroll_api, xero_user_id, ird)
            results["tax"][0] += 1
            print(f"  Tax OK: IRD={ird} KiwiSaver=3%/3%")
        except Exception as e:  # noqa: BLE001 -- deliberate-swallow: counted and reported; the sweep continues
            results["tax"][1] += 1
            print(f"  ERROR Tax: {e}")

        try:
            setup_employee_leave(payroll_api, xero_user_id)
            results["leave"][0] += 1
            print("  Leave OK: Annual=160h Sick=80h")
        except Exception as e:  # noqa: BLE001 -- deliberate-swallow: counted and reported; the sweep continues
            results["leave"][1] += 1
            print(f"  ERROR Leave: {e}")

        try:
            setup_employee_bank(payroll_api, xero_user_id, bank)
            results["bank"][0] += 1
            print(f"  Bank OK: {bank}")
        except Exception as e:  # noqa: BLE001 -- deliberate-swallow: counted and reported; the sweep continues
            results["bank"][1] += 1
            print(f"  ERROR Bank: {e}")

    if not execute:
        print("\nDRY RUN complete - run with --execute to apply")
    else:
        print(
            f"\nResults: Tax {results['tax'][0]}/{sum(results['tax'])}, "
            f"Leave {results['leave'][0]}/{sum(results['leave'])}, "
            f"Bank {results['bank'][0]}/{sum(results['bank'])}"
        )


if __name__ == "__main__":
    main()
