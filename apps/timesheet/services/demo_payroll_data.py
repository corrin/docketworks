"""Fake payroll identifiers for non-production Xero organisations.

The IRD numbers and bank accounts here are format-valid and entirely made up.
Xero validates both at employee creation, so a demo organisation cannot be
seeded with placeholders — but nothing about a demo organisation should carry
a real person's tax number, and a scrubbed production dump does not contain
them anyway (the scrub strips staff identity, and Xero payroll identifiers
were never in the database to begin with).

Pure generators only. v1 kept the Xero tax/leave/bank write calls in this
module AND a second copy of them inside ``create_payroll_employee``, and its
sync ran both; v2 has one, in ``apps/xero/payroll_employees.py`` (ADR 0039).
"""

from stdnum.nz import ird

# Format-valid NZ accounts on one real ANZ branch (01-0242). Xero validates
# the bank/branch pair against its own table, so an invented branch is
# rejected; the account numbers within it are not real accounts.
BANK_ACCOUNTS = (
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
)

# Bases in 04900000-14999999 produce nine-digit IRD numbers. Stepping by 100
# keeps consecutive employees visibly distinct in Xero's UI.
_IRD_BASE = 4_900_000
_IRD_STEP = 100

# stdnum returns this when the base has no valid check digit under either
# weighting; such a base is skipped rather than corrected.
_NO_CHECK_DIGIT = "10"


def generate_ird_number(employee_number: int) -> str:
    """Build a distinct, format-valid, FAKE IRD number for one employee.

    ``employee_number`` is a 1-based position within the batch, not anything
    durable: the number only has to be unique inside the organisation being
    seeded, and re-seeding an organisation re-links existing employees rather
    than creating new ones.
    """
    if employee_number < 1:
        raise ValueError(f"employee_number is 1-based; got {employee_number}")

    base = _IRD_BASE + employee_number * _IRD_STEP
    while True:
        padded = str(base).zfill(8)
        check_digit = ird.calc_check_digit(padded)
        if check_digit != _NO_CHECK_DIGIT:
            return ird.format(padded + check_digit)
        base += 1


def get_bank_account(employee_number: int) -> str:
    """Pick a format-valid, FAKE NZ bank account for one employee.

    Accounts repeat every ten employees on purpose — Xero does not require
    them to be distinct, and ten hand-verified accounts beat generating
    numbers whose branch Xero would reject.
    """
    if employee_number < 1:
        raise ValueError(f"employee_number is 1-based; got {employee_number}")
    return BANK_ACCOUNTS[employee_number % len(BANK_ACCOUNTS)]
