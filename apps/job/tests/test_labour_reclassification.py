"""Guards migration 0100_reclassify_labour_cost_lines.

Builds legacy-shaped cost lines, runs the migration's ``forward`` against the
live app registry (the same import-the-migration pattern as
CostLineSubtypeBackfillRuleTests in test_labour_subtypes.py), and asserts each
phase's rules. The migration is forward-only, so there is no reverse to test.
"""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal
from typing import Any

from django.apps import apps as live_apps

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import CostLine, CostSet, Job, LabourSubtype
from apps.job.models.costline_validators import (
    validate_costline_ext_refs,
    validate_costline_meta,
)
from apps.job.services.workshop_service import WorkshopTimesheetService
from apps.purchasing.models import Stock
from apps.testing import BaseTestCase

# Local Stock UUID PKs the cost lines reference (arbitrary in tests — the
# migration resolves the real local PK from xero_id at runtime).
ONSITE_LABOUR_STOCK_ID = "436e3dd1-8369-4076-859c-496cded0149d"
QUOTE_ONSITE_STOCK_ID = "dac02069-7002-4db0-910d-bde31c8168c1"
GENERIC_LABOUR_STOCK_ID = "fd0ee1a5-3b0c-48c3-a475-74385149fab1"
# Stock catalogue codes the migrations search by (must match the migration
# constants).
ONSITE_LABOUR_ITEM_CODE = "LABOUR ONSITE"
QUOTE_ONSITE_ITEM_CODE = "Quote Onsite"
GENERIC_LABOUR_ITEM_CODE = "LABOUR"

_migration = importlib.import_module(
    "apps.job.migrations.0100_reclassify_labour_cost_lines"
)
_migration_0101 = importlib.import_module(
    "apps.job.migrations.0101_reclassify_generic_labour_cost_lines"
)


def run_migration() -> None:
    _migration.forward(live_apps, None)


def run_migration_0101() -> None:
    _migration_0101.forward(live_apps, None)


