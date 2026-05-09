from django.utils import timezone

from apps.client.models import Client, ClientContact
from apps.job.models import Job
from apps.job.services.kanban_service import KanbanService
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


class KanbanSearchTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.xero_pay_item = XeroPayItem.get_ordinary_time()
        self.job_number = 9000

    def _make_client(self, name: str) -> Client:
        return Client.objects.create(
            name=name,
            xero_last_modified=timezone.now(),
        )

    def _make_job(
        self,
        *,
        name: str,
        client_name: str,
        status: str = "in_progress",
        contact_name: str | None = None,
    ):
        client = self._make_client(client_name)
        contact = None
        if contact_name:
            contact = ClientContact.objects.create(client=client, name=contact_name)

        self.job_number += 1
        return Job.objects.create(
            staff=self.test_staff,
            name=name,
            client=client,
            contact=contact,
            status=status,
            job_number=self.job_number,
            created_by=self.test_staff,
            default_xero_pay_item=self.xero_pay_item,
        )

    def test_perform_advanced_search_matches_single_token_job_name_substring(self):
        target = self._make_job(
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            client_name="Weaver, Decker and Schultz",
        )
        self._make_job(
            name="Aluminium handrail",
            client_name="Other Client",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "kick"}))

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_matches_numeric_substring(self):
        target = self._make_job(
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            client_name="Weaver, Decker and Schultz",
        )
        self._make_job(
            name="5MM folded flashing 1200MM",
            client_name="Other Client",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "910"}))

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_matches_client_tokens_in_any_order(self):
        target = self._make_job(
            name="Kick plates",
            client_name="Weaver, Decker and Schultz",
        )
        self._make_job(
            name="Other work",
            client_name="Schultz Fabrication Only",
        )

        jobs = list(
            KanbanService.perform_advanced_search(
                {"universal_search": "schultz weaver"}
            )
        )

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_matches_contact_name_substring(self):
        target = self._make_job(
            name="Kick plates",
            client_name="Weaver, Decker and Schultz",
            contact_name="Molly Wainwright",
        )
        self._make_job(
            name="Other work",
            client_name="Other Client",
            contact_name="Alice Brown",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "wain"}))

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_get_jobs_by_kanban_column_matches_client_tokens_in_any_order(self):
        target = self._make_job(
            name="Kick plates",
            client_name="Weaver, Decker and Schultz",
            status="in_progress",
        )
        self._make_job(
            name="Draft work",
            client_name="Weaver Draft",
            status="draft",
        )

        result = KanbanService.get_jobs_by_kanban_column(
            "in_progress", search_term="schultz weaver"
        )

        self.assertTrue(result["success"])
        self.assertEqual([job["id"] for job in result["jobs"]], [str(target.id)])
