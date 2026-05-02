"""
Generate fake payroll data for development and testing.

WARNING: This module generates FAKE IRD numbers and bank accounts.
These are syntactically valid but not real. Never use in production.
"""

import logging
import time

from stdnum.nz import ird as nz_ird
from xero_python.payrollnz import PayrollNzApi
from xero_python.payrollnz.models import (
    BankAccount,
    EmployeeLeaveSetup,
    EmployeeTax,
    PaymentMethod,
    TaxCode,
)

from apps.workflow.api.xero.active_app import get_active_client
from apps.workflow.api.xero.auth import get_tenant_id

logger = logging.getLogger(__name__)

# Pause between Xero API calls to avoid rate limiting
_API_PAUSE_SECONDS = 3

# Pre-validated NZ bank accounts (ANZ branch 01-0242)
_BANK_ACCOUNTS = [
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


def generate_ird_number(employee_num: int) -> str:
    """Generate a syntactically valid NZ IRD number with proper checksum."""
    # Use base in range 04900000-14999999 to produce valid 9-digit IRDs
    # The base must be zero-padded to 8 digits for proper checksum calculation
    base = 4900000 + (employee_num * 100)
    while True:
        base_str = str(base).zfill(8)  # Zero-pad to 8 digits (e.g., "06300100")
        check_digit = nz_ird.calc_check_digit(base_str)
        if check_digit != "10":
            full_ird = base_str + check_digit
            return nz_ird.format(full_ird)
        base += 1


def get_bank_account(index: int) -> str:
    """Get a pre-validated NZ bank account number."""
    return _BANK_ACCOUNTS[index % len(_BANK_ACCOUNTS)]


def setup_employee_tax(employee_id: str, ird_number: str) -> None:
    """Set up employee tax details including KiwiSaver."""
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_active_client())

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
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employee_tax=tax,
    )
    logger.info("Set up tax for employee %s: IRD=%s", employee_id, ird_number)
    time.sleep(_API_PAUSE_SECONDS)


def setup_employee_leave(employee_id: str) -> None:
    """Set up employee leave entitlements."""
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_active_client())

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
            xero_tenant_id=tenant_id,
            employee_id=employee_id,
            employee_leave_setup=leave_setup,
        )
        logger.info("Set up leave for employee %s", employee_id)
    except Exception as e:
        if "already setup" in str(e).lower():
            logger.info("Leave already set up for employee %s", employee_id)
        else:
            raise
    time.sleep(_API_PAUSE_SECONDS)


def setup_employee_bank(employee_id: str, bank_account_number: str) -> None:
    """Set up employee bank account."""
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_active_client())

    parts = bank_account_number.split("-")
    if len(parts) != 4:
        raise ValueError(f"Invalid bank account format: {bank_account_number}")

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
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        payment_method=payment,
    )
    logger.info("Set up bank for employee %s: %s", employee_id, bank_account_number)
    time.sleep(_API_PAUSE_SECONDS)
