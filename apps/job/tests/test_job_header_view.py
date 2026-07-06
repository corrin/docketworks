"""Job header endpoint tests.

Guards the phone the job-settings tab shows for the job's client, and the
query shape of the header fetch (the phone must come from a queryset
annotation, never a lazy contact_methods query — KAN-281 nplusone 500).
"""

from typing import TYPE_CHECKING

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

from apps.client.models import Client, ClientContactMethod
from apps.job.models import Job
from apps.job.serializers.job_serializer import JobHeaderResponseSerializer
from apps.testing import BaseAPITestCase
from apps.workflow.models import XeroPayItem


class JobHeaderViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)

    def _job(self, *, job_client: Client | None) -> Job:
        job: Job = Job.objects.create(
            name="Header Job",
            client=job_client,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )
        return job

    def _client_with_phones(self) -> Client:
        job_client = Client.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )
        ClientContactMethod.objects.create(
            client=job_client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            label="AAA sorts first",
        )
        ClientContactMethod.objects.create(
            client=job_client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 222 2222",
            label="ZZZ sorts last",
            is_primary=True,
        )
        ClientContactMethod.objects.create(
            client=job_client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 333 3333",
            label="MMM middle",
        )
        return job_client

    def _get_header(
        self, job: Job, if_none_match: str | None = None
    ) -> "_MonkeyPatchedResponse":
        url = reverse("jobs:job_header_rest", kwargs={"job_id": job.id})
        if if_none_match is not None:
            return self.client.get(url, HTTP_IF_NONE_MATCH=if_none_match)
        return self.client.get(url)

    def test_returns_primary_client_phone(self) -> None:
        job = self._job(job_client=self._client_with_phones())

        response = self._get_header(job)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client_phone"], "09 222 2222")

    def test_empty_phone_when_client_has_no_phone_methods(self) -> None:
        job_client = Client.objects.create(
            name="Phoneless Ltd", xero_last_modified=timezone.now()
        )
        job = self._job(job_client=job_client)

        response = self._get_header(job)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client_phone"], "")

    def test_empty_phone_when_job_has_no_client(self) -> None:
        job = self._job(job_client=None)

        response = self._get_header(job)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client_phone"], "")

    def test_phone_does_not_add_a_lazy_query(self) -> None:
        """The phone must ride the job SELECT, not a per-request lazy query."""
        job = self._job(job_client=self._client_with_phones())

        with CaptureQueriesContext(connection) as captured:
            response = self._get_header(job)

        self.assertEqual(response.status_code, 200)
        lazy_phone_queries = [
            q["sql"]
            for q in captured.captured_queries
            if q["sql"].startswith('SELECT "client_clientcontactmethod"')
        ]
        self.assertEqual(lazy_phone_queries, [])

    def test_etag_round_trip_returns_304(self) -> None:
        job = self._job(job_client=self._client_with_phones())

        first = self._get_header(job)
        etag = first.headers["ETag"]
        second = self._get_header(job, if_none_match=etag)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 304)

    def test_serializer_requires_annotated_instance(self) -> None:
        """Serializing an unannotated job must crash loudly, never lazy-query."""
        job = self._job(job_client=self._client_with_phones())
        unannotated = Job.objects.select_related("client").get(id=job.id)

        with self.assertRaises(Exception) as ctx:
            JobHeaderResponseSerializer(unannotated).data
        self.assertIn("client_phone", str(ctx.exception))
