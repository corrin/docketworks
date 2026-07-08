from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import ClientContactMethod, Company
from apps.testing import BaseAPITestCase

URL = "/api/job/data-quality/duplicate-phones/"


class DuplicatePhonesViewTests(BaseAPITestCase):
    def _office_staff(self) -> Staff:
        return Staff.objects.create_user(
            email="office@example.com",
            password="testpass",
            first_name="Office",
            last_name="Staff",
            is_office_staff=True,
        )

    def _phone(self, value: str, company: Company) -> None:
        method = ClientContactMethod(
            company=company,
            method_type=ClientContactMethod.MethodType.PHONE,
            value=value,
        )
        method.normalized_value = ClientContactMethod.normalize_phone(value)
        ClientContactMethod.objects.bulk_create([method])

    def test_returns_cross_company_conflict_to_office_staff(self) -> None:
        acme = Company.objects.create(name="Acme", xero_last_modified=timezone.now())
        beta = Company.objects.create(name="Beta", xero_last_modified=timezone.now())
        self._phone("021 111 111", acme)
        self._phone("021 111 111", beta)
        self.client.force_authenticate(self._office_staff())

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["cross_client"], 1)
        self.assertEqual(len(response.data["duplicate_phones"]), 1)
        self.assertEqual(len(response.data["duplicate_phones"][0]["owners"]), 2)

    def test_forbidden_for_non_office_staff(self) -> None:
        self.client.force_authenticate(self.test_staff)  # not office staff

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 403)
