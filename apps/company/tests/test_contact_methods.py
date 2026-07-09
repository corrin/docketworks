import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

if TYPE_CHECKING:
    from apps.job.models import Job

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.company_rest_service import CompanyRestService
from apps.crm.models import PhoneCallRecord
from apps.crm.services.phone_call_service import rematch_calls_for_numbers
from apps.testing import BaseAPITestCase, BaseTestCase
from apps.workflow.accounting.types import ContactResult
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import AppError


def _link(company: Company, name: str, email: str | None = None) -> CompanyPersonLink:
    person = Person.objects.create(name=name, email=email)
    return CompanyPersonLink.objects.create(
        company=company,
        person=person,
        xero_name=name,
    )


class ContactMethodTests(TestCase):
    def _company(self, name: str = "Acme Ltd") -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def test_phone_normalization_matches_nz_variants(self) -> None:
        """Catches call matching failures when NZ local and E.164 numbers diverge."""
        self.assertEqual(
            ContactMethod.normalize_phone("+64 9 636 5131"),
            "+6496365131",
        )
        self.assertEqual(
            ContactMethod.normalize_phone("09 636 5131"),
            "+6496365131",
        )

    def test_primary_phone_is_single_per_company_owner(self) -> None:
        """Catches multiple primary phone numbers being left on a company record."""
        company = self._company()
        first = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )
        second = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 222 2222",
            is_primary=True,
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)

    def test_same_number_allowed_on_company_and_its_own_contact(self) -> None:
        """A company and its own contact sharing one line must not be rejected."""
        company = self._company()
        contact = _link(company, "Jane Smith")
        on_company = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        on_contact = ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )

        self.assertEqual(on_company.normalized_value, on_contact.normalized_value)
        self.assertIsNotNone(on_contact.pk)

    def test_same_number_allowed_on_two_contacts_of_same_company(self) -> None:
        """Two contacts of one company can share a number (one effective company)."""
        company = self._company()
        first_contact = _link(company, "A")
        second_contact = _link(company, "B")
        ContactMethod.objects.create(
            person=first_contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        on_second = ContactMethod.objects.create(
            person=second_contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )

        self.assertIsNotNone(on_second.pk)

    def test_same_number_rejected_across_different_companies(self) -> None:
        """Two different companies cannot own one number; the matcher would be ambiguous."""
        company_a = self._company("Acme Ltd")
        company_b = self._company("Beta Ltd")
        ContactMethod.objects.create(
            company=company_a,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        with self.assertRaises(ValidationError):
            ContactMethod.objects.create(
                company=company_b,
                method_type=ContactMethod.MethodType.PHONE,
                value="021 111 111",
            )

    def test_same_number_rejected_across_contacts_of_different_companies(self) -> None:
        """Contacts of two different companies cannot share a number."""
        company_a = self._company("Acme Ltd")
        company_b = self._company("Beta Ltd")
        contact_a = _link(company_a, "A")
        contact_b = _link(company_b, "B")
        ContactMethod.objects.create(
            person=contact_a.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        with self.assertRaises(ValidationError):
            ContactMethod.objects.create(
                person=contact_b.person,
                method_type=ContactMethod.MethodType.PHONE,
                value="021 111 111",
            )

    def test_grandfathered_cross_company_number_can_be_resaved(self) -> None:
        """A pre-existing cross-company number (legacy data) re-saves unchanged."""
        company_a = self._company("Acme Ltd")
        company_b = self._company("Beta Ltd")
        ContactMethod.objects.create(
            company=company_a,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        # Simulate legacy prod data: B already owns the same number, inserted
        # bypassing the guard (as pre-guard rows were).
        legacy = ContactMethod(
            company=company_b,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        legacy.normalized_value = ContactMethod.normalize_phone("021 111 111")
        ContactMethod.objects.bulk_create([legacy])

        legacy.refresh_from_db()
        legacy.label = "Mobile"
        legacy.save()  # association unchanged -> grandfathered, must not raise

        legacy.refresh_from_db()
        self.assertEqual(legacy.label, "Mobile")

    def test_changing_number_into_another_companies_ownership_raises(self) -> None:
        """Editing a method's number onto another company's number is blocked."""
        company_a = self._company("Acme Ltd")
        company_b = self._company("Beta Ltd")
        ContactMethod.objects.create(
            company=company_a,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        moving = ContactMethod.objects.create(
            company=company_b,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 222 222",
        )

        moving.value = "021 111 111"  # now collides with company A
        with self.assertRaises(ValidationError):
            moving.save()

    def test_primary_phone_is_single_per_contact_owner(self) -> None:
        """Catches multiple primary phone numbers being left on a contact record."""
        company = self._company()
        contact = _link(company, "Jane Smith")
        first = ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
            is_primary=True,
        )
        second = ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 222 222",
            is_primary=True,
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)

    def test_partial_update_fields_still_persists_normalized_value(self) -> None:
        """save(update_fields=["value"]) must also persist the recomputed
        normalized_value, or the matching/uniqueness index goes stale."""
        company = self._company("Acme Ltd")
        method = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )

        method.value = "021 222 222"
        method.save(update_fields=["value"])

        method.refresh_from_db()
        self.assertEqual(
            method.normalized_value,
            ContactMethod.normalize_phone("021 222 222"),
        )


class CompanyPrimaryPhoneValueTests(TestCase):
    """Guards the helper PO PDFs and Xero sync use to print a supplier phone."""

    def test_returns_primary_phone_first(self) -> None:
        company = Company.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
        )
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 222 2222",
            is_primary=True,
        )

        self.assertEqual(company.primary_phone_value(), "09 222 2222")

    def test_returns_empty_string_when_no_phone_methods(self) -> None:
        company = Company.objects.create(
            name="Phoneless Ltd", xero_last_modified=timezone.now()
        )
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.EMAIL,
            value="office@example.com",
        )

        self.assertEqual(company.primary_phone_value(), "")


