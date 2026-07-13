from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.testing import BaseAPITestCase

URL = "/api/job/data-quality/duplicate-identities/"


class DuplicateIdentitiesViewTests(BaseAPITestCase):
    def _office_staff(self) -> Staff:
        return Staff.objects.create_user(
            email="office@example.com",
            password="testpass",
            first_name="Office",
            last_name="Staff",
            is_office_staff=True,
        )

    def test_returns_grouped_duplicates_to_office_staff(self) -> None:
        Company.objects.create(name="Acme Ltd", xero_last_modified=timezone.now())
        Company.objects.create(
            name="CASH SALE - Acme Limited",
            xero_last_modified=timezone.now(),
        )
        self.client.force_authenticate(self._office_staff())

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["company_merge_groups"], 1)
        self.assertEqual(len(response.data["company_groups"]), 1)

    def test_forbidden_for_non_office_staff(self) -> None:
        self.client.force_authenticate(self.test_staff)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 403)
