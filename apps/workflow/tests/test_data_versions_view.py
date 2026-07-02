"""Guards against stale-data regressions: any write to Stock, Job, Staff
assignments, or Client contacts must bump the corresponding data-version
string so the frontend invalidates its cache and re-fetches.
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.client.models import Client, ClientContact
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.job.models import Job
from apps.job.services.job_service import JobStaffService
from apps.purchasing.models import Stock
from apps.workflow.models import CompanyDefaults, XeroPayItem


@pytest.fixture
def office_staff(db):
    staff = Staff.objects.create(
        email="office@example.test",
        first_name="O",
        last_name="S",
        password_needs_reset=False,
        is_office_staff=True,
    )
    staff.set_password("pw")
    staff.save()
    return staff


@pytest.fixture
def auth_client(office_staff):
    api = APIClient()
    api.force_authenticate(user=office_staff)
    return api


def _stock(**overrides):
    defaults = dict(
        description="Test material",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
    )
    defaults.update(overrides)
    return Stock.objects.create(**defaults)


@pytest.fixture
def kanban_prerequisites(db):
    shop_client = _client(name="Shop Client")
    CompanyDefaults.objects.get_or_create(
        company_name="Test Co",
        defaults={"shop_client": shop_client},
    )
    XeroPayItem.objects.get_or_create(
        name="Ordinary Time",
        uses_leave_api=False,
        defaults={"multiplier": Decimal("1.00")},
    )


def _client(**overrides):
    defaults = dict(name="Kanban Client", xero_last_modified=timezone.now())
    defaults.update(overrides)
    return Client.objects.create(**defaults)


def _job(staff, **overrides):
    defaults = dict(
        staff=staff,
        client=_client(),
        name="Kanban Job",
        pricing_methodology="time_materials",
    )
    defaults.update(overrides)
    return Job.objects.create(**defaults)


def _phone_call(**overrides):
    now = timezone.now()
    defaults = dict(
        provider_call_id="version-test-call",
        account_code="version-test",
        call_datetime=now,
        call_date=timezone.localdate(),
        call_time=now.time(),
        origin="+6421555123",
        destination="+6496365131",
        duration_seconds=60,
        raw_json={"id": "version-test-call"},
    )
    defaults.update(overrides)
    return PhoneCallRecord.objects.create(**defaults)


def test_get_returns_dict_with_dataset_keys(auth_client, db):
    resp = auth_client.get("/api/data-versions/")
    assert resp.status_code == 200
    body = resp.json()
    assert "stock" in body
    assert "kanban" in body
    assert "crm_calls" in body
    assert isinstance(body["stock"], str)
    assert isinstance(body["kanban"], str)
    assert isinstance(body["crm_calls"], str)
    assert body["stock"]
    assert body["kanban"]
    assert body["crm_calls"]


def test_response_has_no_store_cache_header(auth_client, db):
    """A stale `Cache-Control` header would let browsers serve expired version
    strings, defeating cache invalidation entirely.
    """
    resp = auth_client.get("/api/data-versions/")
    assert resp["Cache-Control"] == "no-store"


def test_unauthenticated_request_is_rejected(db):
    """Leaking version strings to unauthenticated callers exposes deployment
    details (hashes, timestamps) that an attacker can fingerprint.
    """
    resp = APIClient().get("/api/data-versions/")
    assert resp.status_code in (401, 403)


def test_creating_stock_changes_version(auth_client, db):
    before = auth_client.get("/api/data-versions/").json()["stock"]
    _stock(description="New item")
    after = auth_client.get("/api/data-versions/").json()["stock"]
    assert before != after


def test_saving_stock_changes_version(auth_client, db):
    item = _stock(description="Initial")
    before = auth_client.get("/api/data-versions/").json()["stock"]
    item.unit_cost = Decimal("99.99")
    item.save()
    after = auth_client.get("/api/data-versions/").json()["stock"]
    assert before != after


def test_save_with_update_fields_still_bumps_version(auth_client, db):
    """The model's save() override merges 'updated_at' into update_fields,
    so a partial save like the Xero sync's `save(update_fields=['unit_cost'])`
    still triggers a version bump — that's the whole point of the field."""
    item = _stock(description="Partial save")
    before = auth_client.get("/api/data-versions/").json()["stock"]
    item.unit_cost = Decimal("196.04")
    item.save(update_fields=["unit_cost"])
    after = auth_client.get("/api/data-versions/").json()["stock"]
    assert before != after


