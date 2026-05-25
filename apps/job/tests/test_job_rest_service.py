from decimal import Decimal

from django.utils import timezone

from apps.client.models import Client, ClientContact
from apps.job.models import Job, JobEvent
from apps.job.models.costing import CostLine
from apps.job.services.job_rest_service import JobRestService
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


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


class JobRestServiceEditTests(BaseTestCase):
    def test_get_job_for_edit_serializes_event_staff(self):
        client = Client.objects.create(
            name="Edit Job Client",
            xero_last_modified=timezone.now(),
        )
        contact = ClientContact.objects.create(client=client, name="Site Contact")
        job = Job.objects.create(
            name="Editable Job",
            client=client,
            contact=contact,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )
        JobEvent.objects.create(
            job=job,
            staff=self.test_staff,
            event_type="job_created",
            detail={"job_name": job.name},
        )

        result = JobRestService.get_job_for_edit(job.id, request=None)

        self.assertEqual(result["events"][0]["staff"], "Test Staff")
