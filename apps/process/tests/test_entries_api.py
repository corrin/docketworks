"""API tests for form entries: CRUD, soft delete, parent links, history.

Reads and writes are any-staff here — unlike forms (office-staff-only writes),
regular staff sign entries; the audit trail (ProcessEvent) is the control,
not a permission gate.
"""

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job
from apps.process.models import Form, FormEntry, ProcessEvent

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.process.tests.urls"),
]

PASSWORD = "s3cret-Pass!"
ENTRIES_URL = "/api/process/entries/"
FORM_ENTRIES_URL = "/api/process/forms/{form_id}/entries/"
ENTRY_DETAIL_URL = "/api/process/entries/{id}/"
ENTRY_HISTORY_URL = "/api/process/entries/{id}/history/"

SCHEMA = {
    "fields": [
        {"key": "area", "label": "Area", "type": "text", "required": True},
        {"key": "injured", "label": "Injured staff member", "type": "staff"},
    ]
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


def make_form(**overrides: object) -> Form:
    defaults: dict[str, object] = {
        "document_type": "form",
        "category": "incident",
        "title": "Incident report",
        "form_schema": SCHEMA,
    }
    defaults.update(overrides)
    return Form.objects.create(**defaults)


def make_entry(form: Form, **overrides: object) -> FormEntry:
    defaults: dict[str, object] = {
        "form": form,
        "entry_date": "2026-08-25",
        "data": {"area": "Bay 1"},
    }
    defaults.update(overrides)
    return FormEntry.objects.create(**defaults)


def create(client: Client, form_id: object, **overrides: object) -> "_MonkeyPatchedWSGIResponse":
    payload: dict[str, object] = {"entry_date": "2026-08-25", "data": {"area": "Bay 1"}}
    payload.update(overrides)
    return client.post(
        FORM_ENTRIES_URL.format(form_id=form_id), data=payload, content_type="application/json"
    )


def patch(client: Client, entry_id: object, **fields: object) -> "_MonkeyPatchedWSGIResponse":
    return client.patch(
        ENTRY_DETAIL_URL.format(id=entry_id), data=fields, content_type="application/json"
    )


class TestAuth:
    def test_anonymous_cannot_list_or_create(self) -> None:
        form = make_form()
        assert Client().get(ENTRIES_URL).status_code == 401
        assert Client().get(FORM_ENTRIES_URL.format(form_id=form.id)).status_code == 401
        assert create(Client(), form.id).status_code == 401

    def test_regular_staff_can_create_edit_and_archive(self) -> None:
        """The domain's point: regular staff sign forms; the audit trail is
        the control, not a permission gate."""
        form = make_form()
        client = any_staff_client()

        created = create(client, form.id)
        assert created.status_code == 201
        entry_id = created.json()["id"]

        edited = patch(client, entry_id, data={"area": "Bay 2"})
        assert edited.status_code == 200

        archived = client.delete(ENTRY_DETAIL_URL.format(id=entry_id))
        assert archived.status_code == 204


class TestCreate:
    def test_creates_entry_stamps_entered_by_and_writes_event(self) -> None:
        form = make_form()
        staff = make_staff("creator@example.com")
        client = client_for(staff)

        response = create(client, form.id)

        assert response.status_code == 201
        body = response.json()
        entry = FormEntry.objects.get(pk=body["id"])
        assert entry.entered_by == staff
        assert body["entered_by"] == str(staff.id)
        assert ProcessEvent.objects.filter(form_entry=entry, event_type="entry_created").exists()

    def test_invalid_data_is_a_transparent_400(self) -> None:
        form = make_form()
        response = create(any_staff_client(), form.id, data={"area": "x", "mystery": 1})

        assert response.status_code == 400
        assert "mystery" in response.json()["detail"]

    def test_staff_defaults_are_not_invented(self) -> None:
        # omitted staff stays NULL — the API never guesses who an entry is about
        form = make_form()
        response = create(any_staff_client(), form.id)

        assert response.status_code == 201
        entry = FormEntry.objects.get(pk=response.json()["id"])
        assert entry.staff is None
        assert response.json()["staff"] is None

    def test_parent_entry_links_across_forms(self) -> None:
        meeting_form = make_form(title="Toolbox meeting", category="meeting")
        action_form = make_form(title="Action items", category="meeting")
        parent = make_entry(meeting_form)
        client = any_staff_client()

        response = create(client, action_form.id, parent_entry=str(parent.id))

        assert response.status_code == 201
        body = response.json()
        assert body["parent_entry"] == str(parent.id)
        child = FormEntry.objects.get(pk=body["id"])
        assert child.parent_entry == parent

    def test_create_on_an_archived_form_is_a_400(self) -> None:
        # v1 had no such guard (docs/accepted-api-differences.yml); v2 refuses
        # new entries against a form the office has retired.
        form = make_form(status="archived")

        response = create(any_staff_client(), form.id)

        assert response.status_code == 400
        assert form.title in response.json()["detail"]
        assert not FormEntry.objects.filter(form=form).exists()

    def test_unknown_parent_entry_is_a_400(self) -> None:
        form = make_form()
        missing = str(uuid4())

        response = create(any_staff_client(), form.id, parent_entry=missing)

        assert response.status_code == 400
        assert "parent_entry" in response.json()["detail"]


class TestList:
    def test_paginated_envelope_with_page_size_50_default(self) -> None:
        form = make_form()
        make_entry(form)

        body = any_staff_client().get(FORM_ENTRIES_URL.format(form_id=form.id)).json()

        assert body["page"] == 1
        assert body["page_size"] == 50
        assert body["count"] == 1
        assert body["total_pages"] == 1
        assert len(body["results"]) == 1

    def test_only_active_entries_listed(self) -> None:
        form = make_form()
        active = make_entry(form)
        make_entry(form, is_active=False)

        body = any_staff_client().get(FORM_ENTRIES_URL.format(form_id=form.id)).json()

        assert [row["id"] for row in body["results"]] == [str(active.id)]

    def test_flat_list_filters_by_parent(self) -> None:
        meeting_form = make_form(title="Toolbox meeting", category="meeting")
        action_form = make_form(title="Action items", category="meeting")
        parent = make_entry(meeting_form)
        child = make_entry(action_form, parent_entry=parent)
        make_entry(action_form)

        body = any_staff_client().get(ENTRIES_URL, {"parent": str(parent.id)}).json()

        assert [row["id"] for row in body["results"]] == [str(child.id)]

    def test_rows_resolve_display_data_for_staff_fields(self) -> None:
        form = make_form()
        staff = make_staff("injured@example.com", first_name="Ben", last_name="Signer")
        make_entry(form, data={"area": "Bay 1", "injured": str(staff.id)})

        body = any_staff_client().get(FORM_ENTRIES_URL.format(form_id=form.id)).json()

        row = body["results"][0]
        assert row["display_data"]["injured"] == staff.get_display_full_name()

    def test_flat_list_filters_by_staff(self) -> None:
        form = make_form()
        subject = make_staff("subject@example.com", first_name="Sam", last_name="Subject")
        matching = make_entry(form, staff=subject)
        make_entry(form)

        body = any_staff_client().get(ENTRIES_URL, {"staff": str(subject.id)}).json()

        assert [row["id"] for row in body["results"]] == [str(matching.id)]

    def test_flat_list_filters_by_job(self) -> None:
        form = make_form()
        company = make_company("Acme Co")
        job_owner = make_staff("jobowner@example.com")
        job = make_job(company, job_owner)
        matching = make_entry(form, job=job)
        make_entry(form)

        body = any_staff_client().get(ENTRIES_URL, {"job": str(job.id)}).json()

        assert [row["id"] for row in body["results"]] == [str(matching.id)]
        # EntryOut.job must serialize the FK id, not the related Job instance.
        assert body["results"][0]["job"] == str(job.id)


class TestUpdate:
    def test_edit_writes_entry_updated_with_field_labels(self) -> None:
        # PATCH data {"area": "Bay 2"}; event.description mentions "Area" and both values
        form = make_form()
        entry = make_entry(form, data={"area": "Bay 1"})
        client = any_staff_client()

        response = patch(client, entry.id, data={"area": "Bay 2"})

        assert response.status_code == 200
        entry.refresh_from_db()
        assert entry.data == {"area": "Bay 2"}
        event = ProcessEvent.objects.get(form_entry=entry, event_type="entry_updated")
        assert "Area" in event.description
        assert "Bay 1" in event.description
        assert "Bay 2" in event.description

    def test_merged_data_is_validated(self) -> None:
        # PATCH with a key not in schema -> 400, entry unchanged, no event
        form = make_form()
        entry = make_entry(form, data={"area": "Bay 1"})
        client = any_staff_client()

        response = patch(client, entry.id, data={"area": "Bay 1", "mystery": 1})

        assert response.status_code == 400
        entry.refresh_from_db()
        assert entry.data == {"area": "Bay 1"}
        assert not ProcessEvent.objects.filter(
            form_entry=entry, event_type="entry_updated"
        ).exists()

    def test_entry_date_only_patch_ignores_a_since_changed_schema(self) -> None:
        """A PATCH that never touches ``data`` must not validate it: the form's
        schema can change after entries exist (Task 7 allows PATCH
        /forms/{id}/ with a new form_schema), and re-validating untouched,
        now-stale data against the new schema would 400 an edit the caller
        never asked for."""
        form = make_form()
        entry = make_entry(form, data={"area": "Bay 1"})
        # Drop 'area' and require a field the stored data lacks: the entry's
        # stored data is now invalid against the form's current schema.
        form.form_schema = {
            "fields": [{"key": "zone", "label": "Zone", "type": "text", "required": True}]
        }
        form.save(update_fields=["form_schema"])
        client = any_staff_client()

        response = patch(client, entry.id, entry_date="2026-08-26")

        assert response.status_code == 200
        entry.refresh_from_db()
        assert str(entry.entry_date) == "2026-08-26"
        assert entry.data == {"area": "Bay 1"}

    def test_no_change_patch_leaves_updated_at_untouched(self) -> None:
        form = make_form()
        entry = make_entry(form, data={"area": "Bay 1"})
        original_updated_at = entry.updated_at

        response = patch(any_staff_client(), entry.id, data={"area": "Bay 1"})

        assert response.status_code == 200
        entry.refresh_from_db()
        assert entry.updated_at == original_updated_at


class TestUpdateAgainstArchivedForm:
    def test_patch_on_an_archived_form_is_a_400(self) -> None:
        form = make_form()
        entry = make_entry(form, data={"area": "Bay 1"})
        form.status = "archived"
        form.save(update_fields=["status"])

        response = patch(any_staff_client(), entry.id, data={"area": "Bay 2"})

        assert response.status_code == 400
        assert form.title in response.json()["detail"]
        entry.refresh_from_db()
        assert entry.data == {"area": "Bay 1"}


class TestArchive:
    def test_delete_still_works_on_an_archived_form(self) -> None:
        # Removing residue is not adding a record, so archiving an entry
        # stays reachable even once its form is archived.
        form = make_form()
        entry = make_entry(form)
        form.status = "archived"
        form.save(update_fields=["status"])

        response = any_staff_client().delete(ENTRY_DETAIL_URL.format(id=entry.id))

        assert response.status_code == 204
        entry.refresh_from_db()
        assert entry.is_active is False

    def test_delete_is_soft_and_audited(self) -> None:
        # DELETE -> 204; row is_active=False; entry_archived event exists
        form = make_form()
        entry = make_entry(form)

        response = any_staff_client().delete(ENTRY_DETAIL_URL.format(id=entry.id))

        assert response.status_code == 204
        entry.refresh_from_db()
        assert entry.is_active is False
        assert ProcessEvent.objects.filter(form_entry=entry, event_type="entry_archived").exists()

    def test_repeated_delete_is_idempotent(self) -> None:
        # Second DELETE on an already-archived entry: still 204, no second event.
        form = make_form()
        entry = make_entry(form)
        client = any_staff_client()

        first = client.delete(ENTRY_DETAIL_URL.format(id=entry.id))
        second = client.delete(ENTRY_DETAIL_URL.format(id=entry.id))

        assert first.status_code == 204
        assert second.status_code == 204
        assert (
            ProcessEvent.objects.filter(form_entry=entry, event_type="entry_archived").count() == 1
        )


class TestHistory:
    def test_history_lists_events_newest_first_with_staff_names(self) -> None:
        form = make_form()
        creator = make_staff("creator2@example.com", first_name="Cara", last_name="Creator")
        editor = make_staff("editor@example.com", first_name="Eddie", last_name="Editor")
        client = client_for(creator)
        create_response = create(client, form.id, data={"area": "Bay 1"})
        entry_id = create_response.json()["id"]
        patch(client_for(editor), entry_id, data={"area": "Bay 2"})

        response = any_staff_client().get(ENTRY_HISTORY_URL.format(id=entry_id))

        assert response.status_code == 200
        body = response.json()
        assert [event["event_type"] for event in body] == ["entry_updated", "entry_created"]
        assert body[0]["staff_name"] == editor.get_display_full_name()
        assert body[1]["staff_name"] == creator.get_display_full_name()
