"""API tests for the company CRUD/search endpoints.

Covers phone updates, list rendering, and the main CRUD flows through the
Django test client.
"""

from typing import TYPE_CHECKING

import pytest
from django.test import Client

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

from apps.accounts.models import Staff
from apps.company.models import Company, ContactMethod, SupplierPickupAddress
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.company.tests.urls"),
]


def _phone_values(company: Company) -> list[tuple[str, bool]]:
    return list(
        ContactMethod.objects.filter(
            company=company, method_type=ContactMethod.MethodType.PHONE
        ).values_list("value", "is_primary")
    )


class TestAuth:
    def test_endpoints_require_auth(self) -> None:
        anonymous = Client()
        assert anonymous.get("/api/companies/all/").status_code == 401

    def test_people_endpoints_require_office_staff(self, workshop_staff: Staff) -> None:
        company = make_company("Acme")
        client = Client()
        authenticate(client, workshop_staff)
        response = client.get(f"/api/companies/{company.id}/people/")
        assert response.status_code == 403
        # Non-office staff can still use the plain company endpoints.
        assert client.get("/api/companies/all/").status_code == 200


class TestListAndRetrieve:
    def test_all_list_returns_id_and_name_sorted(self, client: Client) -> None:
        make_company("Zeta")
        make_company("Acme")

        response = client.get("/api/companies/all/")

        assert response.status_code == 200
        rows = response.json()
        # Sortedness asserted over the rows this test owns rather than the whole
        # table: every install carries a shop company, so an exact list was
        # asserting a state no real instance is ever in.
        names = [row["name"] for row in rows]
        assert names == sorted(names)
        assert names.index("Acme") < names.index("Zeta")
        assert set(rows[0]) == {"id", "name"}

    def test_search_returns_v1_pagination_envelope(self, client: Client) -> None:
        make_company("Acme Engineering")

        # Scoped by query rather than asserting the whole table: every install
        # carries a shop company, so "the only row" was never a real state.
        response = client.get("/api/companies/search/", {"q": "Acme"})

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 50
        assert body["total_pages"] == 1
        row = body["results"][0]
        assert row["name"] == "Acme Engineering"
        assert row["phone"] == ""
        assert row["total_spend"] == "$0.00"

    def test_search_rows_include_primary_phone(self, client: Client) -> None:
        company = make_company("Acme Engineering")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 0000",
            is_primary=True,
        )

        response = client.get("/api/companies/search/", {"q": "Acme"})

        assert response.json()["results"][0]["phone"] == "09 555 0000"

    def test_search_page_size_is_clamped_to_max(self, client: Client) -> None:
        """An absurd page_size must clamp to MAX_PAGE_SIZE (100) in the envelope."""
        make_company("Acme Engineering")

        response = client.get("/api/companies/search/", {"page_size": "100000"})

        assert response.status_code == 200
        body = response.json()
        assert body["page_size"] == 100
        assert len(body["results"]) <= 100

    def test_merged_tombstone_is_excluded_from_browse(self, client: Client) -> None:
        winner = make_company("Winner Ltd")
        loser = make_company("Loser Ltd")
        loser.merged_into = winner
        loser.save(update_fields=["merged_into"])

        response = client.get("/api/companies/search/")

        names = [row["name"] for row in response.json()["results"]]
        assert "Winner Ltd" in names
        assert "Loser Ltd" not in names
        # ...but stays reachable by id on the detail endpoint (ADR 0034).
        assert client.get(f"/api/companies/{loser.id}/").status_code == 200

    def test_retrieve_returns_full_detail(self, client: Client) -> None:
        company = make_company("Acme Engineering", address="1 Way St", email="a@acme.nz")

        response = client.get(f"/api/companies/{company.id}/")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(company.id)
        assert body["name"] == "Acme Engineering"
        assert body["email"] == "a@acme.nz"
        assert body["address"] == "1 Way St"
        assert body["phone"] == ""
        assert body["merged_into"] is None
        assert body["total_spend"] == "$0.00"

    def test_retrieve_unknown_company_is_404(self, client: Client) -> None:
        response = client.get("/api/companies/00000000-0000-0000-0000-000000000000/")
        assert response.status_code == 404