class PrimaryPhoneAnnotationTests(TestCase):
    """Guards the shared queryset annotation every phone-bearing payload uses."""

    def _company(self, name: str = "Acme Ltd") -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def test_company_annotation_prefers_primary_over_label_order(self) -> None:
        company = self._company()
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
            label="AAA sorts first",
        )
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 222 2222",
            label="ZZZ sorts last",
            is_primary=True,
        )

        annotated = Company.objects.annotate(
            phone=ContactMethod.primary_phone_annotation(
                owner="company", outer_ref="pk"
            )
        ).get(pk=company.pk)

        self.assertEqual(annotated.phone, "09 222 2222")

    def test_company_annotation_is_empty_string_without_phones(self) -> None:
        company = self._company("Phoneless Ltd")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.EMAIL,
            value="office@example.com",
        )

        annotated = Company.objects.annotate(
            phone=ContactMethod.primary_phone_annotation(
                owner="company", outer_ref="pk"
            )
        ).get(pk=company.pk)

        self.assertEqual(annotated.phone, "")

    def test_contact_annotation_returns_contact_primary_phone(self) -> None:
        company = self._company()
        contact = _link(company, "Jane Smith")
        ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 222 222",
            is_primary=True,
        )

        annotated = CompanyPersonLink.objects.annotate(
            phone=ContactMethod.primary_phone_for_link_annotation()
        ).get(pk=contact.pk)

        self.assertEqual(annotated.phone, "021 222 222")


class UpdateJobContactTests(BaseTestCase):
    """Guards that reassigning a job's contact persists to the job record."""

    def _job_with_contact(self) -> "tuple[Job, Company, CompanyPersonLink]":
        from apps.job.models import Job
        from apps.workflow.models import XeroPayItem

        company = Company.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )
        contact = _link(company, "Jane Smith")
        job: Job = Job.objects.create(
            name="Contact Assignment Job",
            company=company,
            person=contact.person,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )
        return job, company, contact

    def test_update_job_person_persists_new_person(self) -> None:
        job, company, _ = self._job_with_contact()
        new_contact = _link(company, "Bob Brown")

        CompanyRestService.update_job_person(
            job.id, {"id": str(new_contact.person_id)}, self.test_staff
        )

        job.refresh_from_db()
        self.assertEqual(job.person_id, new_contact.person_id)


