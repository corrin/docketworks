from decimal import Decimal
from uuid import uuid4

from django.utils import timezone

from apps.company.models import Company, Person
from apps.job.models import Job, JobDeltaRejection, JobEvent
from apps.job.models.costing import CostLine
from apps.job.services.job_rest_service import DeltaValidationError, JobRestService
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults, XeroPayItem


class JobRestServiceCreateJobTests(BaseTestCase):
    def test_fixed_price_create_copies_estimate_pay_item_without_relation_loads(self):
        company = Company.objects.create(
            name="Create Job Company",
            xero_last_modified=timezone.now(),
        )

        job = JobRestService.create_job(
            {
                "name": "Fixed Price Job",
                "company_id": company.id,
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
        company = Company.objects.create(
            name="Edit Job Company",
            xero_last_modified=timezone.now(),
        )
        person = Person.objects.create(name="Site Contact")
        job = Job.objects.create(
            name="Editable Job",
            company=company,
            person=person,
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


class JobRestServiceDeltaRejectionRecordingTests(BaseTestCase):
    def test_hard_checksum_mismatch_records_the_rejection(self):
        """A refused delta must leave a JobDeltaRejection explaining why.

        ``DeltaValidationError`` subclasses ``PreconditionFailed``. If the
        broader handler is ordered first it swallows the specific one, and
        because ``soft_fail_context`` is still None that early in the update
        the rejection is dropped entirely — the only record of why a client's
        edit was refused disappears.
        """
        defaults = CompanyDefaults.get_solo()
        defaults.job_delta_soft_fail = False
        defaults.save(update_fields=["job_delta_soft_fail"])

        company = Company.objects.create(
            name="Delta Reject Company",
            xero_last_modified=timezone.now(),
        )
        job = Job.objects.create(
            name="Rejectable Job",
            company=company,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )

        payload = {
            "change_id": str(uuid4()),
            "fields": ["description"],
            "before": {"description": job.description},
            "after": {"description": "Edited elsewhere"},
            "before_checksum": "stale-checksum-from-an-older-read",
        }

        with self.assertRaises(DeltaValidationError):
            JobRestService.update_job(job.id, payload, self.test_staff)

        rejection = JobDeltaRejection.objects.get()
        self.assertIn("checksum mismatch", rejection.reason.lower())
        self.assertEqual(str(rejection.change_id), payload["change_id"])