class TestUpdate:
    """Phone-update behavior for local, non-Xero-synced companies."""

    def _update(
        self, client: Client, company: Company, payload: dict[str, object]
    ) -> "_MonkeyPatchedWSGIResponse":
        return client.patch(
            f"/api/companies/{company.id}/update/",
            payload,
            content_type="application/json",
        )

    def test_update_renames_company(self, client: Client) -> None:
        company = make_company("Old Name")

        response = self._update(client, company, {"name": "New Name"})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["company"]["name"] == "New Name"
        company.refresh_from_db()
        assert company.name == "New Name"

    def test_explicit_null_is_rejected_not_silently_dropped(self, client: Client) -> None:
        """`{"name": null}` must fail, not return 200 having changed nothing.

        v1 declares these fields non-nullable, so v2 admitting null is a
        weakened contract — and the handler papered over it with an
        `is not None` guard that dropped the field on the floor. Omission
        still means "leave it alone"; that is what `exclude_unset` is for.
        """
        company = make_company(
            "Acme",
            allow_jobs=True,
            is_account_customer=True,
            address="12 Original Street",
        )

        for field in ("name", "allow_jobs", "is_account_customer", "address"):
            response = self._update(client, company, {field: None})
            assert response.status_code == 422, f"{field}=null was accepted"

        # The rejection is the schema's, so the handler never runs and nothing
        # could have been written; these assertions guard the 422 being real
        # rather than a 200 relabelled. The handler's own presence-reading is
        # what test_omitted_fields_keep_their_stored_values covers.
        company.refresh_from_db()
        assert company.name == "Acme"
        assert company.allow_jobs is True
        assert company.is_account_customer is True
        assert company.address == "12 Original Street"

    def test_omitted_fields_keep_their_stored_values(self, client: Client) -> None:
        """A one-field PATCH must not write placeholders over everything else.

        `omittable()` leaves a placeholder in the attribute — `""` for text,
        `False` for a flag — so `payload.address` reads `""` on a request that
        never mentioned address. Only `model_fields_set` distinguishes that from
        a client genuinely sending `""`. Each starting value below therefore
        differs from its field's PLACEHOLDER, not merely from the model default,
        which for allow_jobs is True either way and would hide the bug.
        """
        company = make_company(
            "Acme",
            allow_jobs=True,
            is_account_customer=True,
            address="12 Original Street",
        )

        response = self._update(client, company, {"name": "Acme Renamed"})

        assert response.status_code == 200
        company.refresh_from_db()
        assert company.name == "Acme Renamed"
        assert company.address == "12 Original Street"
        assert company.is_account_customer is True
        assert company.allow_jobs is True

    def test_explicit_blank_name_is_rejected(self, client: Client) -> None:
        """Regression: an empty name must not silently blank the company.

        Rejected at validation (422) rather than by the service (400). v1's
        serializer declares `minLength: 1` and so refused a blank at the same
        point; v2 previously let it past the schema and caught it downstream.
        422-for-validation is the recorded envelope-wide convention.
        """
        company = make_company("Acme")

        patched = self._update(client, company, {"name": ""})

        assert patched.status_code == 422
        company.refresh_from_db()
        assert company.name == "Acme"

        put = client.put(
            f"/api/companies/{company.id}/update/",
            {"name": ""},
            content_type="application/json",
        )
        assert put.status_code == 422
        company.refresh_from_db()
        assert company.name == "Acme"

        # The guard rejects explicit blanks only — a real rename still works.
        renamed = self._update(client, company, {"name": "Acme Renamed"})
        assert renamed.status_code == 200
        company.refresh_from_db()
        assert company.name == "Acme Renamed"

    def test_update_with_new_phone_creates_primary_method(self, client: Client) -> None:
        company = make_company("Acme")

        response = self._update(client, company, {"phone": "09 555 1234"})

        assert response.status_code == 200
        assert response.json()["company"]["phone"] == "09 555 1234"
        assert _phone_values(company) == [("09 555 1234", True)]

    def test_update_with_existing_secondary_number_promotes_it(self, client: Client) -> None:
        company = make_company("Acme")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 1111",
            is_primary=True,
        )
        secondary = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 2222",
        )

        response = self._update(client, company, {"phone": "095552222"})

        assert response.status_code == 200
        secondary.refresh_from_db()
        assert secondary.is_primary
        assert (
            ContactMethod.objects.filter(
                company=company,
                method_type=ContactMethod.MethodType.PHONE,
                is_primary=True,
            ).count()
            == 1
        )

    def test_update_renumbers_current_primary_when_number_is_new(self, client: Client) -> None:
        company = make_company("Acme")
        primary = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 1111",
            is_primary=True,
        )

        response = self._update(client, company, {"phone": "09 555 9999"})

        assert response.status_code == 200
        primary.refresh_from_db()
        assert primary.value == "09 555 9999"
        assert primary.is_primary
        assert (
            ContactMethod.objects.filter(
                company=company, method_type=ContactMethod.MethodType.PHONE
            ).count()
            == 1
        )

    def test_blank_phone_clears_primary_method(self, client: Client) -> None:
        company = make_company("Acme")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 1111",
            is_primary=True,
        )

        response = self._update(client, company, {"phone": ""})

        assert response.status_code == 200
        assert _phone_values(company) == []

    def test_omitted_phone_leaves_methods_untouched(self, client: Client) -> None:
        company = make_company("Acme")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 1111",
            is_primary=True,
        )

        response = self._update(client, company, {"name": "Acme Renamed"})

        assert response.status_code == 200
        assert _phone_values(company) == [("09 555 1111", True)]

    def test_conflicting_phone_returns_400_and_rolls_back_update(self, client: Client) -> None:
        other = make_company("Other Co")
        ContactMethod.objects.create(
            company=other,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 7777",
        )
        company = make_company("Acme")

        response = self._update(client, company, {"name": "Acme Renamed", "phone": "0955 57777"})

        assert response.status_code == 400
        assert "already belongs" in response.json()["detail"]
        company.refresh_from_db()
        assert company.name == "Acme"  # atomic: the rename rolled back too
        assert _phone_values(company) == []

    def test_unknown_company_update_returns_404(self, client: Client) -> None:
        missing = client.patch(
            "/api/companies/00000000-0000-0000-0000-000000000000/update/",
            {"name": "x"},
            content_type="application/json",
        )

        assert missing.status_code == 404

    def test_invalid_email_is_rejected(self, client: Client) -> None:
        company = make_company("Acme")

        response = self._update(client, company, {"email": "not-an-email"})

        assert response.status_code == 422

    def test_xero_synced_update_is_blocked_until_phase4(self, client: Client) -> None:
        """Phase gap: pushing updates to Xero is Phase 4; nothing is written."""
        company = make_company("Synced Co", xero_contact_id="X-123")

        response = self._update(client, company, {"name": "Renamed"})

        assert response.status_code == 500
        assert "Phase 4" in response.json()["detail"]
        company.refresh_from_db()
        assert company.name == "Synced Co"


