"""API tests for form acknowledgements.

An acknowledgement is self-only: the POST takes no body at all, and
``staff`` is always the authenticated caller. There is no update or delete
endpoint — repeat acknowledgements are allowed and each creates a new row.
"""

from typing import TYPE_CHECKING

import pytest
from django.db import IntegrityError, transaction
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate
from apps.process.models import Acknowledgement, Procedure
from apps.process.tests.test_forms_api import make_form, make_staff

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.process.tests.urls"),
]

ACKNOWLEDGE_URL = "/api/process/forms/{id}/acknowledge/"
ACKNOWLEDGEMENTS_URL = "/api/process/forms/{id}/acknowledgements/"


def client_for(staff: Staff) -> Client:
    client = Client()
    authenticate(client, staff)
    return client


def any_staff_client() -> Client:
    return client_for(make_staff("worker@example.com"))


def acknowledge(client: Client, form_id: object, **body: object) -> "_MonkeyPatchedWSGIResponse":
    return client.post(
        ACKNOWLEDGE_URL.format(id=form_id), data=body, content_type="application/json"
    )


def list_acknowledgements(client: Client, form_id: object) -> "_MonkeyPatchedWSGIResponse":
    return client.get(ACKNOWLEDGEMENTS_URL.format(id=form_id))


class TestAuth:
    def test_anonymous_cannot_acknowledge(self) -> None:
        form = make_form()
        assert (
            Client()
            .post(ACKNOWLEDGE_URL.format(id=form.id), content_type="application/json")
            .status_code
            == 401
        )

    def test_anonymous_cannot_list(self) -> None:
        form = make_form()
        assert Client().get(ACKNOWLEDGEMENTS_URL.format(id=form.id)).status_code == 401

    def test_any_staff_can_acknowledge_and_list(self) -> None:
        form = make_form()
        client = any_staff_client()
        assert acknowledge(client, form.id).status_code == 201
        assert list_acknowledgements(client, form.id).status_code == 200


class TestAcknowledge:
    def test_post_stamps_the_requesting_user(self) -> None:
        form = make_form()
        staff = make_staff("signer@example.com", first_name="Signer", last_name="Person")
        client = client_for(staff)

        response = acknowledge(client, form.id)

        assert response.status_code == 201
        body = response.json()
        row = Acknowledgement.objects.get(pk=body["id"])
        assert row.staff_id == staff.id
        assert row.form_id == form.id
        assert body["staff_name"] == staff.get_display_full_name()

    def test_no_body_at_all_succeeds(self) -> None:
        """The real acknowledge click sends no body content, not even "{}" —
        confirms AcknowledgeIn's all-optional fields don't turn a missing
        body into a required-field 422."""
        form = make_form()
        client = any_staff_client()

        response = client.post(ACKNOWLEDGE_URL.format(id=form.id), content_type="application/json")

        assert response.status_code == 201

    def test_body_staff_is_rejected(self) -> None:
        form = make_form()
        other = make_staff("other@example.com")
        client = any_staff_client()

        response = acknowledge(client, form.id, staff=str(other.id))

        assert response.status_code == 422

    def test_repeat_acknowledgement_creates_a_second_row(self) -> None:
        form = make_form()
        client = any_staff_client()

        first = acknowledge(client, form.id)
        second = acknowledge(client, form.id)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] != second.json()["id"]
        assert Acknowledgement.objects.filter(form=form).count() == 2

    def test_unknown_form_is_a_404(self) -> None:
        missing_id = "11111111-2222-3333-4444-555555555555"
        client = any_staff_client()

        assert acknowledge(client, missing_id).status_code == 404


class TestList:
    def test_lists_newest_first(self) -> None:
        form = make_form()
        staff_a = make_staff("a@example.com")
        staff_b = make_staff("b@example.com")
        older = Acknowledgement.objects.create(staff=staff_a, form=form)
        newer = Acknowledgement.objects.create(staff=staff_b, form=form)

        body = list_acknowledgements(any_staff_client(), form.id).json()

        assert [row["id"] for row in body] == [str(newer.id), str(older.id)]

    def test_description_renders_the_sentence(self) -> None:
        form = make_form(title="Fire Drill Register")
        staff = make_staff("carol@example.com", first_name="Carol", last_name="Signer")
        row = Acknowledgement.objects.create(staff=staff, form=form)

        body = list_acknowledgements(any_staff_client(), form.id).json()

        description = next(item["description"] for item in body if item["id"] == str(row.id))
        assert staff.get_display_full_name() in description
        assert f"{row.acknowledged_at:%d %b %Y %H:%M}" in description
        assert "Fire Drill Register" in description


class TestModel:
    def test_exactly_one_document_constraint(self) -> None:
        staff = make_staff("model@example.com")
        form = make_form()

        # Each violation gets its own savepoint: Postgres aborts the whole
        # transaction on an IntegrityError, so a second write inside the same
        # test needs a nested atomic() to recover after pytest.raises catches it.
        with transaction.atomic(), pytest.raises(IntegrityError):
            Acknowledgement.objects.create(staff=staff, form=None, procedure=None)

        procedure = Procedure.objects.create(
            document_type="procedure", category="safety", title="A procedure"
        )
        with transaction.atomic(), pytest.raises(IntegrityError):
            Acknowledgement.objects.create(staff=staff, form=form, procedure=procedure)
