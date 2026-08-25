"""API tests for forms and categories.

Reads are any-staff (regular staff exist in this domain to sign); form
writes are office staff. Archive replaces delete — a form's audit trail
cannot vanish with the form.
"""

from typing import TYPE_CHECKING

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate
from apps.process.models import Form, FormEntry, ProcessEvent

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.process.tests.urls"),
]

PASSWORD = "s3cret-Pass!"
CATEGORIES_URL = "/api/process/categories/"
FORMS_URL = "/api/process/forms/"
DETAIL_URL = "/api/process/forms/{id}/"

VALID_SCHEMA = {"fields": [{"key": "area", "label": "Area", "type": "text", "required": True}]}
CREATE_PAYLOAD = {
    "document_type": "form",
    "category": "incident",
    "title": "Incident report",
    "form_schema": VALID_SCHEMA,
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


def any_staff_client() -> Client:
    return client_for(make_staff("worker@example.com"))


def office_client() -> Client:
    return client_for(make_staff("office@example.com", is_office_staff=True))


def make_form(**overrides: object) -> Form:
    defaults: dict[str, object] = {
        "document_type": "form",
        "category": "incident",
        "title": "Incident report",
        "form_schema": VALID_SCHEMA,
    }
    defaults.update(overrides)
    return Form.objects.create(**defaults)


def create(client: Client, **overrides: object) -> "_MonkeyPatchedWSGIResponse":
    return client.post(
        FORMS_URL, data={**CREATE_PAYLOAD, **overrides}, content_type="application/json"
    )


def patch(client: Client, form_id: object, **fields: object) -> "_MonkeyPatchedWSGIResponse":
    return client.patch(DETAIL_URL.format(id=form_id), data=fields, content_type="application/json")


class TestAuth:
    def test_anonymous_cannot_list(self) -> None:
        assert Client().get(FORMS_URL).status_code == 401

    def test_any_staff_can_list(self) -> None:
        assert any_staff_client().get(FORMS_URL).status_code == 200

    def test_non_office_staff_cannot_create(self) -> None:
        assert create(any_staff_client()).status_code == 403

    def test_non_office_staff_cannot_update(self) -> None:
        form = make_form()
        assert patch(any_staff_client(), form.id, title="Changed").status_code == 403


class TestCategories:
    def test_returns_both_choice_lists_with_labels(self) -> None:
        response = any_staff_client().get(CATEGORIES_URL)

        assert response.status_code == 200
        body = response.json()
        assert {"key": "incident", "label": "Incident"} in body["forms"]
        assert {"key": "jsa", "label": "JSA"} in body["procedures"]


class TestCreate:
    def test_office_staff_creates_a_form_and_an_event(self) -> None:
        response = create(office_client())

        assert response.status_code == 201
        body = response.json()
        form = Form.objects.get(pk=body["id"])
        assert form.title == "Incident report"
        assert form.category == "incident"
        assert ProcessEvent.objects.filter(form=form, event_type="form_created").exists()

    def test_blank_title_is_a_422(self) -> None:
        assert create(office_client(), title="").status_code == 422

    def test_unknown_category_is_a_422(self) -> None:
        assert create(office_client(), category="bogus").status_code == 422

    def test_malformed_schema_is_a_422(self) -> None:
        schema = {"fields": [{"key": "a", "label": "A", "type": "rating"}]}
        assert create(office_client(), form_schema=schema).status_code == 422

    def test_entry_ref_source_form_must_exist(self) -> None:
        missing_id = "11111111-2222-3333-4444-555555555555"
        schema = {
            "fields": [
                {
                    "key": "asset",
                    "label": "Asset",
                    "type": "entry_ref",
                    "source_form": missing_id,
                    "display_key": "name",
                }
            ]
        }
        assert create(office_client(), form_schema=schema).status_code == 400

    def test_blank_document_number_is_a_422(self) -> None:
        assert create(office_client(), document_number="").status_code == 422


class TestList:
    def test_filters_by_category(self) -> None:
        make_form(category="incident", title="Incident A")
        make_form(category="safety", title="Safety A")

        body = any_staff_client().get(FORMS_URL, {"category": "safety"}).json()

        assert {row["category"] for row in body} == {"safety"}

    def test_archived_hidden_by_default_and_reachable_by_status_filter(self) -> None:
        make_form(title="Active form")
        make_form(title="Archived form", status="archived")
        client = any_staff_client()

        default_titles = {row["title"] for row in client.get(FORMS_URL).json()}
        assert "Archived form" not in default_titles
        assert "Active form" in default_titles

        archived_titles = {
            row["title"] for row in client.get(FORMS_URL, {"status": "archived"}).json()
        }
        assert archived_titles == {"Archived form"}

    def test_q_matches_title_case_insensitively(self) -> None:
        make_form(title="Fire Drill Register")
        make_form(title="Toolbox Meeting")

        body = any_staff_client().get(FORMS_URL, {"q": "fire drill"}).json()

        assert [row["title"] for row in body] == ["Fire Drill Register"]

    def test_rows_carry_entry_count(self) -> None:
        form = make_form(title="Inspection")
        FormEntry.objects.create(form=form, entry_date="2026-08-25", data={})
        FormEntry.objects.create(form=form, entry_date="2026-08-25", data={}, is_active=False)

        body = any_staff_client().get(FORMS_URL).json()

        row = next(item for item in body if item["id"] == str(form.id))
        assert row["entry_count"] == 1


class TestPartialUpdate:
    def test_schema_edit_writes_a_schema_updated_event(self) -> None:
        form = make_form()
        new_schema = {"fields": [{"key": "area", "label": "Area", "type": "text"}]}

        response = patch(office_client(), form.id, form_schema=new_schema)

        assert response.status_code == 200
        assert ProcessEvent.objects.filter(form=form, event_type="schema_updated").count() == 1

    def test_archive_via_status_writes_form_archived(self) -> None:
        form = make_form()

        response = patch(office_client(), form.id, status="archived")

        assert response.status_code == 200
        form.refresh_from_db()
        assert form.status == "archived"
        assert ProcessEvent.objects.filter(form=form, event_type="form_archived").count() == 1

    def test_no_destroy_route_exists(self) -> None:
        form = make_form()
        assert office_client().delete(DETAIL_URL.format(id=form.id)).status_code == 405

    def test_re_archiving_writes_no_second_event(self) -> None:
        """A PATCH that resupplies the already-stored status is a no-op: it
        must not write a second form_archived event with old == new."""
        form = make_form()
        client = office_client()

        first = patch(client, form.id, status="archived")
        assert first.status_code == 200
        assert ProcessEvent.objects.filter(form=form, event_type="form_archived").count() == 1

        second = patch(client, form.id, status="archived")
        assert second.status_code == 200
        assert ProcessEvent.objects.filter(form=form, event_type="form_archived").count() == 1
        assert ProcessEvent.objects.filter(form=form).count() == 1

    def test_entry_ref_round_trips_as_a_string_uuid(self) -> None:
        """source_form must serialize as a string on both create and update —
        the JSONField has no UUID-aware encoder, so a raw UUID object left in
        by a python-mode dump would blow up on save."""
        client = office_client()
        source = make_form(title="Asset register", document_type="register", category="register")
        schema = {
            "fields": [
                {
                    "key": "asset",
                    "label": "Asset",
                    "type": "entry_ref",
                    "source_form": str(source.id),
                    "display_key": "name",
                }
            ]
        }

        created = create(client, form_schema=schema)
        assert created.status_code == 201
        form = Form.objects.get(pk=created.json()["id"])
        assert form.form_schema["fields"][0]["source_form"] == str(source.id)

        updated_schema = {**schema, "fields": [{**schema["fields"][0], "label": "Linked Asset"}]}
        patched = patch(client, form.id, form_schema=updated_schema)
        assert patched.status_code == 200
        form.refresh_from_db()
        assert form.form_schema["fields"][0]["source_form"] == str(source.id)
        assert form.form_schema["fields"][0]["label"] == "Linked Asset"
