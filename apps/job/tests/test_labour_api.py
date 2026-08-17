"""API tests for labour subtypes and per-job labour rates.

The tests guard management backfills and invariants plus the job labour-rate
read/update contract; migration implementation text is deliberately not tested
(ADR 0025).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job, JobLabourRate, LabourSubtype

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.job.tests.urls"),
]


def _workshop_client(workshop_staff: Staff) -> Client:
    client = Client()
    authenticate(client, workshop_staff)
    return client


class TestLabourSubtypeList:
    def test_lists_active_subtypes_only(self, client: Client) -> None:
        LabourSubtype.objects.filter(name="Delivery").update(is_active=False)

        response = client.get("/api/job/labour-subtypes/")

        assert response.status_code == 200
        names = [row["name"] for row in response.json()]
        assert "Workshop" in names
        assert "Delivery" not in names

    def test_any_staff_can_read(self, workshop_staff: Staff) -> None:
        response = _workshop_client(workshop_staff).get("/api/job/labour-subtypes/")
        assert response.status_code == 200


class TestLabourSubtypeManage:
    def test_manage_endpoints_are_office_only(self, workshop_staff: Staff) -> None:
        client = _workshop_client(workshop_staff)
        assert client.get("/api/job/labour-subtypes/manage/").status_code == 403
        assert (
            client.post(
                "/api/job/labour-subtypes/manage/",
                data={"name": "Nope", "default_charge_out_rate": "100.00"},
                content_type="application/json",
            ).status_code
            == 403
        )

    def test_manage_list_includes_inactive(self, client: Client) -> None:
        LabourSubtype.objects.filter(name="Delivery").update(is_active=False)

        response = client.get("/api/job/labour-subtypes/manage/")

        assert response.status_code == 200
        rows = {row["name"]: row for row in response.json()}
        assert rows["Delivery"]["is_active"] is False
        assert "counts_for_scheduling" in rows["Workshop"]

    def test_create_backfills_existing_jobs(self, client: Client, job: Job) -> None:
        response = client.post(
            "/api/job/labour-subtypes/manage/",
            data={"name": "Polishing", "default_charge_out_rate": "120.00"},
            content_type="application/json",
        )

        assert response.status_code == 201
        subtype = LabourSubtype.objects.get(name="Polishing")
        rate = job.labour_rates.get(labour_subtype=subtype)
        assert rate.charge_out_rate == Decimal("120.00")

    def test_create_backfills_shop_jobs_at_zero(self, client: Client, job: Job) -> None:
        shop_company = CompanyDefaults.get_solo().shop_company
        assert shop_company is not None
        office = Staff.objects.get(office_email="job-office@example.com")
        shop_job = make_job(shop_company, office, name="Shop maintenance")

        response = client.post(
            "/api/job/labour-subtypes/manage/",
            data={"name": "Polishing", "default_charge_out_rate": "120.00"},
            content_type="application/json",
        )

        assert response.status_code == 201
        subtype = LabourSubtype.objects.get(name="Polishing")
        assert shop_job.labour_rates.get(labour_subtype=subtype).charge_out_rate == Decimal("0.00")
        assert job.labour_rates.get(labour_subtype=subtype).charge_out_rate == Decimal("120.00")

    def test_inactive_create_does_not_backfill(self, client: Client, job: Job) -> None:
        response = client.post(
            "/api/job/labour-subtypes/manage/",
            data={"name": "Dormant", "default_charge_out_rate": "99.00", "is_active": False},
            content_type="application/json",
        )

        assert response.status_code == 201
        subtype = LabourSubtype.objects.get(name="Dormant")
        assert not job.labour_rates.filter(labour_subtype=subtype).exists()

    def test_duplicate_name_is_400(self, client: Client) -> None:
        response = client.post(
            "/api/job/labour-subtypes/manage/",
            data={"name": "Workshop", "default_charge_out_rate": "100.00"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_negative_rate_is_rejected(self, client: Client) -> None:
        response = client.post(
            "/api/job/labour-subtypes/manage/",
            data={"name": "Cheap", "default_charge_out_rate": "-1.00"},
            content_type="application/json",
        )
        # Schema-level validation (v1 answered 400 from DRF min_value)
        assert response.status_code == 422

    def test_retrieve_unknown_subtype_is_404(self, client: Client) -> None:
        assert client.get(f"/api/job/labour-subtypes/manage/{uuid4()}/").status_code == 404

    def test_cannot_deactivate_last_workshop_subtype(self, client: Client) -> None:
        workshop = LabourSubtype.objects.get(name="Workshop")
        # Clear staff defaults so the pool guard (not the staff-default guard,
        # which runs first as in v1) answers this request.
        admin = LabourSubtype.objects.get(name="Admin")
        Staff.objects.filter(default_labour_subtype=workshop).update(default_labour_subtype=admin)

        response = client.patch(
            f"/api/job/labour-subtypes/manage/{workshop.id}/",
            data={"is_active": False},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "only active Workshop subtype" in response.json()["detail"]
        workshop.refresh_from_db()
        assert workshop.is_active is True

    def test_cannot_flip_last_workshop_subtype_off(self, client: Client) -> None:
        workshop = LabourSubtype.objects.get(name="Workshop")

        response = client.patch(
            f"/api/job/labour-subtypes/manage/{workshop.id}/",
            data={"is_workshop": False},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "only active Workshop subtype" in response.json()["detail"]

    def test_cannot_deactivate_a_staff_default_subtype(
        self, client: Client, office_staff: Staff
    ) -> None:
        delivery = LabourSubtype.objects.get(name="Delivery")
        office_staff.default_labour_subtype = delivery
        office_staff.save(update_fields=["default_labour_subtype"])

        response = client.patch(
            f"/api/job/labour-subtypes/manage/{delivery.id}/",
            data={"is_active": False},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "reassign them before deactivating" in response.json()["detail"]

    def test_edit_default_rate_does_not_touch_existing_jobs(self, client: Client, job: Job) -> None:
        delivery = LabourSubtype.objects.get(name="Delivery")
        before = job.labour_rates.get(labour_subtype=delivery).charge_out_rate

        response = client.patch(
            f"/api/job/labour-subtypes/manage/{delivery.id}/",
            data={"default_charge_out_rate": "222.00"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["default_charge_out_rate"] == "222.00"
        assert job.labour_rates.get(labour_subtype=delivery).charge_out_rate == before

    def test_reactivation_backfills_jobs_created_while_inactive(
        self, client: Client, office_staff: Staff
    ) -> None:
        delivery = LabourSubtype.objects.get(name="Delivery")
        delivery.is_active = False
        delivery.save(update_fields=["is_active"])
        company = make_company("Reactivation Co")
        new_job = make_job(company, office_staff, name="Made while inactive")
        assert not new_job.labour_rates.filter(labour_subtype=delivery).exists()

        response = client.patch(
            f"/api/job/labour-subtypes/manage/{delivery.id}/",
            data={"is_active": True},
            content_type="application/json",
        )

        assert response.status_code == 200
        rate = new_job.labour_rates.get(labour_subtype=delivery)
        assert rate.charge_out_rate == delivery.default_charge_out_rate


class TestJobLabourRates:
    def test_read_is_office_only(self, job: Job, workshop_staff: Staff) -> None:
        response = _workshop_client(workshop_staff).get(f"/api/job/jobs/{job.id}/labour-rates/")
        assert response.status_code == 403

    def test_returns_seeded_rates_in_display_order(self, client: Client, job: Job) -> None:
        response = client.get(f"/api/job/jobs/{job.id}/labour-rates/")

        assert response.status_code == 200
        rows = response.json()
        active_count = LabourSubtype.objects.filter(is_active=True).count()
        assert len(rows) == active_count
        assert rows[0]["labour_subtype_name"] == "Workshop"
        assert rows[0]["is_workshop"] is True

    def test_patch_updates_rate_and_records_event(self, client: Client, job: Job) -> None:
        workshop = LabourSubtype.objects.get(name="Workshop")

        response = client.patch(
            f"/api/job/jobs/{job.id}/labour-rates/",
            data={"rates": [{"labour_subtype": str(workshop.id), "charge_out_rate": "150.00"}]},
            content_type="application/json",
        )

        assert response.status_code == 200
        rate = JobLabourRate.objects.get(job=job, labour_subtype=workshop)
        assert rate.charge_out_rate == Decimal("150.00")
        event = job.events.get(event_type="pricing_changed")
        assert "Workshop charge-out rate" in event.description

    def test_noop_patch_records_no_event(self, client: Client, job: Job) -> None:
        workshop = LabourSubtype.objects.get(name="Workshop")
        current = JobLabourRate.objects.get(job=job, labour_subtype=workshop).charge_out_rate

        response = client.patch(
            f"/api/job/jobs/{job.id}/labour-rates/",
            data={"rates": [{"labour_subtype": str(workshop.id), "charge_out_rate": str(current)}]},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert not job.events.filter(event_type="pricing_changed").exists()

    def test_patch_rejects_unseeded_subtype_without_writing(self, client: Client, job: Job) -> None:
        unseeded = LabourSubtype.objects.create(
            name="Unseeded",
            is_active=False,
            default_charge_out_rate=Decimal("50.00"),
        )
        workshop = LabourSubtype.objects.get(name="Workshop")
        before = JobLabourRate.objects.get(job=job, labour_subtype=workshop).charge_out_rate

        response = client.patch(
            f"/api/job/jobs/{job.id}/labour-rates/",
            data={
                "rates": [
                    {"labour_subtype": str(workshop.id), "charge_out_rate": "999.00"},
                    {"labour_subtype": str(unseeded.id), "charge_out_rate": "50.00"},
                ]
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "No rate row on this job for: Unseeded." in response.json()["detail"]
        # Rejected up front — the valid entry was not applied either.
        after = JobLabourRate.objects.get(job=job, labour_subtype=workshop).charge_out_rate
        assert after == before

    def test_patch_unknown_subtype_is_400(self, client: Client, job: Job) -> None:
        response = client.patch(
            f"/api/job/jobs/{job.id}/labour-rates/",
            data={"rates": [{"labour_subtype": str(uuid4()), "charge_out_rate": "10.00"}]},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "LabourSubtype not found" in response.json()["detail"]

    def test_patch_negative_rate_is_rejected(self, client: Client, job: Job) -> None:
        workshop = LabourSubtype.objects.get(name="Workshop")
        response = client.patch(
            f"/api/job/jobs/{job.id}/labour-rates/",
            data={"rates": [{"labour_subtype": str(workshop.id), "charge_out_rate": "-5.00"}]},
            content_type="application/json",
        )
        # Schema-level validation (v1 answered 400 from DRF min_value)
        assert response.status_code == 422

    def test_unknown_job_is_404(self, client: Client) -> None:
        assert client.get(f"/api/job/jobs/{uuid4()}/labour-rates/").status_code == 404
