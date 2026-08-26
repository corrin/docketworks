"""The at-least-one-email rule (owner ruling, 2026-08-26).

Some staff have a payroll mailbox (Xero-owned), some an office mailbox, and
many have only one of the two. StaffEmailBackend signs a staff member in with
either address, so the model requires at least one and neither field is
individually required. Blank strings never reach either column (ADR 0040).
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client

from apps.accounts.models import Staff

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

PASSWORD = "s3cret-Pass!"
LOGIN_PATH = "/api/accounts/token/"


def payroll_only_staff(payroll_email: str = "wage@example.com") -> Staff:
    return Staff.objects.create_user(
        office_email=None,
        password=PASSWORD,
        payroll_email=payroll_email,
        first_name="Wage",
        last_name="Worker",
    )


class TestModelRule:
    def test_payroll_only_staff_passes_full_clean_and_saves(self) -> None:
        staff = Staff(payroll_email="wage@example.com", first_name="Wage", last_name="Worker")
        staff.set_password(PASSWORD)

        staff.full_clean()
        staff.save()

        staff.refresh_from_db()
        assert staff.office_email is None
        assert staff.payroll_email == "wage@example.com"

    def test_full_clean_never_launders_a_missing_office_email_into_blank(self) -> None:
        """BaseUserManager.normalize_email coerces None to "" — clean() must
        not apply it to an unset office_email, or the blank slips past every
        isnull check and lands in the column (ADR 0040)."""
        staff = Staff(payroll_email="wage@example.com", first_name="Wage", last_name="Worker")
        staff.set_password(PASSWORD)

        staff.full_clean()

        assert staff.office_email is None

    def test_neither_email_is_refused_with_a_readable_message(self) -> None:
        staff = Staff(first_name="No", last_name="Email")

        with pytest.raises(ValidationError) as excinfo:
            staff.full_clean()

        assert "at least one email" in " ".join(excinfo.value.messages)

    def test_two_payroll_only_rows_coexist(self) -> None:
        """NULL office_emails must be distinct under both unique indexes (the
        plain column one and the Lower() case-insensitive one)."""
        payroll_only_staff("one@example.com")
        payroll_only_staff("two@example.com")

        assert Staff.objects.filter(office_email__isnull=True).count() == 2

    def test_case_variant_duplicate_payroll_email_is_refused_with_a_readable_message(self) -> None:
        """StaffEmailBackend matches payroll_email with iexact and returns
        None on multiple hits — a case-variant duplicate would lock BOTH
        accounts out of login, same as the office_email rule."""
        payroll_only_staff("wage@example.com")
        staff = Staff(payroll_email="WAGE@example.com", first_name="Two", last_name="Worker")
        staff.set_password(PASSWORD)

        with pytest.raises(ValidationError) as excinfo:
            staff.full_clean()

        assert "payroll email" in " ".join(excinfo.value.messages).lower()

    def test_case_variant_duplicate_payroll_email_is_refused_by_the_database(self) -> None:
        """The database's answer to the race clean() cannot close."""
        payroll_only_staff("wage@example.com")
        staff = Staff(payroll_email="WAGE@example.com", first_name="Two", last_name="Worker")
        staff.set_password(PASSWORD)

        with pytest.raises(IntegrityError), transaction.atomic():
            staff.save()

    def test_blank_office_email_is_refused_by_the_database(self) -> None:
        staff = Staff(
            office_email="",
            payroll_email="wage@example.com",
            first_name="Wage",
            last_name="Worker",
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            staff.save()


class TestCreateUser:
    def test_create_user_accepts_a_payroll_only_staff_member(self) -> None:
        staff = payroll_only_staff()

        assert staff.office_email is None
        assert staff.check_password(PASSWORD)

    def test_create_user_refuses_a_staff_member_with_no_email(self) -> None:
        with pytest.raises(ValueError, match="at least one email"):
            Staff.objects.create_user(office_email=None, first_name="No", last_name="Email")


class TestLogin:
    def test_a_payroll_only_staff_member_signs_in_with_the_payroll_address(self) -> None:
        payroll_only_staff()

        response = Client().post(
            LOGIN_PATH,
            data={"username": "wage@example.com", "password": PASSWORD},
            content_type="application/json",
        )

        assert response.status_code == 200
