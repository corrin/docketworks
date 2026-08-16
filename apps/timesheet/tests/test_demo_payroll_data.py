"""Tests for the fake payroll identifiers a demo organisation is seeded with.

Xero validates both an IRD number's check digit and a bank account's branch at
employee-creation time, so "format-valid" is a hard requirement rather than
cosmetic — a wrong check digit is a failed create halfway through a seed.
"""

import pytest
from stdnum.nz import ird

from apps.timesheet.services import demo_payroll_data


class TestGenerateIrdNumber:
    def test_the_generated_number_passes_the_real_check_digit_rule(self) -> None:
        """The whole reason python-stdnum is a dependency (ADR 0032)."""
        assert ird.is_valid(demo_payroll_data.generate_ird_number(1))

    def test_a_batch_is_valid_and_distinct(self) -> None:
        numbers = [demo_payroll_data.generate_ird_number(n) for n in range(1, 51)]

        assert all(ird.is_valid(number) for number in numbers)
        assert len(set(numbers)) == len(numbers)

    def test_the_position_is_one_based(self) -> None:
        with pytest.raises(ValueError, match="1-based"):
            demo_payroll_data.generate_ird_number(0)


class TestGetBankAccount:
    def test_returns_a_four_part_nz_account(self) -> None:
        """Xero splits this into a 6-digit sort code and an undashed number."""
        assert len(demo_payroll_data.get_bank_account(1).split("-")) == 4

    def test_accounts_cycle_rather_than_running_out(self) -> None:
        size = len(demo_payroll_data.BANK_ACCOUNTS)

        assert demo_payroll_data.get_bank_account(1) == demo_payroll_data.get_bank_account(1 + size)

    def test_the_position_is_one_based(self) -> None:
        with pytest.raises(ValueError, match="1-based"):
            demo_payroll_data.get_bank_account(0)
