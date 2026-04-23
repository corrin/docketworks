from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError

from apps.client.models import Client
from apps.job.models import CostLine, Job
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


class CostLineSchemaValidationTests(BaseTestCase):

    def setUp(self) -> None:
        self.client = Client.objects.create(
            name="Test Client",
            email="test@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.xero_pay_item = XeroPayItem.get_ordinary_time()
        self.job = Job.objects.create(
            job_number=1,
            name="CostLine Schema Test",
            charge_out_rate=Decimal("120.00"),
            client=self.client,
            default_xero_pay_item=self.xero_pay_item,
            staff=self.test_staff,
        )
        # Use the auto-created CostSet from Job.save()
        self.cost_set = self.job.latest_actual

    def _build_cost_line(self, **overrides) -> CostLine:
        base_kwargs = {
            "cost_set": self.cost_set,
            "kind": "time",
            "desc": "Schema test line",
            "quantity": Decimal("1.000"),
            "unit_cost": Decimal("10.00"),
            "unit_rev": Decimal("15.00"),
            "accounting_date": date.today(),
            "meta": {},
            "ext_refs": {},
            "xero_pay_item": self.xero_pay_item,
        }
        base_kwargs.update(overrides)
        return CostLine(**base_kwargs)

    def test_time_meta_allows_known_keys(self) -> None:
        meta = {
            "staff_id": str(uuid4()),
            "date": date.today().isoformat(),
            "is_billable": True,
            "wage_rate_multiplier": 1.5,
            "wage_rate": 45.00,  # JSON requires float, not Decimal
            "charge_out_rate": 90.00,
        }
        line = self._build_cost_line(meta=meta)
        # Should not raise ValidationError
        line.full_clean()

    def test_meta_rejects_unknown_keys(self) -> None:
        line = self._build_cost_line(
            meta={"staff_id": str(uuid4()), "unexpected": "value"}
        )
        with self.assertRaises(ValidationError) as exc:
            line.full_clean()
        self.assertIn("meta", exc.exception.message_dict)

    def test_ext_refs_reject_unknown_keys(self) -> None:
        line = self._build_cost_line(ext_refs={"experiment": "value"})
        with self.assertRaises(ValidationError) as exc:
            line.full_clean()
        self.assertIn("ext_refs", exc.exception.message_dict)

    def test_save_invokes_schema_validation(self) -> None:
        line = self._build_cost_line(
            meta={"staff_id": str(uuid4()), "unknown_field": "value"}
        )
        with self.assertRaises(ValidationError):
            line.save()

    def test_time_entry_without_xero_pay_item_fails_for_actual(self) -> None:
        """Actual CostSet time entries MUST have xero_pay_item."""
        # self.cost_set is already an actual CostSet from setUp
        self.assertEqual(self.cost_set.kind, "actual")
        line = self._build_cost_line(xero_pay_item=None)
        with self.assertRaises(ValidationError) as exc:
            line.full_clean()
        self.assertIn(
            "Actual time entries must have xero_pay_item set.",
            str(exc.exception),
        )

    def test_time_entry_without_xero_pay_item_ok_for_estimate(self) -> None:
        """Estimate CostSet time entries do NOT require xero_pay_item."""
        # Job.save() auto-creates estimate, quote, and actual CostSets
        estimate_cost_set = self.job.latest_estimate
        self.assertEqual(estimate_cost_set.kind, "estimate")
        line = self._build_cost_line(cost_set=estimate_cost_set, xero_pay_item=None)
        # Should not raise ValidationError
        line.full_clean()

    def test_time_entry_without_xero_pay_item_ok_for_quote(self) -> None:
        """Quote CostSet time entries do NOT require xero_pay_item."""
        # Job.save() auto-creates estimate, quote, and actual CostSets
        quote_cost_set = self.job.latest_quote
        self.assertEqual(quote_cost_set.kind, "quote")
        line = self._build_cost_line(cost_set=quote_cost_set, xero_pay_item=None)
        # Should not raise ValidationError
        line.full_clean()
