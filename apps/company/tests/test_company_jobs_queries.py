from __future__ import annotations

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.company.models import Company
from apps.company.services.company_rest_service import CompanyRestService
from apps.job.models import Job
from apps.testing import BaseTestCase


class CompanyJobsQueryTests(BaseTestCase):
    """get_company_jobs reads job.quoted per job; without select_related on
    quote that lazy-loads once per job and the dev/E2E n+1 guard raises."""

    def test_get_company_jobs_does_not_lazy_load_quotes(self) -> None:
        company_obj = Company.objects.create(
            name="Company Jobs Query Company",
            email="company-jobs-queries@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        for name in ("Company Jobs Query Job 1", "Company Jobs Query Job 2"):
            job = Job(name=name, company=company_obj)
            job.save(staff=self.test_staff)

        with CaptureQueriesContext(connection) as ctx:
            jobs = CompanyRestService.get_company_jobs(company_obj.id)

        self.assertEqual(len(jobs), 2)
        # exists() guard + the jobs query (quote joined in, not lazy-loaded)
        self.assertLessEqual(len(ctx.captured_queries), 2)
