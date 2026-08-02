"""Contact-method business rules and CRUD API (ported from v1 test_contact_methods.py).

Dropped from v1 (see port report): the nplusone Profiler harness (v2 has no
nplusone dependency); the query-shape behaviour it guarded is covered by the
serialization assertions here.
"""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.tests.conftest import make_company

pytestmark = pytest.mark.django_db


def _link(company: Company, name: str) -> CompanyPersonLink:
    person = Person.objects.create(name=name)
    return CompanyPersonLink.objects.create(company=company, person=person)


class TestContactMethodRules:
    def test_phone_normalization_matches_nz_variants(self) -> None:
        """Catches call matching failures when NZ local and E.164 numbers diverge."""
        assert ContactMethod.normalize_phone("+64 9 636 5131") == "+6496365131"
        assert ContactMethod.normalize_phone("09 636 5131") == "+6496365131"

    def test_primary_phone_is_single_per_company_owner(self) -> None:
        """Catches multiple primary phone numbers being left on a company record."""
        company = make_company("Acme Ltd")
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
        assert first.is_primary is False
        assert second.is_primary is True

    def test_primary_phone_is_single_per_contact_owner(self) -> None:
        company = make_company("Acme Ltd")
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
        assert first.is_primary is False
        assert second.is_primary is True

    def test_same_number_allowed_on_company_and_its_own_contact(self) -> None:
        """A company and its own contact sharing one line must not be rejected."""
        company = make_company("Acme Ltd")
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

        assert on_company.normalized_value == on_contact.normalized_value
        assert on_contact.pk is not None

    def test_same_number_allowed_on_two_contacts_of_same_company(self) -> None:
        """Two contacts of one company can share a number (one effective company)."""
        company = make_company("Acme Ltd")
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

        assert on_second.pk is not None

    def test_same_number_rejected_across_different_companies(self) -> None:
        """Two different companies cannot own one number; matching would be ambiguous."""
        company_a = make_company("Acme Ltd")
        company_b = make_company("Beta Ltd")
        ContactMethod.objects.create(
            company=company_a,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        with pytest.raises(ValidationError):
            ContactMethod.objects.create(
                company=company_b,
                method_type=ContactMethod.MethodType.PHONE,
                value="021 111 111",
            )

    def test_same_number_rejected_across_contacts_of_different_companies(self) -> None:
        company_a = make_company("Acme Ltd")
        company_b = make_company("Beta Ltd")
        contact_a = _link(company_a, "A")
        contact_b = _link(company_b, "B")
        ContactMethod.objects.create(
            person=contact_a.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        with pytest.raises(ValidationError):
            ContactMethod.objects.create(
                person=contact_b.person,
                method_type=ContactMethod.MethodType.PHONE,
                value="021 111 111",
            )

    def test_grandfathered_cross_company_number_can_be_resaved(self) -> None:
        """A pre-existing cross-company number (legacy data) re-saves unchanged."""
        company_a = make_company("Acme Ltd")
        company_b = make_company("Beta Ltd")
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
        assert legacy.label == "Mobile"

    def test_changing_number_into_another_companies_ownership_raises(self) -> None:
        """Editing a method's number onto another company's number is blocked."""
        company_a = make_company("Acme Ltd")
        company_b = make_company("Beta Ltd")
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
        with pytest.raises(ValidationError):
            moving.save()

    def test_partial_update_fields_still_persists_normalized_value(self) -> None:
        """save(update_fields=["value"]) must also persist the recomputed
        normalized_value, or the matching/uniqueness index goes stale."""
        company = make_company("Acme Ltd")
        method = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 111",
        )

        method.value = "021 222 222"
        method.save(update_fields=["value"])

        method.refresh_from_db()
        assert method.normalized_value == ContactMethod.normalize_phone("021 222 222")


class TestPrimaryPhoneHelpers:
    """Guards the helpers PO PDFs, Xero sync, and phone-bearing payloads use."""

    def test_primary_phone_value_returns_primary_first(self) -> None:
        company = make_company("Acme Ltd")
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

        assert company.primary_phone_value() == "09 222 2222"

    def test_primary_phone_value_empty_without_phone_methods(self) -> None:
        company = make_company("Phoneless Ltd")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.EMAIL,
            value="office@example.com",
        )

        assert company.primary_phone_value() == ""

    def test_company_annotation_prefers_primary_over_label_order(self) -> None:
        company = make_company("Acme Ltd")
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
            phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk")
        ).get(pk=company.pk)

        assert annotated.__dict__["phone"] == "09 222 2222"

    def test_company_annotation_is_empty_string_without_phones(self) -> None:
        company = make_company("Phoneless Ltd")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.EMAIL,
            value="office@example.com",
        )

        annotated = Company.objects.annotate(
            phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk")
        ).get(pk=company.pk)

        assert annotated.__dict__["phone"] == ""

    def test_contact_annotation_returns_contact_primary_phone(self) -> None:
        company = make_company("Acme Ltd")
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

        assert annotated.phone == "021 222 222"


