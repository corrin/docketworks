from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job, LabourSubtype
from apps.job.services.workshop_service import WorkshopTimesheetService
from apps.testing import BaseTestCase


class LabourSubtypeSeedTests(BaseTestCase):
    def test_migrations_seed_current_subtypes(self) -> None:
        names = set(LabourSubtype.objects.values_list("name", flat=True))
        self.assertEqual(
            names,
            {"Workshop", "Admin", "Quoting", "Delivery", "Onsite", "Supervision"},
        )

    def test_current_active_subtypes_exclude_delivery(self) -> None:
        active_names = set(
            LabourSubtype.objects.filter(is_active=True).values_list("name", flat=True)
        )
        self.assertEqual(
            active_names,
            {"Workshop", "Admin", "Quoting", "Onsite", "Supervision"},
        )

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
            {"Workshop", "Admin", "Quoting", "Onsite", "Supervision"},
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
        self.assertEqual(len(subtype_names), 4)

    def test_shop_job_seeds_zero_rates(self) -> None:
        job = Job(name="Shop Labour Rate Job")
        job.shop_job = True
        job.save(staff=self.test_staff)
        rates = list(job.labour_rates.values_list("charge_out_rate", flat=True))
        self.assertEqual(len(rates), 5)
        self.assertEqual(set(rates), {Decimal("0.00")})


class CostLineSubtypeBackfillRuleTests(BaseTestCase):
    """Guards the KAN-230 migration rule for classifying legacy time lines."""

    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Backfill Client",
            email="backfill@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job(name="Backfill Job", client=self.client_obj)
        self.job.save(staff=self.test_staff)

    def test_office_time_desc_goes_to_office_admin_rest_to_workshop(self) -> None:
        import importlib

        from django.apps import apps as live_apps

        from apps.job.models import CostLine

        estimate = self.job.cost_sets.get(kind="estimate")
        workshop_subtype = LabourSubtype.objects.get(name="Workshop")
        LabourSubtype.objects.filter(name="Admin").update(name="Office/Admin")
        office_line = CostLine.objects.create(
            cost_set=estimate,
            kind="time",
            desc="Estimated office time",
            accounting_date=date.today(),
            labour_subtype=workshop_subtype,
        )
        workshop_line = CostLine.objects.create(
            cost_set=estimate,
            kind="time",
            desc="Some legacy time entry",
            accounting_date=date.today(),
            labour_subtype=workshop_subtype,
        )
        # Simulate pre-migration rows (no subtype); update() bypasses
        # CostLine.save()'s validation, exactly like the legacy data
        CostLine.objects.filter(id__in=[office_line.id, workshop_line.id]).update(
            labour_subtype=None
        )

        migration = importlib.import_module(
            "apps.job.migrations.0095_backfill_job_labour_rates_and_costline_subtypes"
        )
        migration.backfill_costline_subtypes(live_apps, None)

        office_line.refresh_from_db()
        workshop_line.refresh_from_db()
        assert office_line.labour_subtype is not None
        assert workshop_line.labour_subtype is not None
        self.assertEqual(office_line.labour_subtype.name, "Office/Admin")
        self.assertEqual(workshop_line.labour_subtype.name, "Workshop")


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
