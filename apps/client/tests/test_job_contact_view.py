"""Job contact endpoint tests.

Guards the phone the job-settings tab shows for the job's contact person
(KAN-281). The response serializer must not drop the phone the service
annotates onto the payload.
"""

from typing import TYPE_CHECKING, Any

from django.urls import reverse
from django.utils import timezone

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.job.models import Job
from apps.testing import BaseAPITestCase
from apps.workflow.models import XeroPayItem


class JobContactViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)
        self.job_client = Client.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )

    def _contact(self, name: str, *, phone: str | None) -> ClientContact:
        contact = ClientContact.objects.create(client=self.job_client, name=name)
        if phone is not None:
            ClientContactMethod.objects.create(
                contact=contact,
                method_type=ClientContactMethod.MethodType.PHONE,
                value=phone,
                is_primary=True,
            )
        else:
            pass  # contact deliberately has no phone methods
        return contact

    def _job(self, contact: ClientContact) -> Job:
        job: Job = Job.objects.create(
            name="Contact Job",
            client=self.job_client,
            contact=contact,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )
        return job

    def _url(self, job: Job) -> str:
        return reverse("clients:job_contact_rest", kwargs={"job_id": job.id})

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

    def test_get_returns_contact_phone(self) -> None:
        job = self._job(self._contact("Jane Smith", phone="021 111 111"))

        response = self._get(job)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "021 111 111")

    def test_get_returns_empty_phone_when_contact_has_no_phone_methods(self) -> None:
        job = self._job(self._contact("Jane Smith", phone=None))

        response = self._get(job)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "")

    def test_put_response_includes_new_contact_phone(self) -> None:
        job = self._job(self._contact("Jane Smith", phone="021 111 111"))
        replacement = self._contact("Bob Jones", phone="021 222 222")

        response = self._put(job, self._put_payload(replacement))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "021 222 222")

    def test_put_rejects_phone_in_request_body(self) -> None:
        """Phones live in ClientContactMethod; the job contact update path
        only reassigns the contact FK and must never accept a phone write."""
        job = self._job(self._contact("Jane Smith", phone="021 111 111"))
        replacement = self._contact("Bob Jones", phone="021 222 222")
        payload = self._put_payload(replacement) | {"phone": "09 999 9999"}

        response = self._put(job, payload)

        # The unknown field is ignored; the response still reports the
        # contact's real phone from ClientContactMethod.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "021 222 222")
