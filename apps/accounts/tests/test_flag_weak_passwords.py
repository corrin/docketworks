"""The flag_weak_passwords command: every user gets the reset flag."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import Staff

pytestmark = pytest.mark.django_db


def _run() -> str:
    out = StringIO()
    call_command("flag_weak_passwords", stdout=out)
    return out.getvalue()


@pytest.fixture
def two_staff() -> tuple[Staff, Staff]:
    first = Staff.objects.create_user(
        email="first@example.test",
        password="password-one",
        first_name="First",
        last_name="Person",
    )
    second = Staff.objects.create_user(
        email="second@example.test",
        password="password-two",
        first_name="Second",
        last_name="Person",
    )
    return first, second


def test_flags_every_user(two_staff: tuple[Staff, Staff]) -> None:
    first, second = two_staff
    assert first.password_needs_reset is False

    output = _run()

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.password_needs_reset is True
    assert second.password_needs_reset is True
    # Every row, not just the two created here (the baseline seeds staff too).
    assert not Staff.objects.filter(password_needs_reset=False).exists()
    assert "first@example.test" in output
    assert "second@example.test" in output


@pytest.mark.usefixtures("two_staff")
def test_reports_total_flagged_count() -> None:
    output = _run()

    total = Staff.objects.count()
    assert f"{total} users marked to reset their passwords" in output


def test_rerun_is_idempotent(two_staff: tuple[Staff, Staff]) -> None:
    _run()
    _run()

    first, _ = two_staff
    first.refresh_from_db()
    assert first.password_needs_reset is True
    assert not Staff.objects.filter(password_needs_reset=False).exists()
