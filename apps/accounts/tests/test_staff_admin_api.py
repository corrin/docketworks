"""API tests for staff create and partial update.

POST /api/accounts/staff/ and PATCH /api/accounts/staff/{staff_id}/ are the
staff admin screen's write path. Superuser only — the office-staff gate v1
carried let any office member grant themselves superuser, so the auth tests
here pin the hole shut.
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

URL = "/api/accounts/staff/"
DETAIL_URL = "/api/accounts/staff/{id}/"
PASSWORD = "s3cret-Pass!"

CREATE_PAYLOAD = {
    "office_email": "new.person@example.com",
    "first_name": "New",
    "last_name": "Person",
    "password": "AnotherPass-42!",
}


def make_staff(email: str, **extra: object) -> Staff:
    return Staff.objects.create_user(
        office_email=email,
        password=PASSWORD,
        first_name=str(extra.pop("first_name", "Test")),
        last_name=str(extra.pop("last_name", "Person")),
        **extra,
    )


def client_for(staff: Staff) -> Client:
    client = Client()
    authenticate(client, staff)
    return client


def superuser_client() -> Client:
    return client_for(make_staff("super@example.com", is_superuser=True, is_office_staff=True))


def create(client: Client, **overrides: object) -> "_MonkeyPatchedWSGIResponse":
    return client.post(URL, data={**CREATE_PAYLOAD, **overrides}, content_type="application/json")


def patch(client: Client, staff_id: object, **fields: object) -> "_MonkeyPatchedWSGIResponse":
    return client.patch(
        DETAIL_URL.format(id=staff_id), data=fields, content_type="application/json"
    )


class TestAuth:
    def test_anonymous_cannot_create(self) -> None:
        assert (
            Client().post(URL, data=CREATE_PAYLOAD, content_type="application/json").status_code
            == 401
        )

    def test_office_staff_cannot_create(self) -> None:
        office = make_staff("office@example.com", is_office_staff=True)
        assert create(client_for(office)).status_code == 403

    def test_anonymous_cannot_update(self) -> None:
        target = make_staff("target@example.com")
        assert (
            Client()
            .patch(DETAIL_URL.format(id=target.id), data={}, content_type="application/json")
            .status_code
            == 401
        )

    def test_office_staff_cannot_update(self) -> None:
        """The v1 escalation hole: office staff could PATCH is_superuser onto
        themselves because the API gate was is_office_staff. Superuser only."""
        office = make_staff("office@example.com", is_office_staff=True)
        response = patch(client_for(office), office.id, is_superuser=True)
        assert response.status_code == 403
        office.refresh_from_db()
        assert office.is_superuser is False


class TestPasswordValidators:
    """AUTH_PASSWORD_VALIDATORS reach every set-password surface through
    _set_staff_password; a weak value must be a 400 whose message names the
    failed rule (ADR 0038 — the admin fixes the password, not a code)."""

    def test_a_common_password_is_rejected(self) -> None:
        response = create(superuser_client(), password="password")

        assert response.status_code == 400
        assert "too common" in response.json()["detail"]
        assert not Staff.objects.filter(office_email="new.person@example.com").exists()

    def test_a_password_similar_to_the_email_is_rejected(self) -> None:
        response = create(superuser_client(), password="new.person@example.com")

        assert response.status_code == 400
        assert "too similar" in response.json()["detail"]

    def test_an_entirely_numeric_password_is_rejected_on_patch(self) -> None:
        target = make_staff("target@example.com")

        response = patch(superuser_client(), target.id, password="1234567890")

        assert response.status_code == 400
        assert "entirely numeric" in response.json()["detail"]
        target.refresh_from_db()
        assert target.check_password(PASSWORD)


class TestCreate:
    def test_creates_a_staff_member_with_a_usable_password(self) -> None:
        response = create(superuser_client())

        assert response.status_code == 201
        body = response.json()
        created = Staff.objects.get(pk=body["id"])
        assert created.office_email == "new.person@example.com"
        assert created.check_password("AnotherPass-42!")
        assert body["date_left"] is None

    def test_model_defaults_apply_to_omitted_fields(self) -> None:
        response = create(superuser_client())

        created = Staff.objects.get(pk=response.json()["id"])
        assert created.hours_mon == Decimal("8.00")
        assert created.hours_sun == Decimal("0.00")
        assert created.is_workshop_staff is True
        assert created.employment_start_date is not None
        assert created.default_labour_subtype is not None

    def test_wage_rate_is_derived_from_base_wage_rate(self) -> None:
        response = create(superuser_client(), base_wage_rate="40.00")

        created = Staff.objects.get(pk=response.json()["id"])
        assert created.base_wage_rate == Decimal("40.00")
        assert created.wage_rate > created.base_wage_rate  # loading > 0 in fixture defaults

    def test_wage_rate_in_the_payload_is_rejected(self) -> None:
        """wage_rate is derived; a client sending it must get a 422, not silence."""
        assert create(superuser_client(), wage_rate="99.00").status_code == 422

    def test_missing_password_is_rejected(self) -> None:
        payload = {k: v for k, v in CREATE_PAYLOAD.items() if k != "password"}
        response = superuser_client().post(URL, data=payload, content_type="application/json")
        assert response.status_code == 422

    def test_blank_preferred_name_is_rejected(self) -> None:
        assert create(superuser_client(), preferred_name="").status_code == 422

    def test_unknown_pay_basis_is_rejected(self) -> None:
        assert create(superuser_client(), pay_basis="weekly").status_code == 422

    def test_duplicate_office_email_is_a_400(self) -> None:
        make_staff("new.person@example.com")
        assert create(superuser_client()).status_code == 400

    def test_case_variant_duplicate_office_email_is_a_400(self) -> None:
        """StaffEmailBackend matches office_email with iexact and returns None
        on multiple hits, so a case-variant duplicate silently locks BOTH
        accounts out of login — it must be refused at write time."""
        make_staff("new.person@example.com")
        assert create(superuser_client(), office_email="New.Person@example.com").status_code == 400

    def test_duplicate_payroll_email_is_a_400(self) -> None:
        make_staff("other@example.com", payroll_email="pay@example.com")
        assert create(superuser_client(), payroll_email="pay@example.com").status_code == 400

    def test_duplicate_xero_user_id_is_a_400(self) -> None:
        make_staff("other@example.com", xero_user_id="11111111-2222-3333-4444-555555555555")
        response = create(superuser_client(), xero_user_id="11111111-2222-3333-4444-555555555555")
        assert response.status_code == 400

    def test_negative_base_wage_rate_is_rejected(self) -> None:
        assert create(superuser_client(), base_wage_rate="-5").status_code == 422

    def test_negative_hours_are_rejected(self) -> None:
        assert create(superuser_client(), hours_mon="-1").status_code == 422

    def test_payroll_only_create_succeeds(self) -> None:
        """Wage staff often have no office mailbox; the payroll address alone
        is enough (owner ruling, 2026-08-26)."""
        payload = {k: v for k, v in CREATE_PAYLOAD.items() if k != "office_email"}
        payload["payroll_email"] = "wage@example.com"

        response = superuser_client().post(URL, data=payload, content_type="application/json")

        assert response.status_code == 201
        body = response.json()
        assert body["office_email"] is None
        created = Staff.objects.get(pk=body["id"])
        assert created.office_email is None
        assert created.payroll_email == "wage@example.com"

    def test_no_email_at_all_is_a_400_naming_email(self) -> None:
        payload = {k: v for k, v in CREATE_PAYLOAD.items() if k != "office_email"}

        response = superuser_client().post(URL, data=payload, content_type="application/json")

        assert response.status_code == 400
        assert "email" in response.json()["detail"].lower()

    def test_blank_office_email_is_a_422(self) -> None:
        assert create(superuser_client(), office_email="").status_code == 422

    def test_staff_manager_true_creates_and_joins_the_group(self) -> None:
        response = create(superuser_client(), is_staff_manager=True)

        assert response.status_code == 201
        assert response.json()["is_staff_manager"] is True
        created = Staff.objects.get(pk=response.json()["id"])
        assert created.groups.filter(name="StaffManager").exists()

    def test_password_needs_reset_true_survives_the_password_set(self) -> None:
        """An admin may issue a known temporary password and force its change;
        the explicit flag must outlive _set_staff_password's clear."""
        response = create(superuser_client(), password_needs_reset=True)

        assert response.status_code == 201
        created = Staff.objects.get(pk=response.json()["id"])
        assert created.password_needs_reset is True


