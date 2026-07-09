"""Job header endpoint tests.

Guards the ETag/If-None-Match round trip on the job header fetch, and the
null-company contract (shell jobs have no company; every company/contact field
must serialize as null, not 500).
"""

from typing import TYPE_CHECKING

from django.urls import reverse
from django.utils import timezone

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

from apps.company.models import Company
from apps.job.models import Job
from apps.testing import BaseAPITestCase
from apps.workflow.models import XeroPayItem


class JobHeaderViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)

    def _job(self, *, job_company: Company | None) -> Job:
        job: Job = Job.objects.create(
            name="Header Job",
            company=job_company,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )
        return job

    def _get_header(
        self, job: Job, if_none_match: str | None = None
    ) -> "_MonkeyPatchedResponse":
        url = reverse("jobs:job_header_rest", kwargs={"job_id": job.id})
        if if_none_match is not None:
            return self.client.get(url, HTTP_IF_NONE_MATCH=if_none_match)
        return self.client.get(url)

    def test_header_for_job_without_company(self) -> None:
        job = self._job(job_company=None)

        response = self._get_header(job)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["company_id"])
        self.assertIsNone(payload["company_name"])
        self.assertIsNone(payload["person_id"])
        self.assertIsNone(payload["person_name"])

    def test_etag_round_trip_returns_304(self) -> None:
        job_company = Company.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )
        job = self._job(job_company=job_company)

        first = self._get_header(job)
        etag = first.headers["ETag"]
        second = self._get_header(job, if_none_match=etag)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 304)