class CompanyListPhoneTests(TestCase):
    """Guards the Phone column of the companies list (restored after the
    ContactMethod migration dropped it)."""

    def _company_with_phone(self, name: str, phone: str) -> Company:
        company = Company.objects.create(name=name, xero_last_modified=timezone.now())
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value=phone,
            is_primary=True,
        )
        return company

    def _lazy_phone_queries(self, captured: CaptureQueriesContext) -> list[str]:
        return [
            q["sql"]
            for q in captured.captured_queries
            if q["sql"].startswith('SELECT "company_clientcontactmethod"')
        ]

    def test_list_companies_rows_include_phone(self) -> None:
        self._company_with_phone("Acme Ltd", "09 111 1111")
        Company.objects.create(name="Phoneless Ltd", xero_last_modified=timezone.now())

        with CaptureQueriesContext(connection) as captured:
            result = CompanyRestService.list_companies(page=1, page_size=10)

        phones = {row["name"]: row["phone"] for row in result["results"]}
        self.assertEqual(phones["Acme Ltd"], "09 111 1111")
        self.assertEqual(phones["Phoneless Ltd"], "")
        self.assertEqual(self._lazy_phone_queries(captured), [])

    def test_searched_clients_include_phone(self) -> None:
        self._company_with_phone("Acme Ltd", "09 111 1111")

        result = CompanyRestService.list_companies(query="Acme", page=1, page_size=10)

        self.assertEqual(result["results"][0]["phone"], "09 111 1111")


