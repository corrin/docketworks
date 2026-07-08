import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job
from apps.workflow.models import CompanyDefaults


@pytest.fixture
def test_staff(db):
    return Staff.objects.create_user(
        email="process-test@example.com",
        password="testpass",
        first_name="Process",
        last_name="Tester",
    )


@pytest.fixture
def job(db, test_staff):
    shop_company = Company.objects.create(
        name="Process Shop Company",
        xero_last_modified=timezone.now(),
    )
    CompanyDefaults.objects.create(
        company_name="Process Test Co",
        shop_company=shop_company,
    )
    company = Company.objects.create(
        name="Test Company",
        xero_last_modified=timezone.now(),
    )
    return Job.objects.create(company=company, name="Test Job", staff=test_staff)
