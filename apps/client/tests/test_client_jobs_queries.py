from __future__ import annotations

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.client.models import Client
from apps.client.services.client_rest_service import ClientRestService
from apps.job.models import Job
from apps.testing import BaseTestCase


class ClientJobsQueryTests(BaseTestCase):
    """get_client_jobs reads job.quoted per job; without select_related on
    quote that lazy-loads once per job and the dev/E2E n+1 guard raises."""

    def test_get_client_jobs_does_not_lazy_load_quotes(self) -> None:
        client_obj = Client.objects.create(
            name="Client Jobs Query Client",
            email="client-jobs-queries@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        for name in ("Client Jobs Query Job 1", "Client Jobs Query Job 2"):
            job = Job(name=name, client=client_obj)
            job.save(staff=self.test_staff)

        with CaptureQueriesContext(connection) as ctx:
            jobs = ClientRestService.get_client_jobs(client_obj.id)

        self.assertEqual(len(jobs), 2)
        # exists() guard + the jobs query (quote joined in, not lazy-loaded)
        self.assertLessEqual(len(ctx.captured_queries), 2)
