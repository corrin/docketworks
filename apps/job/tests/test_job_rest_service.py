from decimal import Decimal

from django.utils import timezone

from apps.client.models import Client
from apps.job.models.costing import CostLine
from apps.job.services.job_rest_service import JobRestService
from apps.testing import BaseTestCase


class JobRestServiceCreateJobTests(BaseTestCase):
    def test_fixed_price_create_copies_estimate_pay_item_without_relation_loads(self):
        client = Client.objects.create(
            name="Create Job Client",
            xero_last_modified=timezone.now(),
        )

        job = JobRestService.create_job(
            {
                "name": "Fixed Price Job",
                "client_id": client.id,
                "pricing_methodology": "fixed_price",
                "estimated_materials": Decimal("120.00"),
                "estimated_time": Decimal("2.50"),
            },
            self.test_staff,
        )

        estimate_lines = list(
            CostLine.objects.filter(cost_set=job.latest_estimate).order_by("desc")
        )
        quote_lines = list(
            CostLine.objects.filter(cost_set=job.latest_quote).order_by("desc")
        )
        estimate_pay_items = {
            line.desc: line.xero_pay_item_id for line in estimate_lines
        }
        quote_pay_items = {line.desc: line.xero_pay_item_id for line in quote_lines}

        self.assertEqual(len(quote_lines), len(estimate_lines))
        self.assertEqual(quote_pay_items, estimate_pay_items)
