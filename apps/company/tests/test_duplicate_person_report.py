from django.test import TestCase
from django.utils import timezone

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.duplicate_person_report import (
    DuplicatePersonReportService,
    person_names_compatible,
)


class DuplicatePersonReportTests(TestCase):
    """Exact signals must find review candidates without splitting one Person."""

    def _company(self, name: str) -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def _link(self, person: Person, company: Company) -> None:
        CompanyPersonLink.objects.create(person=person, company=company)

    def _legacy_phone(self, person: Person, value: str) -> None:
        method = ContactMethod(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value=value,
            normalized_value=ContactMethod.normalize_phone(value),
        )
        ContactMethod.objects.bulk_create([method])

    def test_combined_name_and_email_is_high_confidence(self) -> None:
        """A report refactor must retain all evidence used for safe auto-selection."""
        first = Person.objects.create(name=" Jane   Smith ", email="JANE@example.com")
        second = Person.objects.create(name="jane smith", email="jane@example.com")
        self._link(first, self._company("Acme"))
        self._link(second, self._company("Beta"))

        report = DuplicatePersonReportService().get_report()

        self.assertEqual(len(report["duplicate_people"]), 1)
        candidate = report["duplicate_people"][0]
        self.assertEqual(candidate["confidence"], "high")
        self.assertEqual(
            {match["kind"] for match in candidate["matches"]}, {"name", "email"}
        )
        self.assertEqual(report["summary"]["people_flagged"], 2)

    def test_phone_only_match_is_medium_confidence(self) -> None:
        """Person-owned phones are useful candidates even when names differ."""
        first = Person.objects.create(name="Jane Smith")
        second = Person.objects.create(name="J Smith")
        self._legacy_phone(first, "021 555 123")
        self._legacy_phone(second, "+64 21 555 123")

        candidate = DuplicatePersonReportService().get_report()["duplicate_people"][0]

        self.assertEqual(candidate["confidence"], "medium")
        self.assertEqual(candidate["matches"][0]["kind"], "phone")

    def test_one_person_linked_to_multiple_companies_is_not_duplicate(self) -> None:
        """The first-class model allows one human to have several company links."""
        person = Person.objects.create(name="Jane Smith", email="jane@example.com")
        self._link(person, self._company("Acme"))
        self._link(person, self._company("Beta"))
        self._legacy_phone(person, "021 555 123")

        report = DuplicatePersonReportService().get_report()

        self.assertEqual(report["duplicate_people"], [])
        self.assertEqual(report["summary"]["candidate_pairs"], 0)

    def test_name_only_match_is_low_confidence(self) -> None:
        """Common exact names require review rather than automatic confidence."""
        Person.objects.create(name="Accounts")
        Person.objects.create(name=" accounts ")

        candidate = DuplicatePersonReportService().get_report()["duplicate_people"][0]

        self.assertEqual(candidate["confidence"], "low")

    def test_nickname_and_phone_is_high_confidence(self) -> None:
        first = Person.objects.create(name="Christopher Watt")
        second = Person.objects.create(name="Chris Watt")
        self._legacy_phone(first, "021 555 123")
        self._legacy_phone(second, "+64 21 555 123")

        candidate = DuplicatePersonReportService().get_report()["duplicate_people"][0]

        self.assertEqual(candidate["confidence"], "high")
        self.assertEqual(
            {match["kind"] for match in candidate["matches"]}, {"name", "phone"}
        )

    def test_two_contact_signals_with_incompatible_names_is_medium(self) -> None:
        first = Person.objects.create(name="Brian")
        second = Person.objects.create(name="Brent")
        for person in (first, second):
            ContactMethod.objects.create(
                person=person,
                method_type=ContactMethod.MethodType.EMAIL,
                value="office@example.com",
            )
            self._legacy_phone(person, "021 555 123")

        candidate = DuplicatePersonReportService().get_report()["duplicate_people"][0]

        self.assertEqual(candidate["confidence"], "medium")

    def test_nickname_does_not_override_conflicting_surnames(self) -> None:
        self.assertFalse(person_names_compatible("Robert Grant", "Rob Smith"))