def test_repeat_call_without_changes_returns_same_version(auth_client, db):
    _stock()
    first = auth_client.get("/api/data-versions/").json()["stock"]
    second = auth_client.get("/api/data-versions/").json()["stock"]
    assert first == second


def test_creating_job_changes_kanban_version(
    auth_client, office_staff, kanban_prerequisites
):
    before = auth_client.get("/api/data-versions/").json()["kanban"]
    _job(office_staff)
    after = auth_client.get("/api/data-versions/").json()["kanban"]
    assert before != after


def test_saving_job_changes_kanban_version(
    auth_client, office_staff, kanban_prerequisites
):
    job = _job(office_staff)
    before = auth_client.get("/api/data-versions/").json()["kanban"]
    job.name = "Renamed Kanban Job"
    job.save(staff=office_staff, update_fields=["name"])
    after = auth_client.get("/api/data-versions/").json()["kanban"]
    assert before != after


def test_assigning_staff_changes_kanban_version(
    auth_client, office_staff, kanban_prerequisites
):
    job = _job(office_staff)
    assignee = Staff.objects.create(
        email="assignee@example.test",
        first_name="A",
        last_name="S",
        password_needs_reset=False,
    )
    before = auth_client.get("/api/data-versions/").json()["kanban"]
    success, error = JobStaffService.assign_staff_to_job(job.id, assignee.id)
    after = auth_client.get("/api/data-versions/").json()["kanban"]
    assert success, error
    assert before != after


def test_related_display_changes_change_kanban_version(
    auth_client, office_staff, kanban_prerequisites
):
    client = _client(name="Original Client")
    contact = ClientContact.objects.create(client=client, name="Original Contact")
    _job(office_staff, client=client, contact=contact)
    before = auth_client.get("/api/data-versions/").json()["kanban"]
    contact.name = "Updated Contact"
    contact.save(update_fields=["name"])
    after = auth_client.get("/api/data-versions/").json()["kanban"]
    assert before != after


def test_client_partial_save_changes_kanban_version(
    auth_client, office_staff, kanban_prerequisites
):
    client = _client(name="Original Client")
    _job(office_staff, client=client)
    before = auth_client.get("/api/data-versions/").json()["kanban"]
    client.name = "Updated Client"
    client.save(update_fields=["name"])
    after = auth_client.get("/api/data-versions/").json()["kanban"]
    assert before != after


def test_creating_phone_call_changes_crm_calls_version(auth_client, db):
    before = auth_client.get("/api/data-versions/").json()["crm_calls"]
    _phone_call()
    after = auth_client.get("/api/data-versions/").json()["crm_calls"]
    assert before != after


def test_saving_phone_call_changes_crm_calls_version(auth_client, db):
    call = _phone_call()
    before = auth_client.get("/api/data-versions/").json()["crm_calls"]
    call.duration_seconds = 120
    call.save(update_fields=["duration_seconds", "updated_at"])
    after = auth_client.get("/api/data-versions/").json()["crm_calls"]
    assert before != after


def test_recording_changes_crm_calls_version(auth_client, db):
    call = _phone_call()
    before = auth_client.get("/api/data-versions/").json()["crm_calls"]
    PhoneCallRecording.objects.create(
        call=call,
        provider_recording_id="version-test-recording",
        account_code="version-test",
        filename="version-test-recording.mp3",
        storage_path="2026/07/02/version-test-recording.mp3",
    )
    after = auth_client.get("/api/data-versions/").json()["crm_calls"]
    assert before != after