class TestCreate:
    def test_create_is_blocked_until_phase4_provider_port(self, client: Client) -> None:
        """Creating a synced company must fail loudly while its provider seam is absent."""
        before = Company.objects.count()

        response = client.post(
            "/api/companies/create/",
            {"name": "New Co"},
            content_type="application/json",
        )

        assert response.status_code == 500
        assert "Phase 4" in response.json()["detail"]
        assert Company.objects.count() == before


class TestCompanyJobs:
    def test_jobs_for_unknown_company_is_404(self, client: Client) -> None:
        response = client.get("/api/companies/00000000-0000-0000-0000-000000000000/jobs/")
        assert response.status_code == 404

    def test_company_without_jobs_returns_empty_results(self, client: Client) -> None:
        company = make_company("Acme")
        response = client.get(f"/api/companies/{company.id}/jobs/")
        assert response.status_code == 200
        assert response.json() == {"results": []}

    def test_company_jobs_returns_header_rows(self, client: Client, office_staff: Staff) -> None:
        company = make_company("Acme")
        job = make_job(company, office_staff, name="Fabricate thing")

        response = client.get(f"/api/companies/{company.id}/jobs/")

        assert response.status_code == 200
        rows = response.json()["results"]
        assert len(rows) == 1
        assert rows[0]["job_id"] == str(job.id)
        assert rows[0]["name"] == "Fabricate thing"
        assert rows[0]["company"] == {"id": str(company.id), "name": "Acme"}
        assert rows[0]["job_number"] == job.job_number