class OnsiteConversionTests(BaseTestCase):
    """Phase 1 — onsite stock-path material/adjust lines become labour."""

    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Onsite Client",
            email="onsite@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job(name="Onsite Job", client=self.client_obj)
        self.job.save(staff=self.test_staff)
        self.estimate = self.job.cost_sets.get(kind="estimate")
        self.actual = self.job.cost_sets.get(kind="actual")
        # The migration resolves the local stock PK from xero_id, so the two
        # onsite stock items must exist with the right xero_id <-> local id.
        Stock.objects.create(
            id=ONSITE_LABOUR_STOCK_ID,
            item_code=ONSITE_LABOUR_ITEM_CODE,
            description="ONSITE LABOUR CHARGES",
            quantity=Decimal("0.00"),
            unit_cost=Decimal("40.00"),
            is_active=True,
        )
        Stock.objects.create(
            id=QUOTE_ONSITE_STOCK_ID,
            item_code=QUOTE_ONSITE_ITEM_CODE,
            description="Quote onsite charge",
            quantity=Decimal("0.00"),
            unit_cost=Decimal("40.00"),
            is_active=True,
        )

    def _material(self, cost_set: CostSet, **kw: Any) -> CostLine:
        defaults = dict(
            cost_set=cost_set,
            kind="material",
            desc="ONSITE LABOUR CHARGES",
            accounting_date=date.today(),
            quantity=Decimal("1.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=Decimal("165.00"),
            ext_refs={"stock_id": ONSITE_LABOUR_STOCK_ID},
        )
        defaults.update(kw)
        return CostLine.objects.create(**defaults)

    def test_estimate_material_becomes_onsite_time(self) -> None:
        line = self._material(self.estimate)
        run_migration()
        line.refresh_from_db()
        self.assertEqual(line.kind, "time")
        assert line.labour_subtype is not None
        self.assertEqual(line.labour_subtype.name, "Onsite")
        self.assertNotIn("stock_id", line.ext_refs)
        # Converted line must validate under the TIME schema for future saves.
        validate_costline_meta(line.meta, "time")
        validate_costline_ext_refs(line.ext_refs)

    def test_quote_onsite_stock_becomes_onsite_quoting(self) -> None:
        line = self._material(
            self.estimate,
            desc="Quote onsite charge -SITE VISIT",
            ext_refs={"stock_id": QUOTE_ONSITE_STOCK_ID},
        )
        run_migration()
        line.refresh_from_db()
        self.assertEqual(line.kind, "time")
        assert line.labour_subtype is not None
        self.assertEqual(line.labour_subtype.name, "Onsite quoting")

    def test_desc_only_onsite_quote_routes_to_onsite_quoting(self) -> None:
        # No stock link. Matches phase 1 via 'onsite charge', and the 'quote
        # onsite' signal routes it to Onsite quoting rather than Onsite.
        line = self._material(self.estimate, desc="QUOTE ONSITE CHARGE", ext_refs={})
        run_migration()
        line.refresh_from_db()
        assert line.labour_subtype is not None
        self.assertEqual(line.labour_subtype.name, "Onsite quoting")

    def test_revenue_repair_explicit_patterns(self) -> None:
        corrupt_165 = self._material(
            self.estimate, unit_cost=Decimal("165.00"), unit_rev=Decimal("198.00")
        )
        corrupt_150 = self._material(
            self.estimate, unit_cost=Decimal("150.00"), unit_rev=Decimal("180.00")
        )
        # rev == cost*1.2 but a real, already-correct paid-job line — must NOT move.
        correct_13750 = self._material(
            self.estimate, unit_cost=Decimal("137.50"), unit_rev=Decimal("165.00")
        )
        run_migration()
        for ln in (corrupt_165, corrupt_150, correct_13750):
            ln.refresh_from_db()
        self.assertEqual(
            (corrupt_165.unit_cost, corrupt_165.unit_rev),
            (Decimal("0.00"), Decimal("165.00")),
        )
        self.assertEqual(
            (corrupt_150.unit_cost, corrupt_150.unit_rev),
            (Decimal("0.00"), Decimal("150.00")),
        )
        self.assertEqual(
            (correct_13750.unit_cost, correct_13750.unit_rev),
            (Decimal("137.50"), Decimal("165.00")),
        )

    def test_actual_material_becomes_adjust_and_drops_consumed_by(self) -> None:
        line = self._material(
            self.actual,
            unit_cost=Decimal("40.00"),
            unit_rev=Decimal("48.00"),
            meta={"consumed_by": "c198ccc4-d2b0-474a-ada4-b7d02168943f"},
        )
        run_migration()
        line.refresh_from_db()
        self.assertEqual(line.kind, "adjust")
        self.assertIsNone(line.labour_subtype)
        # (40,48) markup repair -> (40,165)
        self.assertEqual(
            (line.unit_cost, line.unit_rev), (Decimal("40.00"), Decimal("165.00"))
        )
        # consumed_by is not valid under the ADJUSTMENT schema — must be dropped.
        self.assertNotIn("consumed_by", line.meta)
        validate_costline_meta(line.meta, "adjust")
        self.assertNotIn("stock_id", line.ext_refs)


class KeywordRelabelTests(BaseTestCase):
    """Phases 2 and 3 — relabel actual time lines off the blanket Workshop."""

    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Relabel Client",
            email="relabel@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job(name="Relabel Job", client=self.client_obj)
        self.job.save(staff=self.test_staff)
        self.workshop_staff = Staff.objects.create_user(
            email="ws@example.com",
            password="x",
            first_name="Work",
            last_name="Shop",
            base_wage_rate=Decimal("40.00"),
            is_workshop_staff=True,
        )
        self.office_staff = Staff.objects.create_user(
            email="off@example.com",
            password="x",
            first_name="Off",
            last_name="Ice",
            base_wage_rate=Decimal("40.00"),
            is_workshop_staff=False,
            is_office_staff=True,
        )
        self.workshop = LabourSubtype.objects.get(name="Workshop")

    def _actual_time(self, staff: Staff, desc: str) -> CostLine:
        """Create a proper actual time line, then force it onto Workshop to
        simulate the 0095 blanket-backfill legacy state."""
        line = WorkshopTimesheetService(staff=staff).create_entry(
            {
                "job_id": str(self.job.id),
                "description": desc,
                "hours": Decimal("1.000"),
                "accounting_date": date.today(),
            }
        )
        CostLine.objects.filter(id=line.id).update(labour_subtype=self.workshop)
        line.refresh_from_db()
        return line

    def _subtype_after(self, staff: Staff, desc: str) -> str:
        line = self._actual_time(staff, desc)
        run_migration()
        line.refresh_from_db()
        assert line.labour_subtype is not None
        return line.labour_subtype.name

    def test_keyword_precedence(self) -> None:
        cases = {
            "ONSITE QUOTE": "Onsite quoting",
            "SITE MEASURE": "Onsite quoting",
            "QUOTE AND SITE VISIT": "Onsite quoting",
            "SUPERVISION": "Supervision",
            "DELIVER FLASHINGS": "Delivery",
            "INSTALL HANDRAIL": "Onsite",
            "QUOTE AND CUT": "Quoting",
        }
        for desc, expected in cases.items():
            with self.subTest(desc=desc):
                self.assertEqual(
                    self._subtype_after(self.workshop_staff, desc), expected
                )

    def test_office_staff_remainder_goes_to_admin(self) -> None:
        # No keyword in the description, performed by office staff -> Admin.
        self.assertEqual(self._subtype_after(self.office_staff, "PAPERWORK"), "Admin")

    def test_workshop_staff_no_keyword_stays_workshop(self) -> None:
        self.assertEqual(
            self._subtype_after(self.workshop_staff, "GENERAL FABRICATION"), "Workshop"
        )


class GenericLabourReclassificationTests(BaseTestCase):
    """Guards migration 0101 — generic LABOUR stock-item cost lines."""

    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Generic Labour Client",
            email="genlabour@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job(name="Generic Labour Job", client=self.client_obj)
        self.job.save(staff=self.test_staff)
        self.estimate = self.job.cost_sets.get(kind="estimate")
        self.actual = self.job.cost_sets.get(kind="actual")
        # The generic LABOUR stock item the migration retires.
        self.stock = Stock.objects.create(
            id=GENERIC_LABOUR_STOCK_ID,
            item_code=GENERIC_LABOUR_ITEM_CODE,
            description="LABOUR CHARGE PER HOUR",
            quantity=Decimal("0.00"),
            unit_cost=Decimal("32.00"),
            is_active=True,
        )

    def _line(self, cost_set: CostSet, kind: str, **kw: Any) -> CostLine:
        defaults = dict(
            cost_set=cost_set,
            kind=kind,
            desc="LABOUR CHARGE PER HOUR",
            accounting_date=date.today(),
            quantity=Decimal("1.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=Decimal("110.00"),
            ext_refs={"stock_id": GENERIC_LABOUR_STOCK_ID},
        )
        defaults.update(kw)
        return CostLine.objects.create(**defaults)

    def test_estimate_material_becomes_workshop_time(self) -> None:
        line = self._line(self.estimate, "material", unit_cost=Decimal("32.00"))
        run_migration_0101()
        line.refresh_from_db()
        self.assertEqual(line.kind, "time")
        assert line.labour_subtype is not None
        self.assertEqual(line.labour_subtype.name, "Workshop")
        self.assertNotIn("stock_id", line.ext_refs)
        validate_costline_meta(line.meta, "time")
        validate_costline_ext_refs(line.ext_refs)

    def test_actual_material_becomes_adjust_and_drops_consumed_by(self) -> None:
        line = self._line(
            self.actual,
            "material",
            meta={"consumed_by": "c198ccc4-d2b0-474a-ada4-b7d02168943f"},
        )
        run_migration_0101()
        line.refresh_from_db()
        self.assertEqual(line.kind, "adjust")
        self.assertIsNone(line.labour_subtype)
        self.assertNotIn("consumed_by", line.meta)
        validate_costline_meta(line.meta, "adjust")
        self.assertNotIn("stock_id", line.ext_refs)

    def test_adjust_lines_stay_adjust_with_values_intact(self) -> None:
        # A negative-rev credit/adjustment is a genuine adjustment — keep it.
        credit = self._line(self.actual, "adjust", unit_rev=Decimal("-110.00"))
        quote_adj = self._line(self.estimate, "adjust", unit_rev=Decimal("110.00"))
        run_migration_0101()
        for ln in (credit, quote_adj):
            ln.refresh_from_db()
        self.assertEqual(credit.kind, "adjust")
        self.assertEqual(credit.unit_rev, Decimal("-110.00"))
        self.assertEqual(quote_adj.kind, "adjust")
        self.assertIsNone(credit.labour_subtype)
        for ln in (credit, quote_adj):
            self.assertNotIn("stock_id", ln.ext_refs)

    def test_markup_repair_to_110(self) -> None:
        # rev == cost*1.2 corrupted pairs -> rev 110, cost kept.
        corrupt_pairs = [
            (Decimal("32.00"), Decimal("38.40")),
            (Decimal("43.00"), Decimal("51.60")),
            (Decimal("44.00"), Decimal("52.80")),
        ]
        lines = [
            self._line(self.actual, "material", unit_cost=cost, unit_rev=rev)
            for cost, rev in corrupt_pairs
        ]
        run_migration_0101()
        for line, (cost, _rev) in zip(lines, corrupt_pairs):
            line.refresh_from_db()
            self.assertEqual((line.unit_cost, line.unit_rev), (cost, Decimal("110.00")))

    def test_stock_item_is_retired(self) -> None:
        self._line(self.estimate, "material", unit_cost=Decimal("32.00"))
        run_migration_0101()
        self.stock.refresh_from_db()
        self.assertFalse(self.stock.is_active)
