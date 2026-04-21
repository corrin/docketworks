from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.client.models import Client
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
    defaults = CompanyDefaults.get_solo()
    defaults.charge_out_rate = Decimal("105.00")
    defaults.save()
    client = Client.objects.create(
        name="Test Client",
        xero_last_modified=timezone.now(),
    )
    return Job.objects.create(client=client, name="Test Job", staff=test_staff)