class CompanyPersonLinkApiPhoneTests(BaseAPITestCase):
    """Guards the contact phone read/write restored on the contacts endpoint
    (company detail People card, PersonSelectionModal, person picker)."""

    URL = "/api/companies/person-links/"

    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)
        self.job_client = Company.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )

    def _contact(
        self, name: str = "Jane Smith", phone: str | None = None
    ) -> CompanyPersonLink:
        contact = _link(self.job_client, name)
        if phone is not None:
            ContactMethod.objects.create(
                person=contact.person,
                method_type=ContactMethod.MethodType.PHONE,
                value=phone,
                is_primary=True,
            )
        return contact

    def test_list_includes_contact_phone_without_lazy_queries(self) -> None:
        self._contact("Jane Smith", phone="021 111 111")
        self._contact("No Phone")

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                self.URL, {"company_id": str(self.job_client.id)}
            )

        self.assertEqual(response.status_code, 200)
        phones = {row["person_name"]: row["phone"] for row in response.json()}
        self.assertEqual(phones["Jane Smith"], "021 111 111")
        self.assertEqual(phones["No Phone"], "")
        lazy = [
            q["sql"]
            for q in captured.captured_queries
            if q["sql"].startswith('SELECT "company_clientcontactmethod"')
        ]
        self.assertEqual(lazy, [])

    def test_create_contact_with_phone_creates_primary_method(self) -> None:
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    self.URL,
                    {
                        "company": str(self.job_client.id),
                        "person_name": "Bob Brown",
                        "phone": "021 222 222",
                    },
                    format="json",
                )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["phone"], "021 222 222")
        method = ContactMethod.objects.get(person__name="Bob Brown")
        self.assertEqual(method.method_type, ContactMethod.MethodType.PHONE)
        self.assertTrue(method.is_primary)
        rematch.assert_called_once_with(["+6421222222"])

    def test_update_phone_updates_existing_primary_method(self) -> None:
        contact = self._contact("Jane Smith", phone="021 111 111")
        method = contact.person.contact_methods.get()

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    f"{self.URL}{contact.id}/",
                    {"phone": "021 333 333"},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "021 333 333")
        method.refresh_from_db()
        self.assertEqual(method.value, "021 333 333")
        self.assertEqual(contact.person.contact_methods.count(), 1)
        rematch.assert_called_once_with(["+6421111111", "+6421333333"])

    def test_update_phone_matching_secondary_promotes_it(self) -> None:
        contact = self._contact("Jane Smith", phone="021 111 111")
        secondary = ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 444 444",
        )

        response = self.client.patch(
            f"{self.URL}{contact.id}/",
            {"phone": "021 444 444"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        secondary.refresh_from_db()
        self.assertTrue(secondary.is_primary)
        self.assertEqual(
            contact.person.contact_methods.filter(is_primary=True).count(), 1
        )

    def test_blank_phone_leaves_methods_untouched(self) -> None:
        contact = self._contact("Jane Smith", phone="021 111 111")

        response = self.client.patch(
            f"{self.URL}{contact.id}/",
            {"phone": "", "position": "Manager"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "021 111 111")
        self.assertEqual(contact.person.contact_methods.count(), 1)

    def test_conflicting_phone_returns_400_and_creates_nothing(self) -> None:
        other_client = Company.objects.create(
            name="Beta Ltd", xero_last_modified=timezone.now()
        )
        ContactMethod.objects.create(
            company=other_client,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 555",
        )
        contact = self._contact("Jane Smith")

        response = self.client.patch(
            f"{self.URL}{contact.id}/",
            {"phone": "021 555 555"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.json())
        self.assertEqual(contact.person.contact_methods.count(), 0)


class CompanyUpdatePhoneTests(BaseAPITestCase):
    """Guards the phone edit restored on the Edit Company modal's update flow
    (company detail's "phone" read via ContactMethod, written through
    set_primary_phone)."""

    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)

    def _company(self, name: str = "Acme Ltd") -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def _update_url(self, company_id: uuid.UUID) -> str:
        return f"/api/companies/{company_id}/update/"

    def test_update_with_new_phone_creates_primary_method(self) -> None:
        company = self._company()

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    self._update_url(company.id),
                    {"phone": "09 111 1111"},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company"]["phone"], "09 111 1111")
        method = ContactMethod.objects.get(company=company)
        self.assertEqual(method.method_type, ContactMethod.MethodType.PHONE)
        self.assertEqual(method.value, "09 111 1111")
        self.assertTrue(method.is_primary)
        rematch.assert_called_once_with([ContactMethod.normalize_phone("09 111 1111")])

    def test_update_with_existing_secondary_number_promotes_it(self) -> None:
        company = self._company()
        primary = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )
        secondary = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 222 2222",
        )

        response = self.client.patch(
            self._update_url(company.id), {"phone": "09 222 2222"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        primary.refresh_from_db()
        secondary.refresh_from_db()
        self.assertFalse(primary.is_primary)
        self.assertTrue(secondary.is_primary)
        self.assertEqual(company.contact_methods.count(), 2)

    def test_update_renumbers_current_primary_when_number_is_new(self) -> None:
        """Matches set_primary_phone's contract: a genuinely new number reuses
        (renumbers) the existing primary row instead of creating a second
        one."""
        company = self._company()
        primary = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )

        response = self.client.patch(
            self._update_url(company.id), {"phone": "09 333 3333"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(company.contact_methods.count(), 1)
        primary.refresh_from_db()
        self.assertEqual(primary.value, "09 333 3333")
        self.assertTrue(primary.is_primary)

    def test_blank_phone_clears_primary_method(self) -> None:
        company = self._company()
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )

        with patch(
            "apps.company.services.company_rest_service.rematch_phone_calls_task.delay"
        ) as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    self._update_url(company.id),
                    {"phone": "", "name": "Acme Renamed"},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company"]["phone"], "")
        self.assertEqual(company.contact_methods.count(), 0)
        company.refresh_from_db()
        self.assertEqual(company.name, "Acme Renamed")
        rematch.assert_called_once_with([ContactMethod.normalize_phone("09 111 1111")])

    def test_omitted_phone_leaves_methods_untouched(self) -> None:
        company = self._company()
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )

        with patch(
            "apps.company.services.company_rest_service.rematch_phone_calls_task.delay"
        ) as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    self._update_url(company.id),
                    {"name": "Acme Renamed"},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company"]["phone"], "09 111 1111")
        self.assertEqual(company.contact_methods.count(), 1)
        company.refresh_from_db()
        self.assertEqual(company.name, "Acme Renamed")
        rematch.assert_not_called()

    def test_conflicting_phone_returns_400_and_rolls_back_update(self) -> None:
        """A conflict must not leave the update half-applied: neither the new
        name nor a stray contact method should be persisted."""
        other = self._company("Beta Ltd")
        ContactMethod.objects.create(
            company=other,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 5555",
        )
        company = self._company("Acme Ltd")

        response = self.client.patch(
            self._update_url(company.id),
            {"phone": "09 555 5555", "name": "Acme Renamed"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.json()["error"].lower())
        company.refresh_from_db()
        self.assertEqual(company.name, "Acme Ltd")
        self.assertEqual(company.contact_methods.count(), 0)

    def test_get_company_detail_returns_primary_phone(self) -> None:
        company = self._company()
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )

        response = self.client.get(f"/api/companies/{company.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "09 111 1111")

    def test_get_company_detail_returns_empty_string_without_phone(self) -> None:
        company = self._company("Phoneless Ltd")

        response = self.client.get(f"/api/companies/{company.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "")

    def test_xero_synced_update_applies_phone_before_provider_push(self) -> None:
        company = self._company()
        company.xero_contact_id = "xero-contact-id"
        company.save()
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.update_contact.return_value = ContactResult(
            success=True, external_id=company.xero_contact_id, name=company.name
        )

        with patch(
            "apps.company.services.company_rest_service.get_provider",
            return_value=provider,
        ):
            with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.patch(
                        self._update_url(company.id),
                        {"phone": "09 444 4444"},
                        format="json",
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company"]["phone"], "09 444 4444")
        pushed_company = provider.update_contact.call_args.args[0]
        pushed_contact = pushed_company.get_company_for_xero()
        self.assertEqual(pushed_contact.phones[0].phone_number, "09 444 4444")
        rematch.assert_called_once_with([ContactMethod.normalize_phone("09 444 4444")])

    def test_xero_synced_blank_phone_clears_before_provider_push(self) -> None:
        company = self._company()
        company.xero_contact_id = "xero-contact-id"
        company.save()
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.update_contact.return_value = ContactResult(
            success=True, external_id=company.xero_contact_id, name=company.name
        )

        with patch(
            "apps.company.services.company_rest_service.get_provider",
            return_value=provider,
        ):
            with patch(
                "apps.company.services.company_rest_service."
                "rematch_phone_calls_task.delay"
            ) as rematch:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.patch(
                        self._update_url(company.id),
                        {"phone": ""},
                        format="json",
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company"]["phone"], "")
        pushed_company = provider.update_contact.call_args.args[0]
        pushed_contact = pushed_company.get_company_for_xero()
        self.assertIsNone(pushed_contact.phones[0].phone_number)
        rematch.assert_called_once_with([ContactMethod.normalize_phone("09 111 1111")])

    def test_phone_rematch_waits_until_transaction_commit(self) -> None:
        company = self._company()

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                response = self.client.patch(
                    self._update_url(company.id),
                    {"phone": "09 111 1111"},
                    format="json",
                )
                rematch.assert_not_called()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(callbacks), 1)
            rematch.assert_not_called()
            callbacks[0]()
            rematch.assert_called_once_with(
                [ContactMethod.normalize_phone("09 111 1111")]
            )

    def test_unknown_company_update_returns_404_without_app_error(self) -> None:
        before = AppError.objects.count()

        response = self.client.patch(
            self._update_url(uuid.uuid4()),
            {"name": "Missing Company"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["error"].lower())
        self.assertEqual(AppError.objects.count(), before)

    def test_validation_error_returns_400_without_app_error(self) -> None:
        company = self._company()
        before = AppError.objects.count()

        response = self.client.patch(
            self._update_url(company.id),
            {"email": "not-an-email"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid input data", response.json()["error"].lower())
        self.assertEqual(AppError.objects.count(), before)

    def test_xero_update_failure_persists_once_and_returns_500(self) -> None:
        company = self._company()
        company.xero_contact_id = "xero-contact-id"
        company.save()
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.update_contact.return_value = ContactResult(
            success=False,
            error="RemoteDisconnected",
        )
        before = AppError.objects.count()

        with patch(
            "apps.company.services.company_rest_service.get_provider",
            return_value=provider,
        ):
            response = self.client.patch(
                self._update_url(company.id),
                {"name": "Acme Renamed"},
                format="json",
            )

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertEqual(payload["error"], "Error updating company")
        self.assertIn("RemoteDisconnected", payload["details"])
        self.assertEqual(AppError.objects.count(), before + 1)
        app_error = AppError.objects.latest("timestamp")
        self.assertEqual(payload["error_id"], str(app_error.id))

    def test_already_logged_update_failure_is_not_persisted_again(self) -> None:
        company = self._company()
        company.xero_contact_id = "xero-contact-id"
        company.save()
        before = AppError.objects.count()
        app_error = AppError.objects.create(
            message="upstream failure",
            app="company",
            file="company_rest_service.py",
            function="_update_company_in_xero",
        )

        with patch(
            "apps.company.services.company_rest_service.get_provider",
            side_effect=AlreadyLoggedException(
                RuntimeError("upstream failure"),
                app_error.id,
            ),
        ):
            response = self.client.patch(
                self._update_url(company.id),
                {"name": "Acme Renamed"},
                format="json",
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(AppError.objects.count(), before + 1)
        self.assertEqual(response.json()["error_id"], str(app_error.id))


class CompanyUpdateProviderFailureTests(BaseTestCase):
    """Service-level guard for ADR 0019 on update_company: Xero/system
    failures must persist to AppError and surface as AlreadyLoggedException
    at the service boundary, never ride the user-facing ValueError (400)
    path. Complements the HTTP-level 500/error_id tests above."""

    def _xero_synced_company(self) -> Company:
        return Company.objects.create(
            name="Acme Ltd",
            xero_contact_id="xero-contact-id",
            xero_last_modified=timezone.now(),
        )

    def test_failed_provider_push_persists_app_error(self) -> None:
        from apps.company.services.company_rest_service import CompanyRestService

        company = self._xero_synced_company()
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.update_contact.return_value = ContactResult(
            success=False, error="rate limited"
        )

        with patch(
            "apps.company.services.company_rest_service.get_provider",
            return_value=provider,
        ):
            with self.assertRaises(AlreadyLoggedException) as ctx:
                CompanyRestService.update_company(company.id, {"name": "Acme Renamed"})

        self.assertIn("Failed to update company", str(ctx.exception))
        self.assertEqual(AppError.objects.count(), 1)

    def test_missing_provider_token_persists_app_error(self) -> None:
        from apps.company.services.company_rest_service import CompanyRestService

        company = self._xero_synced_company()
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = None

        with patch(
            "apps.company.services.company_rest_service.get_provider",
            return_value=provider,
        ):
            with self.assertRaises(AlreadyLoggedException) as ctx:
                CompanyRestService.update_company(company.id, {"name": "Acme Renamed"})

        self.assertIn("authentication required", str(ctx.exception))
        self.assertEqual(AppError.objects.count(), 1)


class CompanyCreatePhoneTests(BaseTestCase):
    """Guards the phone entry restored on the create-company modal."""

    def _provider(self) -> MagicMock:
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.search_contact_by_name.return_value = None
        provider.create_contact.return_value = ContactResult(
            success=True, external_id="xero-contact-id", name="New Company"
        )
        return provider

    def _create(self, provider: MagicMock, **payload: str) -> Company:
        data: dict[str, str] = {"name": "New Company", "email": "", "address": ""}
        data.update(payload)
        with patch(
            "apps.company.services.company_rest_service.get_provider",
            return_value=provider,
        ):
            return CompanyRestService.create_company(data)

    def test_create_with_phone_creates_primary_company_method(self) -> None:
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                company = self._create(self._provider(), phone="09 777 7777")

        method = ContactMethod.objects.get(company=company)
        self.assertEqual(method.method_type, ContactMethod.MethodType.PHONE)
        self.assertEqual(method.value, "09 777 7777")
        self.assertTrue(method.is_primary)

    def test_create_without_phone_creates_no_methods(self) -> None:
        company = self._create(self._provider())

        self.assertEqual(ContactMethod.objects.filter(company=company).count(), 0)

    def test_create_with_conflicting_phone_rolls_back_company(self) -> None:
        owner = Company.objects.create(
            name="Owner Ltd", xero_last_modified=timezone.now()
        )
        ContactMethod.objects.create(
            company=owner,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 777 7777",
        )
        provider = self._provider()

        with self.assertRaises(AlreadyLoggedException) as ctx:
            self._create(provider, phone="09 777 7777")

        self.assertIn("already belongs", str(ctx.exception))
        self.assertFalse(Company.objects.filter(name="New Company").exists())
        provider.create_contact.assert_not_called()


class ContactMethodApiTests(BaseAPITestCase):
    def _company(self, name: str = "Acme Ltd") -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def test_list_paginates_phone_contact_methods(self) -> None:
        """Catches CRM calls page regressions that fetch every phone method."""
        self.client.force_authenticate(user=self.test_staff)
        company = self._company("Acme Ltd")
        for index in range(3):
            ContactMethod.objects.create(
                company=company,
                method_type=ContactMethod.MethodType.PHONE,
                value=f"021 555 10{index}",
            )

        response = self.client.get(
            "/api/companies/contact-methods/",
            {"method_type": "phone", "page_size": "2"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["page_size"], 2)
        self.assertEqual(payload["total_pages"], 2)
        self.assertEqual(len(payload["results"]), 2)

    def test_list_page_size_is_capped(self) -> None:
        """Catches accidental oversized contact-method responses."""
        self.client.force_authenticate(user=self.test_staff)
        company = self._company("Acme Ltd")
        for index in range(101):
            ContactMethod.objects.create(
                company=company,
                method_type=ContactMethod.MethodType.PHONE,
                value=f"021 555 {index:03d}",
            )

        response = self.client.get(
            "/api/companies/contact-methods/",
            {"method_type": "phone", "page_size": "250"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 101)
        self.assertEqual(payload["page_size"], 100)
        self.assertEqual(len(payload["results"]), 100)

    def test_updating_phone_contact_method_rematches_affected_calls(self) -> None:
        """Catches stale call ownership after a customer phone number changes."""
        self.client.force_authenticate(user=self.test_staff)
        company = self._company("Acme Ltd")
        method = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )
        old_call = self._call("old-number", origin="021 555 100", company=company)
        new_call = self._call("new-number", origin="021 555 200", company=None)

        with patch(
            "apps.company.views.contact_method_viewset."
            "rematch_phone_calls_task.delay",
            side_effect=rematch_calls_for_numbers,
        ) as rematch:
            response = self.client.patch(
                f"/api/companies/contact-methods/{method.id}/",
                {"value": "021 555 200"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        rematch.assert_called_once_with(["+6421555100", "+6421555200"])
        old_call.refresh_from_db()
        new_call.refresh_from_db()
        self.assertIsNone(old_call.company)
        self.assertEqual(new_call.company, company)

    def test_deleting_phone_contact_method_unmatches_affected_calls(self) -> None:
        """Catches deleted phone numbers continuing to own CRM calls."""
        self.client.force_authenticate(user=self.test_staff)
        company = self._company("Acme Ltd")
        method = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )
        call = self._call("deleted-number", origin="021 555 100", company=company)

        with patch(
            "apps.company.views.contact_method_viewset."
            "rematch_phone_calls_task.delay",
            side_effect=rematch_calls_for_numbers,
        ) as rematch:
            response = self.client.delete(
                f"/api/companies/contact-methods/{method.id}/"
            )

        self.assertEqual(response.status_code, 204)
        rematch.assert_called_once_with(["+6421555100"])
        call.refresh_from_db()
        self.assertIsNone(call.company)

    def _call(
        self,
        provider_id: str,
        *,
        origin: str,
        company: Company | None,
    ) -> PhoneCallRecord:
        call_datetime = timezone.now()
        return PhoneCallRecord.objects.create(
            provider_call_id=f"account:{provider_id}",
            account_code="account",
            call_datetime=call_datetime,
            call_date=timezone.localdate(),
            call_time=call_datetime.time(),
            origin=origin,
            destination="+6496365131",
            company=company,
            raw_json={
                "id": provider_id,
                "calldate": timezone.localdate().isoformat(),
                "calltime": call_datetime.time().isoformat(timespec="seconds"),
            },
        )