class TestPartialUpdate:
    def test_a_single_field_patch_leaves_the_rest_alone(self) -> None:
        target = make_staff("target@example.com", first_name="Tara", is_office_staff=True)

        response = patch(superuser_client(), target.id, preferred_name="T")

        assert response.status_code == 200
        target.refresh_from_db()
        assert target.preferred_name == "T"
        assert target.first_name == "Tara"
        assert target.is_office_staff is True

    def test_password_omitted_leaves_the_hash_unchanged(self) -> None:
        target = make_staff("target@example.com")
        before = target.password

        patch(superuser_client(), target.id, first_name="Renamed")

        target.refresh_from_db()
        assert target.password == before

    def test_password_supplied_changes_it(self) -> None:
        target = make_staff("target@example.com")

        response = patch(superuser_client(), target.id, password="Fresh-Pass-9!")

        assert response.status_code == 200
        target.refresh_from_db()
        assert target.check_password("Fresh-Pass-9!")

    def test_password_null_is_a_422(self) -> None:
        """null is never a password value: only omission means "unchanged"."""
        target = make_staff("target@example.com")
        assert patch(superuser_client(), target.id, password=None).status_code == 422

    def test_a_set_password_clears_password_needs_reset(self) -> None:
        """This is the one set-password surface; a fresh admin-set password
        must not leave the account flagged forever."""
        target = make_staff("target@example.com", password_needs_reset=True)

        patch(superuser_client(), target.id, password="Fresh-Pass-9!")

        target.refresh_from_db()
        assert target.password_needs_reset is False

    def test_a_patch_without_password_keeps_the_reset_flag(self) -> None:
        target = make_staff("target@example.com", password_needs_reset=True)

        patch(superuser_client(), target.id, first_name="Renamed")

        target.refresh_from_db()
        assert target.password_needs_reset is True

    def test_patching_the_flag_true_forces_a_change_at_next_login(self) -> None:
        target = make_staff("target@example.com")

        response = patch(superuser_client(), target.id, password_needs_reset=True)

        assert response.status_code == 200
        target.refresh_from_db()
        assert target.password_needs_reset is True

    def test_an_explicit_flag_wins_over_a_password_sets_clear(self) -> None:
        """_set_staff_password runs before _apply_staff_fields, so an admin
        sending a temporary password plus the flag gets both: the new
        password, still flagged for change."""
        target = make_staff("target@example.com")

        response = patch(
            superuser_client(), target.id, password="Fresh-Pass-9!", password_needs_reset=True
        )

        assert response.status_code == 200
        target.refresh_from_db()
        assert target.check_password("Fresh-Pass-9!")
        assert target.password_needs_reset is True

    def test_setting_date_left_offboards(self) -> None:
        target = make_staff("target@example.com")

        patch(superuser_client(), target.id, date_left="2026-01-31")

        target.refresh_from_db()
        assert target.date_left == date(2026, 1, 31)

    def test_null_date_left_reinstates(self) -> None:
        target = make_staff("target@example.com", date_left=date(2026, 1, 31))

        patch(superuser_client(), target.id, date_left=None)

        target.refresh_from_db()
        assert target.date_left is None

    def test_omitted_date_left_is_untouched(self) -> None:
        target = make_staff("target@example.com", date_left=date(2026, 1, 31))

        patch(superuser_client(), target.id, first_name="Renamed")

        target.refresh_from_db()
        assert target.date_left == date(2026, 1, 31)

    def test_base_wage_rate_patch_rederives_wage_rate(self) -> None:
        """The regression a partial save would hide: Staff.save() only computes
        wage_rate when update_fields is None or includes base_wage_rate, so the
        handler must issue a full save."""
        target = make_staff("target@example.com", base_wage_rate=Decimal("30.00"))

        patch(superuser_client(), target.id, base_wage_rate="50.00")

        target.refresh_from_db()
        assert target.wage_rate > Decimal("50.00")

    def test_staff_manager_add_remove_and_omit(self) -> None:
        target = make_staff("target@example.com")
        admin = superuser_client()

        patch(admin, target.id, is_staff_manager=True)
        assert target.groups.filter(name="StaffManager").exists()

        patch(admin, target.id, first_name="Still")  # omitted: membership untouched
        assert target.groups.filter(name="StaffManager").exists()

        patch(admin, target.id, is_staff_manager=False)
        assert not target.groups.filter(name="StaffManager").exists()

    def test_response_staff_manager_is_raw_membership_not_effective_privilege(self) -> None:
        """is_staff_manager() the model method folds in is_superuser; the wire
        field must be raw membership or editing a superuser would silently
        enrol them in the group on round-trip."""
        target = make_staff("target@example.com", is_superuser=True)

        response = patch(superuser_client(), target.id, first_name="Renamed")

        assert response.json()["is_staff_manager"] is False
        assert not target.groups.filter(name="StaffManager").exists()

    def test_unknown_staff_is_a_404(self) -> None:
        response = patch(superuser_client(), "00000000-0000-0000-0000-000000000000", first_name="X")
        assert response.status_code == 404

    def test_duplicate_office_email_is_a_400(self) -> None:
        make_staff("taken@example.com")
        target = make_staff("target@example.com")

        response = patch(superuser_client(), target.id, office_email="taken@example.com")

        assert response.status_code == 400

    def test_clearing_office_email_with_payroll_present_succeeds(self) -> None:
        target = make_staff("target@example.com", payroll_email="wage@example.com")

        response = patch(superuser_client(), target.id, office_email=None)

        assert response.status_code == 200
        target.refresh_from_db()
        assert target.office_email is None

    def test_clearing_the_only_email_is_a_400(self) -> None:
        """The at-least-one rule must surface as a readable refusal, not an
        IntegrityError 500."""
        target = make_staff("target@example.com")

        response = patch(superuser_client(), target.id, office_email=None)

        assert response.status_code == 400
        assert "email" in response.json()["detail"].lower()
        target.refresh_from_db()
        assert target.office_email == "target@example.com"


