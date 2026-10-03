"""The E2E fixtures command: idempotent, and exact on the wage the spec pins."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.core.test_data import TEST_COMPANY_NAME

pytestmark = pytest.mark.django_db

E2E_EMAIL = "e2e@example.test"
WORKSHOP_EMAIL = "e2e-workshop@example.test"


def _run() -> str:
    out = StringIO()
    call_command("e2e_ensure_fixtures", stdout=out)
    return out.getvalue()


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_TEST_USERNAME", E2E_EMAIL)
    monkeypatch.setenv("E2E_TEST_PASSWORD", "first-password")
    monkeypatch.setenv("E2E_WORKSHOP_USERNAME", WORKSHOP_EMAIL)
    monkeypatch.setenv("E2E_WORKSHOP_PASSWORD", "workshop-password")


@pytest.mark.usefixtures("credentials")
def test_creates_the_user_with_the_spec_s_wage_and_the_test_company() -> None:
    defaults = CompanyDefaults.get_solo()
    defaults.test_company_name = None
    defaults.save(update_fields=["test_company_name"])

    output = _run()

    user = Staff.objects.get(office_email=E2E_EMAIL)
    assert user.is_office_staff and user.is_superuser
    assert user.check_password("first-password")
    assert user.wage_rate == Decimal("45.00")
    company = Company.objects.get(name=TEST_COMPANY_NAME)
    assert CompanyDefaults.get_solo().test_company_name == TEST_COMPANY_NAME
    assert f"Test company: {company.name}" in output


@pytest.mark.usefixtures("credentials")
def test_derives_the_base_wage_from_this_database_s_loading() -> None:
    defaults = CompanyDefaults.get_solo()
    defaults.labour_cost_loading = Decimal("25.00")
    defaults.save(update_fields=["labour_cost_loading"])

    _run()

    user = Staff.objects.get(office_email=E2E_EMAIL)
    assert user.base_wage_rate == Decimal("36.00")
    assert user.wage_rate == Decimal("45.00")


@pytest.mark.usefixtures("credentials")
def test_a_second_run_realigns_the_password_and_creates_nothing_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run()
    monkeypatch.setenv("E2E_TEST_PASSWORD", "rotated-password")

    _run()

    assert Staff.objects.filter(office_email__iexact=E2E_EMAIL).count() == 1
    assert Company.objects.filter(name=TEST_COMPANY_NAME).count() == 1
    assert Staff.objects.get(office_email=E2E_EMAIL).check_password("rotated-password")


@pytest.mark.usefixtures("credentials")
def test_creates_the_workshop_user_as_shop_floor_staff() -> None:
    _run()

    user = Staff.objects.get(office_email=WORKSHOP_EMAIL)
    assert not user.is_office_staff and not user.is_superuser
    assert user.is_workshop_staff
    assert user.check_password("workshop-password")
    assert user.wage_rate > 0
    assert user.default_labour_subtype is not None
    assert user.default_labour_subtype.is_workshop


@pytest.mark.usefixtures("credentials")
def test_a_second_run_takes_office_access_back_off_the_workshop_user() -> None:
    _run()
    user = Staff.objects.get(office_email=WORKSHOP_EMAIL)
    user.is_office_staff = True
    user.is_superuser = True
    user.set_password("drifted")
    user.save()

    _run()

    user.refresh_from_db()
    assert not user.is_office_staff and not user.is_superuser
    assert user.check_password("workshop-password")
    assert Staff.objects.filter(office_email__iexact=WORKSHOP_EMAIL).count() == 1


@pytest.mark.usefixtures("credentials")
def test_refuses_without_the_workshop_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2E_WORKSHOP_PASSWORD")
    with pytest.raises(CommandError, match="E2E_WORKSHOP_PASSWORD is not set"):
        _run()


def test_refuses_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2E_TEST_USERNAME", raising=False)
    monkeypatch.delenv("E2E_TEST_PASSWORD", raising=False)
    with pytest.raises(CommandError, match="E2E_TEST_USERNAME is not set"):
        _run()
