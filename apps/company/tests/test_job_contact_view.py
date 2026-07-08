"""Job contact endpoint tests.

Guards the GET/PUT contract of the job-contact endpoint end-to-end (URL
routing, permissions, and response-serializer validation), which the
job-settings tab uses to load and reassign a job's contact person.
"""

from typing import TYPE_CHECKING, Any

from django.urls import reverse
from django.utils import timezone

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

from apps.company.models import ClientContact, Company
from apps.job.models import Job
from apps.testing import BaseAPITestCase
from apps.workflow.models import XeroPayItem


class JobContactViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)
        self.job_company = Company.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )

    def _contact(self, name: str) -> ClientContact:
        return ClientContact.objects.create(company=self.job_company, name=name)

    def _job(self, contact: ClientContact) -> Job:
        job: Job = Job.objects.create(
            name="Contact Job",
            company=self.job_company,
            contact=contact,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )
        return job

    def _url(self, job: Job) -> str:
        return reverse("companies:job_contact_rest", kwargs={"job_id": job.id})

    def _get(self, job: Job) -> "_MonkeyPatchedResponse":
        return self.client.get(self._url(job))

    def _put(self, job: Job, payload: dict[str, Any]) -> "_MonkeyPatchedResponse":
        return self.client.put(self._url(job), payload, format="json")

    def _put_payload(self, contact: ClientContact) -> dict[str, Any]:
        return {
            "id": str(contact.id),
            "name": contact.name,
            "email": contact.email,
            "position": contact.position,
            "is_primary": contact.is_primary,
            "notes": contact.notes,
        }

    def test_get_returns_job_contact(self) -> None:
        contact = self._contact("Jane Smith")
        job = self._job(contact)

        response = self._get(job)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], str(contact.id))
        self.assertEqual(body["name"], "Jane Smith")

    def test_put_response_reflects_new_contact(self) -> None:
        job = self._job(self._contact("Jane Smith"))
        replacement = self._contact("Bob Jones")

        response = self._put(job, self._put_payload(replacement))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(replacement.id))
        job.refresh_from_db()
        self.assertEqual(job.contact_id, replacement.id)

    def test_put_ignores_unrecognized_field(self) -> None:
        """Phones live in ClientContactMethod; the job contact update path
        only reassigns the contact FK. An unexpected key (here the removed
        phone field) must be ignored, not written or echoed back."""
        job = self._job(self._contact("Jane Smith"))
        replacement = self._contact("Bob Jones")
        payload = self._put_payload(replacement) | {"phone": "09 999 9999"}

        response = self._put(job, payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], str(replacement.id))
        self.assertNotIn("phone", body)
        job.refresh_from_db()
        self.assertEqual(job.contact_id, replacement.id)