@pytest.mark.urls("apps.company.tests.urls")
class TestContactMethodApi:
    def test_list_paginates_phone_contact_methods(self, client: Client) -> None:
        """Catches CRM calls page regressions that fetch every phone method."""
        company = make_company("Acme Ltd")
        for index in range(3):
            ContactMethod.objects.create(
                company=company,
                method_type=ContactMethod.MethodType.PHONE,
                value=f"021 555 10{index}",
            )

        response = client.get(
            "/api/companies/contact-methods/",
            {"method_type": "phone", "page_size": "2"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 3
        assert payload["page"] == 1
        assert payload["page_size"] == 2
        assert payload["total_pages"] == 2
        assert len(payload["results"]) == 2

    def test_list_serializes_person_owned_phone_methods(self, client: Client) -> None:
        """Catches CRM calls page 500s from person-owned phone numbers."""
        company = make_company("Acme Ltd")
        contact = _link(company, "Jane Smith")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )
        ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 200",
        )

        response = client.get(
            "/api/companies/contact-methods/",
            {"method_type": "phone", "page_size": "50"},
        )

        assert response.status_code == 200
        person_method = next(
            method for method in response.json()["results"] if method["person_name"] == "Jane Smith"
        )
        assert person_method["owner_company"] == str(company.id)
        assert person_method["company_name"] == "Acme Ltd"

    def test_list_filters_by_company_including_contact_methods(self, client: Client) -> None:
        company = make_company("Acme Ltd")
        other = make_company("Beta Ltd")
        contact = _link(company, "Jane Smith")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )
        ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 200",
        )
        ContactMethod.objects.create(
            company=other,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 300",
        )

        response = client.get("/api/companies/contact-methods/", {"company_id": str(company.id)})

        values = {row["value"] for row in response.json()["results"]}
        assert values == {"021 555 100", "021 555 200"}

    def test_list_page_size_is_capped(self, client: Client) -> None:
        """Catches accidental oversized contact-method responses."""
        company = make_company("Acme Ltd")
        methods = [
            ContactMethod(
                company=company,
                method_type=ContactMethod.MethodType.PHONE,
                value=f"021 555 {index:03d}",
                normalized_value=ContactMethod.normalize_phone(f"021 555 {index:03d}"),
            )
            for index in range(101)
        ]
        ContactMethod.objects.bulk_create(methods)

        response = client.get(
            "/api/companies/contact-methods/",
            {"method_type": "phone", "page_size": "250"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 101
        assert payload["page_size"] == 100
        assert len(payload["results"]) == 100

    def test_create_requires_exactly_one_owner(self, client: Client) -> None:
        company = make_company("Acme Ltd")
        contact = _link(company, "Jane Smith")

        both = client.post(
            "/api/companies/contact-methods/",
            {
                "company": str(company.id),
                "person": str(contact.person_id),
                "method_type": "phone",
                "value": "021 555 100",
            },
            content_type="application/json",
        )
        neither = client.post(
            "/api/companies/contact-methods/",
            {"method_type": "phone", "value": "021 555 100"},
            content_type="application/json",
        )

        assert both.status_code == 400
        assert "Exactly one of company or person" in both.json()["detail"]
        assert neither.status_code == 400

    def test_create_conflicting_number_is_rejected(self, client: Client) -> None:
        company_a = make_company("Acme Ltd")
        company_b = make_company("Beta Ltd")
        ContactMethod.objects.create(
            company=company_a,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )

        response = client.post(
            "/api/companies/contact-methods/",
            {
                "company": str(company_b.id),
                "method_type": "phone",
                "value": "0215 55100",
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "already belongs" in response.json()["detail"]
        assert not ContactMethod.objects.filter(company=company_b).exists()

    def test_updating_phone_contact_method_schedules_rematch_of_both_numbers(
        self, client: Client, django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks
    ) -> None:
        """Catches stale call ownership after a customer phone number changes."""
        company = make_company("Acme Ltd")
        method = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )

        with (
            patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.patch(
                f"/api/companies/contact-methods/{method.id}/",
                {"value": "021 555 200"},
                content_type="application/json",
            )

        assert response.status_code == 200
        rematch.assert_called_once_with(["+6421555100", "+6421555200"])

    def test_deleting_phone_contact_method_schedules_rematch(
        self, client: Client, django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks
    ) -> None:
        """Catches deleted phone numbers continuing to own CRM calls."""
        company = make_company("Acme Ltd")
        method = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )

        with (
            patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.delete(f"/api/companies/contact-methods/{method.id}/")

        assert response.status_code == 204
        rematch.assert_called_once_with(["+6421555100"])

    def test_crud_roundtrip(self, client: Client) -> None:
        company = make_company("Acme Ltd")

        created = client.post(
            "/api/companies/contact-methods/",
            {
                "company": str(company.id),
                "method_type": "phone",
                "value": "021 555 100",
                "label": "Office",
                "is_primary": True,
            },
            content_type="application/json",
        )
        assert created.status_code == 201
        method_id = created.json()["id"]
        assert created.json()["normalized_value"] == "+6421555100"
        assert created.json()["company_name"] == "Acme Ltd"

        fetched = client.get(f"/api/companies/contact-methods/{method_id}/")
        assert fetched.status_code == 200
        assert fetched.json()["label"] == "Office"

        patched = client.patch(
            f"/api/companies/contact-methods/{method_id}/",
            {"value": "021 555 200"},
            content_type="application/json",
        )
        assert patched.status_code == 200
        assert patched.json()["normalized_value"] == "+6421555200"

        deleted = client.delete(f"/api/companies/contact-methods/{method_id}/")
        assert deleted.status_code == 204
        assert not ContactMethod.objects.filter(id=method_id).exists()