class TestSupplierAliases:
    def test_alias_create_list_and_soft_delete(self, client: Client) -> None:
        company = make_company("Acme Supplies")

        created = client.post(
            f"/api/companies/{company.id}/supplier-aliases/",
            {"alias": "  ACME  "},
            content_type="application/json",
        )
        assert created.status_code == 201
        assert created.json()["alias"] == "ACME"

        listed = client.get(f"/api/companies/{company.id}/supplier-aliases/")
        assert [row["alias"] for row in listed.json()] == ["ACME"]

        deleted = client.delete(f"/api/companies/supplier-aliases/{created.json()['id']}/")
        assert deleted.status_code == 204
        assert client.get(f"/api/companies/{company.id}/supplier-aliases/").json() == []

    def test_recreating_deactivated_alias_reactivates_it(self, client: Client) -> None:
        company = make_company("Acme Supplies")
        created = client.post(
            f"/api/companies/{company.id}/supplier-aliases/",
            {"alias": "ACME"},
            content_type="application/json",
        )
        client.delete(f"/api/companies/supplier-aliases/{created.json()['id']}/")

        recreated = client.post(
            f"/api/companies/{company.id}/supplier-aliases/",
            {"alias": "ACME"},
            content_type="application/json",
        )

        assert recreated.status_code == 201
        assert recreated.json()["id"] == created.json()["id"]
        assert recreated.json()["is_active"] is True

    def test_blank_alias_is_rejected(self, client: Client) -> None:
        company = make_company("Acme Supplies")
        response = client.post(
            f"/api/companies/{company.id}/supplier-aliases/",
            {"alias": "   "},
            content_type="application/json",
        )
        assert response.status_code == 422


class TestPickupAddresses:
    def _create(
        self, client: Client, company: Company, **overrides: object
    ) -> "_MonkeyPatchedWSGIResponse":
        payload: dict[str, object] = {
            "company": str(company.id),
            "name": "Main Warehouse",
            "street": "12 Depot Road",
            "city": "Auckland",
        }
        payload.update(overrides)
        return client.post(
            "/api/companies/pickup-addresses/", payload, content_type="application/json"
        )

    def test_unsent_nullable_fields_are_null(self, client: Client) -> None:
        company = make_company("Acme Supplies")

        response = self._create(client, company)

        assert response.status_code == 201
        body = response.json()
        assert body["suburb"] is None
        assert body["formatted_address"] == "12 Depot Road, Auckland"

    @pytest.mark.parametrize(
        "field", ["suburb", "state", "postal_code", "google_place_id", "notes"]
    )
    def test_blank_nullable_text_is_a_validation_error(self, client: Client, field: str) -> None:
        """Unset is NULL (ADR 0040): "" is refused at the schema, same as PO lines.

        v1 coerced blanks serializer-side for exactly these fields; the corrected
        contract is ledgered with the stock and product-mapping entries.
        """
        company = make_company("Acme Supplies")

        response = self._create(client, company, **{field: ""})

        assert response.status_code == 422, f"{field} blank should be a validation error"
        assert SupplierPickupAddress.objects.count() == 0

    def test_whitespace_only_text_is_blank_too(self, client: Client) -> None:
        """NullableText strips before the length check; "  " must not sneak past
        the *_not_blank constraints, which only reject the exact empty string."""
        company = make_company("Acme Supplies")

        response = self._create(client, company, suburb="  \t ")

        assert response.status_code == 422
        assert SupplierPickupAddress.objects.count() == 0

    def test_explicit_null_clears_a_nullable_text_field(self, client: Client) -> None:
        company = make_company("Acme Supplies")
        created = self._create(client, company, suburb="Thorndon").json()

        response = client.patch(
            f"/api/companies/pickup-addresses/{created['id']}/",
            {"suburb": None},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert SupplierPickupAddress.objects.get(id=created["id"]).suburb is None

    def test_second_primary_demotes_the_first(self, client: Client) -> None:
        company = make_company("Acme Supplies")
        first = self._create(client, company, name="First", is_primary=True).json()
        second = self._create(client, company, name="Second", is_primary=True).json()

        listed = client.get(
            "/api/companies/pickup-addresses/", {"supplier_id": str(company.id)}
        ).json()

        primary_flags = {row["name"]: row["is_primary"] for row in listed}
        assert primary_flags == {"First": False, "Second": True}
        assert first["is_primary"] and second["is_primary"]

    def test_destroy_is_soft_delete(self, client: Client) -> None:
        company = make_company("Acme Supplies")
        created = self._create(client, company).json()

        deleted = client.delete(f"/api/companies/pickup-addresses/{created['id']}/")

        assert deleted.status_code == 204
        assert client.get("/api/companies/pickup-addresses/").json() == []
        # Row still exists, just deactivated.
        assert SupplierPickupAddress.objects.get(id=created["id"]).is_active is False

    def test_duplicate_name_for_company_is_400(self, client: Client) -> None:
        company = make_company("Acme Supplies")
        assert self._create(client, company).status_code == 201

        duplicate = self._create(client, company)

        assert duplicate.status_code == 400
