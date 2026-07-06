from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job, JobLabourRate, LabourSubtype
from apps.job.services.labour_subtype_service import seed_subtype_onto_existing_jobs
from apps.job.services.workshop_service import WorkshopTimesheetService
from apps.testing import BaseTestCase


class LabourSubtypeSeedTests(BaseTestCase):
    CATALOGUE = {
        "Workshop",
        "Admin",
        "Quoting",
        "Onsite quoting",
        "Delivery",
        "Onsite",
        "Supervision",
    }

    def test_migrations_seed_current_subtypes(self) -> None:
        names = set(LabourSubtype.objects.values_list("name", flat=True))
        self.assertEqual(names, self.CATALOGUE)

    def test_all_catalogue_subtypes_are_active(self) -> None:
        active_names = set(
            LabourSubtype.objects.filter(is_active=True).values_list("name", flat=True)
        )
        self.assertEqual(active_names, self.CATALOGUE)

    def test_workshop_is_the_only_workshop_subtype(self) -> None:
        workshop_names = set(
            LabourSubtype.objects.filter(is_workshop=True).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(workshop_names, {"Workshop"})

    def test_scheduler_subtypes_are_non_office_production_work(self) -> None:
        scheduled_names = set(
            LabourSubtype.objects.filter(counts_for_scheduling=True).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(scheduled_names, {"Workshop", "Onsite", "Supervision"})

    def test_onsite_defaults_to_onsite_charge_out_rate(self) -> None:
        onsite = LabourSubtype.objects.get(name="Onsite")
        self.assertEqual(onsite.default_charge_out_rate, Decimal("165.00"))


class JobLabourRateSeedingTests(BaseTestCase):
    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Labour Rate Client",
            email="labour-rates@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

    def _create_job(self) -> Job:
        job = Job(name="Labour Rate Job", client=self.client_obj)
        job.save(staff=self.test_staff)
        return job

    def test_new_job_seeds_rates_for_active_subtypes(self) -> None:
        job = self._create_job()
        rates = {
            rate.labour_subtype.name: rate.charge_out_rate
            for rate in job.labour_rates.select_related("labour_subtype")
        }
        self.assertEqual(
            set(rates),
            {
                "Workshop",
                "Admin",
                "Quoting",
                "Onsite quoting",
                "Delivery",
                "Onsite",
                "Supervision",
            },
        )
        self.assertEqual(rates["Workshop"], Decimal("105.00"))
        self.assertEqual(rates["Onsite"], Decimal("165.00"))

    def test_inactive_subtype_is_not_seeded(self) -> None:
        LabourSubtype.objects.filter(name="Quoting").update(is_active=False)
        job = self._create_job()
        subtype_names = set(
            job.labour_rates.values_list("labour_subtype__name", flat=True)
        )
        self.assertNotIn("Quoting", subtype_names)
        self.assertEqual(len(subtype_names), 6)

    def test_shop_job_seeds_zero_rates(self) -> None:
        job = Job(name="Shop Labour Rate Job")
        job.shop_job = True
        job.save(staff=self.test_staff)
        rates = list(job.labour_rates.values_list("charge_out_rate", flat=True))
        self.assertEqual(len(rates), 7)
        self.assertEqual(set(rates), {Decimal("0.00")})


class StaffDefaultLabourSubtypeTests(BaseTestCase):
    def test_new_workshop_staff_defaults_to_workshop(self) -> None:
        staff = Staff.objects.create_user(
            email="workshop-default@example.com",
            password="testpass",
            first_name="Workshop",
            last_name="Default",
            is_workshop_staff=True,
        )
        assert staff.default_labour_subtype is not None
        self.assertEqual(staff.default_labour_subtype.name, "Workshop")

    def test_new_non_workshop_staff_defaults_to_office_admin(self) -> None:
        staff = Staff.objects.create_user(
            email="office-default@example.com",
            password="testpass",
            first_name="Office",
            last_name="Default",
            is_workshop_staff=False,
            is_office_staff=True,
        )
        assert staff.default_labour_subtype is not None
        self.assertEqual(staff.default_labour_subtype.name, "Admin")


class TimesheetLabourSubtypeTests(BaseTestCase):
    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Timesheet Subtype Client",
            email="timesheet-subtypes@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job(name="Timesheet Subtype Job", client=self.client_obj)
        self.job.save(staff=self.test_staff)
        self.staff = Staff.objects.create_user(
            email="timesheet-subtypes@example.com",
            password="testpass",
            first_name="Timesheet",
            last_name="Subtypes",
            base_wage_rate=Decimal("40.00"),
            is_workshop_staff=True,
        )
        self.service = WorkshopTimesheetService(staff=self.staff)

    def test_create_entry_uses_staff_default_subtype_and_job_rate(self) -> None:
        line = self.service.create_entry(
            {
                "job_id": str(self.job.id),
                "description": "",
                "hours": Decimal("2.000"),
                "accounting_date": date.today(),
            }
        )
        assert line.labour_subtype is not None
        assert line.xero_pay_item is not None
        self.assertEqual(line.labour_subtype.name, "Workshop")
        self.assertEqual(line.unit_rev, Decimal("105.00"))
        # Payroll behaviour is untouched by subtypes
        self.assertEqual(line.xero_pay_item.name, "Ordinary Time")

    def test_create_entry_with_explicit_subtype_uses_that_jobs_subtype_rate(
        self,
    ) -> None:
        onsite = LabourSubtype.objects.get(name="Onsite")
        self.job.labour_rates.filter(labour_subtype=onsite).update(
            charge_out_rate=Decimal("170.00")
        )
        line = self.service.create_entry(
            {
                "job_id": str(self.job.id),
                "description": "",
                "hours": Decimal("1.000"),
                "accounting_date": date.today(),
                "labour_subtype_id": str(onsite.id),
            }
        )
        self.assertEqual(line.labour_subtype, onsite)
        self.assertEqual(line.unit_rev, Decimal("170.00"))

    def test_serializer_patch_of_subtype_alone_recalculates_rate(self) -> None:
        """Office timesheet UI patches labour_subtype without resending meta."""
        from apps.job.serializers.costing_serializer import (
            CostLineCreateUpdateSerializer,
        )

        line = self.service.create_entry(
            {
                "job_id": str(self.job.id),
                "description": "",
                "hours": Decimal("1.000"),
                "accounting_date": date.today(),
            }
        )
        onsite = LabourSubtype.objects.get(name="Onsite")
        serializer = CostLineCreateUpdateSerializer(
            line,
            data={"labour_subtype": str(onsite.id)},
            partial=True,
            context={"staff": self.staff},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertEqual(updated.labour_subtype, onsite)
        self.assertEqual(updated.unit_rev, Decimal("165.00"))

    def test_update_entry_subtype_recalculates_rate(self) -> None:
        line = self.service.create_entry(
            {
                "job_id": str(self.job.id),
                "description": "",
                "hours": Decimal("1.000"),
                "accounting_date": date.today(),
            }
        )
        onsite = LabourSubtype.objects.get(name="Onsite")
        updated = self.service.update_entry(
            {
                "entry_id": str(line.id),
                "labour_subtype_id": str(onsite.id),
            }
        )
        self.assertEqual(updated.labour_subtype, onsite)
        self.assertEqual(updated.unit_rev, Decimal("165.00"))


class LabourSubtypeManagementApiTests(BaseTestCase):
    """The company labour-subtype management UI backend (KAN-266)."""

    def setUp(self) -> None:
        self.office_staff = Staff.objects.create_user(
            email="subtype-mgr@example.com",
            password="testpass",
            first_name="Subtype",
            last_name="Manager",
            is_office_staff=True,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.office_staff)
        self.client_obj = Client.objects.create(
            name="Mgmt Client",
            email="mgmt-subtypes@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job(name="Mgmt Job", client=self.client_obj)
        self.job.save(staff=self.test_staff)

    def _create_job(self, name: str) -> Job:
        job = Job(name=name, client=self.client_obj)
        job.save(staff=self.test_staff)
        return job

    def test_manage_list_includes_inactive_subtypes(self) -> None:
        LabourSubtype.objects.filter(name="Delivery").update(is_active=False)
        resp = self.api.get(reverse("jobs:labour_subtype_manage_list_rest"))
        self.assertEqual(resp.status_code, 200, resp.content)
        names = {row["name"] for row in resp.json()}
        self.assertIn("Delivery", names)

    def test_non_office_staff_forbidden(self) -> None:
        workshop_staff = Staff.objects.create_user(
            email="ws-forbidden@example.com",
            password="testpass",
            first_name="Workshop",
            last_name="Only",
            is_workshop_staff=True,
            is_office_staff=False,
        )
        api = APIClient()
        api.force_authenticate(user=workshop_staff)
        resp = api.get(reverse("jobs:labour_subtype_manage_list_rest"))
        self.assertEqual(resp.status_code, 403)

    def test_create_subtype_backfills_existing_jobs_and_seeds_future(self) -> None:
        resp = self.api.post(
            reverse("jobs:labour_subtype_manage_list_rest"),
            {
                "name": "Rush",
                "display_order": 99,
                "is_workshop": False,
                "counts_for_scheduling": False,
                "default_charge_out_rate": "200.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        rush = LabourSubtype.objects.get(name="Rush")
        # Existing job got a rate row at the new subtype's default.
        self.assertEqual(
            self.job.labour_rates.get(labour_subtype=rush).charge_out_rate,
            Decimal("200.00"),
        )
        # A job created afterwards seeds it too.
        later = self._create_job("Later Job")
        self.assertEqual(
            later.labour_rates.get(labour_subtype=rush).charge_out_rate,
            Decimal("200.00"),
        )

    def test_create_subtype_backfills_shop_jobs_at_zero(self) -> None:
        shop_job = Job(name="Shop Mgmt Job")
        shop_job.shop_job = True
        shop_job.save(staff=self.test_staff)
        resp = self.api.post(
            reverse("jobs:labour_subtype_manage_list_rest"),
            {
                "name": "Rush",
                "display_order": 99,
                "is_workshop": False,
                "counts_for_scheduling": False,
                "default_charge_out_rate": "200.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        rush = LabourSubtype.objects.get(name="Rush")
        self.assertEqual(
            shop_job.labour_rates.get(labour_subtype=rush).charge_out_rate,
            Decimal("0.00"),
        )

    def test_edit_default_rate_affects_future_jobs_not_existing(self) -> None:
        onsite = LabourSubtype.objects.get(name="Onsite")
        existing = self.job.labour_rates.get(labour_subtype=onsite).charge_out_rate
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[onsite.id]),
            {"default_charge_out_rate": "175.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        # Snapshot: the existing job's frozen rate is unchanged.
        self.assertEqual(
            self.job.labour_rates.get(labour_subtype=onsite).charge_out_rate,
            existing,
        )
        # A new job seeds the updated default.
        later = self._create_job("Later Onsite Job")
        self.assertEqual(
            later.labour_rates.get(labour_subtype=onsite).charge_out_rate,
            Decimal("175.00"),
        )

    def test_deactivate_blocked_when_subtype_is_a_staff_default(self) -> None:
        Staff.objects.create_user(
            email="ws-default@example.com",
            password="testpass",
            first_name="Workshop",
            last_name="Default",
            is_workshop_staff=True,
        )
        workshop = LabourSubtype.objects.get(name="Workshop")
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[workshop.id]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("is_active", resp.json())
        workshop.refresh_from_db()
        self.assertTrue(workshop.is_active)

    def test_cannot_flip_last_workshop_subtype_off(self) -> None:
        """Flipping is_workshop off the only Workshop subtype empties the pool, so
        default_workshop() would raise (breaks job creation, Xero sync, quote
        import). The serializer must refuse it. The staff-default guard does not
        cover this — it only fires on is_active=False."""
        workshop = LabourSubtype.objects.get(name="Workshop")
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[workshop.id]),
            {"is_workshop": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("only active Workshop", str(resp.json()))
        workshop.refresh_from_db()
        self.assertTrue(workshop.is_workshop)

    def test_cannot_deactivate_last_workshop_subtype(self) -> None:
        """Deactivating the only active Workshop subtype is blocked even when no
        staff defaults to it — distinct from (and beyond) the staff-default guard."""
        workshop = LabourSubtype.objects.get(name="Workshop")
        # Remove any staff-default dependency so the last-workshop guard, not the
        # staff-default guard, is what rejects the change.
        Staff.objects.filter(default_labour_subtype=workshop).update(
            default_labour_subtype=LabourSubtype.default_non_workshop()
        )
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[workshop.id]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("only active Workshop", str(resp.json()))
        workshop.refresh_from_db()
        self.assertTrue(workshop.is_active)

    def test_job_rate_patch_rejects_unseeded_subtype_without_writing(self) -> None:
        """A subtype with no rate row on the job is rejected up front (400) and no
        other rate is written — no partial update (ADR 0015 + ADR 0019)."""
        onsite = LabourSubtype.objects.get(name="Onsite")
        original = self.job.labour_rates.get(labour_subtype=onsite).charge_out_rate
        # Exists but never seeded onto this job (direct create skips the backfill).
        orphan = LabourSubtype.objects.create(
            name="Orphan",
            display_order=98,
            is_active=True,
            is_workshop=False,
            counts_for_scheduling=False,
            default_charge_out_rate=Decimal("70.00"),
        )
        resp = self.api.patch(
            reverse("jobs:job_labour_rates_rest", args=[self.job.id]),
            {
                "rates": [
                    {"labour_subtype": str(onsite.id), "charge_out_rate": "999.00"},
                    {"labour_subtype": str(orphan.id), "charge_out_rate": "70.00"},
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("rates", resp.json())
        # The valid subtype's rate must be untouched (validate-first, no partial write).
        self.assertEqual(
            self.job.labour_rates.get(labour_subtype=onsite).charge_out_rate, original
        )

    def test_deactivate_succeeds_and_drops_from_active_list(self) -> None:
        delivery = LabourSubtype.objects.get(name="Delivery")
        self.assertFalse(Staff.objects.filter(default_labour_subtype=delivery).exists())
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[delivery.id]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        delivery.refresh_from_db()
        self.assertFalse(delivery.is_active)
        # Dropped from the active dropdown source and from new-job seeding.
        active = self.api.get(reverse("jobs:labour_subtype_list_rest"))
        self.assertNotIn("Delivery", {row["name"] for row in active.json()})
        later = self._create_job("Post-Deactivation Job")
        self.assertNotIn(
            "Delivery",
            set(later.labour_rates.values_list("labour_subtype__name", flat=True)),
        )

    def test_reactivation_backfills_jobs_created_while_inactive(self) -> None:
        delivery = LabourSubtype.objects.get(name="Delivery")
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[delivery.id]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        later = self._create_job("Created While Delivery Inactive")
        self.assertFalse(later.labour_rates.filter(labour_subtype=delivery).exists())

        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[delivery.id]),
            {"is_active": True},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            later.labour_rates.get(labour_subtype=delivery).charge_out_rate,
            delivery.default_charge_out_rate,
        )

    def test_reactivation_preserves_existing_job_rates(self) -> None:
        delivery = LabourSubtype.objects.get(name="Delivery")
        existing_rate = self.job.labour_rates.get(labour_subtype=delivery)
        existing_rate.charge_out_rate = Decimal("222.00")
        existing_rate.save(update_fields=["charge_out_rate"])
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[delivery.id]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        later = self._create_job("Missing Delivery Rate")

        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[delivery.id]),
            {"is_active": True},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        existing_rate.refresh_from_db()
        self.assertEqual(existing_rate.charge_out_rate, Decimal("222.00"))
        self.assertEqual(
            later.labour_rates.get(labour_subtype=delivery).charge_out_rate,
            delivery.default_charge_out_rate,
        )

    def test_reactivation_backfills_shop_jobs_at_zero(self) -> None:
        delivery = LabourSubtype.objects.get(name="Delivery")
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[delivery.id]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        shop_job = Job(name="Shop Job Created While Delivery Inactive")
        shop_job.shop_job = True
        shop_job.save(staff=self.test_staff)

        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[delivery.id]),
            {"is_active": True},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            shop_job.labour_rates.get(labour_subtype=delivery).charge_out_rate,
            Decimal("0.00"),
        )

    def test_negative_rate_rejected(self) -> None:
        resp = self.api.post(
            reverse("jobs:labour_subtype_manage_list_rest"),
            {
                "name": "Bad Rate",
                "display_order": 99,
                "is_workshop": False,
                "counts_for_scheduling": False,
                "default_charge_out_rate": "-5.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_negative_rate_patch_rejected(self) -> None:
        onsite = LabourSubtype.objects.get(name="Onsite")
        original_rate = onsite.default_charge_out_rate
        resp = self.api.patch(
            reverse("jobs:labour_subtype_manage_detail_rest", args=[onsite.id]),
            {"default_charge_out_rate": "-5.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        onsite.refresh_from_db()
        self.assertEqual(onsite.default_charge_out_rate, original_rate)

    def test_negative_job_labour_rate_patch_rejected(self) -> None:
        onsite = LabourSubtype.objects.get(name="Onsite")
        rate = self.job.labour_rates.get(labour_subtype=onsite)
        original_rate = rate.charge_out_rate
        resp = self.api.patch(
            reverse("jobs:job_labour_rates_rest", args=[self.job.id]),
            {
                "rates": [
                    {
                        "labour_subtype": str(onsite.id),
                        "charge_out_rate": "-1.00",
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        rate.refresh_from_db()
        self.assertEqual(rate.charge_out_rate, original_rate)

    def test_job_labour_rate_patch_event_renders_in_timeline(self) -> None:
        """A rate edit must write the event shape the timeline data model requires.

        The regression was `pricing_changed.detail.changes` being written as
        strings while JobEvent rendering requires change dictionaries. A
        write-only test let invalid model data through; this follows the
        user-visible PATCH -> timeline-read path so the strict consumer enforces
        the contract.
        """
        workshop = LabourSubtype.objects.get(name="Workshop")

        patch_resp = self.api.patch(
            reverse("jobs:job_labour_rates_rest", args=[self.job.id]),
            {
                "rates": [
                    {
                        "labour_subtype": str(workshop.id),
                        "charge_out_rate": "125.00",
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 200, patch_resp.content)

        timeline_resp = self.api.get(
            reverse("jobs:job_timeline_rest", args=[self.job.id])
        )

        self.assertEqual(timeline_resp.status_code, 200, timeline_resp.content)
        descriptions = {
            entry["description"] for entry in timeline_resp.json()["timeline"]
        }
        self.assertIn(
            "Workshop charge-out rate changed from '$105.00/hour' to '$125.00/hour'",
            descriptions,
        )

    def test_database_rejects_negative_subtype_default_rate(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            LabourSubtype.objects.create(
                name="Negative Default",
                display_order=99,
                default_charge_out_rate=Decimal("-0.01"),
            )

    def test_database_rejects_negative_job_labour_rate(self) -> None:
        onsite = LabourSubtype.objects.get(name="Onsite")
        rate = self.job.labour_rates.get(labour_subtype=onsite)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.job.labour_rates.filter(id=rate.id).update(
                charge_out_rate=Decimal("-0.01")
            )

    def test_backfill_service_is_idempotent(self) -> None:
        rush = LabourSubtype.objects.create(
            name="Rush",
            display_order=99,
            default_charge_out_rate=Decimal("200.00"),
        )
        first = seed_subtype_onto_existing_jobs(rush)
        self.assertGreater(first, 0)
        # Running again creates no duplicates (rows already exist).
        self.assertEqual(seed_subtype_onto_existing_jobs(rush), 0)

    def test_backfill_service_tolerates_benign_unique_conflict(self) -> None:
        rush = LabourSubtype.objects.create(
            name="Rush",
            display_order=99,
            default_charge_out_rate=Decimal("200.00"),
        )
        original_bulk_create = JobLabourRate.objects.bulk_create

        def concurrent_insert(
            rows: list[JobLabourRate],
            batch_size: int | None = None,
            ignore_conflicts: bool = False,
            update_conflicts: bool = False,
            update_fields: list[str] | None = None,
            unique_fields: list[str] | None = None,
        ) -> list[JobLabourRate]:
            first = rows[0]
            JobLabourRate.objects.create(
                job_id=first.job_id,
                labour_subtype=rush,
                charge_out_rate=first.charge_out_rate,
            )
            return original_bulk_create(
                rows,
                batch_size=batch_size,
                ignore_conflicts=ignore_conflicts,
                update_conflicts=update_conflicts,
                update_fields=update_fields,
                unique_fields=unique_fields,
            )

        with patch.object(JobLabourRate.objects, "bulk_create", concurrent_insert):
            seed_subtype_onto_existing_jobs(rush)

        self.assertFalse(
            Job.objects.exclude(labour_rates__labour_subtype=rush).exists()
        )

    def test_backfill_service_raises_when_invariant_remains_broken(self) -> None:
        rush = LabourSubtype.objects.create(
            name="Rush",
            display_order=99,
            default_charge_out_rate=Decimal("200.00"),
        )

        with (
            patch.object(JobLabourRate.objects, "bulk_create", return_value=[]),
            self.assertRaisesRegex(
                RuntimeError,
                "Failed to satisfy active labour-subtype rate-row invariant",
            ),
        ):
            seed_subtype_onto_existing_jobs(rush)

    def test_backfill_service_rejects_inactive_subtype(self) -> None:
        rush = LabourSubtype.objects.create(
            name="Rush",
            display_order=99,
            is_active=False,
            default_charge_out_rate=Decimal("200.00"),
        )

        with self.assertRaisesRegex(ValueError, "Cannot seed inactive"):
            seed_subtype_onto_existing_jobs(rush)


class CompanyDefaultsChargeOutRateRemovedTests(BaseTestCase):
    """charge_out_rate is gone from CompanyDefaults; Workshop subtype is the source."""

    def test_company_defaults_has_no_charge_out_rate(self) -> None:
        from apps.workflow.models import CompanyDefaults

        field_names = {f.name for f in CompanyDefaults._meta.get_fields()}
        self.assertNotIn("charge_out_rate", field_names)

    def test_quote_importer_workshop_rate_uses_workshop_subtype(self) -> None:
        from apps.job.importers.quote_spreadsheet import _workshop_charge_out_rate

        LabourSubtype.objects.filter(name="Workshop").update(
            default_charge_out_rate=Decimal("123.00")
        )
        self.assertEqual(_workshop_charge_out_rate(), Decimal("123.00"))