class TestListExtensions:
    def test_the_list_carries_the_edit_modal_fields(self) -> None:
        """The edit modal is populated from the list row (no retrieve
        endpoint), so the admin fields must all be present."""
        make_staff(
            "detail@example.com",
            preferred_name="Dee",
            xero_user_id="11111111-2222-3333-4444-555555555555",
        )

        body = superuser_client().get(URL).json()

        row = next(item for item in body if item["office_email"] == "detail@example.com")
        assert row["preferred_name"] == "Dee"
        # display_name is the server's one naming rule (first word of the
        # preferred name); the client must never re-derive it.
        assert row["display_name"] == "Dee Person"
        assert row["xero_user_id"] == "11111111-2222-3333-4444-555555555555"
        assert row["is_workshop_staff"] is True
        assert row["is_superuser"] is False
        assert row["is_staff_manager"] is False
        assert Decimal(str(row["hours_mon"])) == Decimal("8.00")
        assert Decimal(str(row["hours_sun"])) == Decimal("0.00")
        assert row["icon_url"] is None

    def test_the_list_reflects_group_membership(self) -> None:
        member = make_staff("manager@example.com")
        group, _ = Group.objects.get_or_create(name="StaffManager")
        member.groups.add(group)

        body = superuser_client().get(URL).json()

        row = next(item for item in body if item["office_email"] == "manager@example.com")
        assert row["is_staff_manager"] is True
