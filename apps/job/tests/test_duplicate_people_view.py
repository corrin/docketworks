from apps.accounts.models import Staff
from apps.company.models import Person
from apps.testing import BaseAPITestCase

URL = "/api/job/data-quality/duplicate-people/"


class DuplicatePeopleViewTests(BaseAPITestCase):
    """The report contains identity data and must remain office-staff-only."""

    def _office_staff(self) -> Staff:
        return Staff.objects.create_user(
            email="office-person-report@example.com",
            password="testpass",
            first_name="Office",
            last_name="Staff",
            is_office_staff=True,
        )

    def test_returns_duplicate_person_candidates_to_office_staff(self) -> None:
        Person.objects.create(name="Jane Smith", email="jane@example.com")
        Person.objects.create(name="jane smith", email="JANE@example.com")
        self.client.force_authenticate(self._office_staff())

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["high"], 1)
        self.assertEqual(len(response.data["duplicate_people"]), 1)

    def test_forbidden_for_non_office_staff(self) -> None:
        self.client.force_authenticate(self.test_staff)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 403)
