import json
import uuid
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.models import Invoice, Quote
from apps.client.models import Client, ClientContact
from apps.job.models import Job
from apps.job.services.kanban_service import KanbanService
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


class KanbanSearchTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.xero_pay_item = XeroPayItem.get_ordinary_time()
        self.shop_client = self._make_client("Demo Company Shop")
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
        order_number: str | None = None,
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
            order_number=order_number,
        )

    def _set_job_number(self, job: Job, job_number: int) -> Job:
        Job.objects.filter(pk=job.pk).untracked_update(job_number=job_number)
        job.refresh_from_db()
        return job

    def _make_invoice(self, job: Job, *, number: str) -> Invoice:
        return Invoice.objects.create(
            xero_id=uuid.uuid4(),
            number=number,
            client=job.client,
            job=job,
            date=date.today(),
            total_excl_tax=Decimal("100.00"),
            tax=Decimal("15.00"),
            total_incl_tax=Decimal("115.00"),
            amount_due=Decimal("115.00"),
            xero_last_modified=timezone.now(),
            raw_json={},
        )

    def _make_quote(self, job: Job, *, number: str) -> Quote:
        return Quote.objects.create(
            xero_id=uuid.uuid4(),
            number=number,
            client=job.client,
            job=job,
            date=date.today(),
            total_excl_tax=Decimal("100.00"),
            total_incl_tax=Decimal("115.00"),
            xero_last_modified=timezone.now(),
            raw_json={},
        )

    def test_perform_advanced_search_matches_single_token_job_name_substring(self):
        """Catches quick search no longer finding job-name substrings."""
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

    def test_perform_advanced_search_preloads_serialize_job_relations(self):
        """
        Catches search results that would lazy-load relations during API serialization.
        """
        target = self._make_job(
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            client_name="Weaver, Decker and Schultz",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "kick"}))

        self.assertEqual([job.id for job in jobs], [target.id])
        with CaptureQueriesContext(connection) as captured:
            KanbanService.serialize_job_for_api(
                jobs[0], shop_client_id=self.shop_client.id
            )

        relation_queries = [
            query["sql"]
            for query in captured
            if "job_costset" in query["sql"] or "accounts_staff" in query["sql"]
        ]
        self.assertEqual(relation_queries, [])

    def test_perform_advanced_search_preloads_quote_for_ranking(self):
        """Catches quote ranking that re-queries quotes per candidate job."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
        )
        other = self._make_job(
            name="Cool Store",
            client_name="Cool Stores Ltd",
        )
        self._make_quote(target, number="QU-56005")
        self._make_quote(other, number="QU-99999")

        with CaptureQueriesContext(connection) as captured:
            jobs = list(
                KanbanService.perform_advanced_search({"universal_search": "cool"})
            )

        self.assertEqual({job.id for job in jobs}, {target.id, other.id})
        direct_quote_queries = [
            query["sql"]
            for query in captured
            if 'FROM "accounting_quote"' in query["sql"]
        ]
        self.assertEqual(direct_quote_queries, [])

    def test_perform_advanced_search_matches_quote_number(self):
        """Catches quote-number search no longer finding the owning job."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
        )
        other = self._make_job(
            name="Other work",
            client_name="Other Client",
        )
        self._make_quote(target, number="QU-56005")
        self._make_quote(other, number="QU-99999")

        jobs = list(
            KanbanService.perform_advanced_search({"universal_search": "56005"})
        )

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_matches_numeric_substring(self):
        """Catches numeric quick search no longer matching job descriptions."""
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

    def test_numeric_query_prefers_job_number_over_long_description_substring(self):
        """Catches job-number matches being buried under description substrings."""
        target = self._set_job_number(
            self._make_job(
                name="Workshop Closed due to new roof",
                client_name="Weaver, Decker and Schultz",
            ),
            96977,
        )
        description_match = self._make_job(
            name="Auckland airport - bag drop",
            client_name="Other Client",
        )
        description_match.description = "quote for bag drop components\n2-3977"
        description_match.save(staff=self.test_staff, update_fields=["description"])
        for index in range(100):
            noisy_job = self._make_job(
                name=f"Noise job {index}",
                client_name=f"Noise Client {index}",
            )
            self._set_job_number(noisy_job, 70000 + index)

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "977"}))

        self.assertEqual(jobs[0].id, target.id)
        self.assertIn(description_match.id, [job.id for job in jobs])

    def test_get_jobs_by_kanban_column_exact_job_number_suppresses_distant_noise(self):
        """Catches exact job-number filtering returning nearby numeric noise."""
        target = self._set_job_number(
            self._make_job(
                name="Best matching job",
                client_name="Weaver, Decker and Schultz",
                status="in_progress",
            ),
            78941,
        )
        self._set_job_number(
            self._make_job(
                name="Adjacent but weaker job",
                client_name="Other Client",
                status="in_progress",
            ),
            78940,
        )
        for index in range(100):
            noisy_job = self._make_job(
                name=f"Noise job {index}",
                client_name=f"Noise Client {index}",
                status="in_progress",
            )
            self._set_job_number(noisy_job, 70000 + index)

        result = KanbanService.get_jobs_by_kanban_column(
            "in_progress", max_jobs=200, search_term="78941"
        )

        self.assertTrue(result["success"])
        self.assertEqual([job["id"] for job in result["jobs"]], [str(target.id)])

    def test_perform_advanced_search_keeps_plausible_short_job_number_match(
        self,
    ):
        """Catches short job-number suffix searches being over-pruned."""
        near_match = self._set_job_number(
            self._make_job(
                name="Best approximate job",
                client_name="Other Client",
            ),
            96977,
        )
        self._make_job(
            name="Auckland airport - bag drop",
            client_name="Another Client",
            contact_name="Alice Brown",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "977"}))

        self.assertIn(near_match.id, [job.id for job in jobs])

    def test_numeric_query_prefers_job_number_suffix_over_middle_substring(self):
        """Catches suffix job-number matches losing to less useful middle matches."""
        suffix_match = self._set_job_number(
            self._make_job(
                name="Suffix match",
                client_name="Other Client",
            ),
            96977,
        )
        middle_match = self._set_job_number(
            self._make_job(
                name="Middle match",
                client_name="Other Client",
            ),
            97701,
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "977"}))

        self.assertEqual(jobs[0].id, suffix_match.id)
        suffix_score = getattr(
            next(j for j in jobs if j.id == suffix_match.id), "search_score", 0
        )
        middle_score = getattr(
            (next((j for j in jobs if j.id == middle_match.id), None)),
            "search_score",
            0,
        )
        self.assertLess(middle_score, suffix_score)

    def test_perform_advanced_search_keeps_multiple_close_text_matches(self):
        """Catches text search collapsing distinct plausible job matches."""
        target_one = self._make_job(
            name="Kick plates",
            client_name="Weaver, Decker and Schultz",
        )
        target_two = self._make_job(
            name="Kick rails",
            client_name="Other Client",
        )
        self._make_job(
            name="Aluminium handrail",
            client_name="Distant Client",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "kick"}))

        self.assertEqual({job.id for job in jobs}, {target_one.id, target_two.id})

    def test_perform_advanced_search_matches_client_tokens_in_any_order(self):
        """Catches client-name token search becoming order-sensitive."""
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
        """Catches contact-name search no longer matching partial names."""
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
        """Catches kanban column search ignoring unordered client-name tokens."""
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

    def test_perform_advanced_search_returns_empty_when_query_not_present(self):
        """Catches unrelated jobs being returned for absent search terms."""
        self._make_job(
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            client_name="Weaver, Decker and Schultz",
        )

        jobs = list(
            KanbanService.perform_advanced_search({"universal_search": "nonsensezzz"})
        )

        self.assertEqual(jobs, [])

    def test_perform_advanced_search_returns_empty_for_only_weak_trigram_matches(self):
        """Catches weak fuzzy matches leaking below the display threshold."""
        weak_match = self._make_job(
            name="5x swaged ends",
            client_name="Other Client",
        )
        setattr(
            weak_match,
            "trigram_score",
            (KanbanService.SEARCH_SCORE_MIN_DISPLAY - 1)
            / KanbanService.SEARCH_SCORE_TRIGRAM_MULTIPLIER,
        )

        ranked_jobs = KanbanService._rank_kanban_search_candidates(
            [weak_match], "weavr"
        )

        self.assertEqual(ranked_jobs, [])

    def test_perform_advanced_search_recovers_typo_tolerance(self):
        """Catches typo tolerance no longer recovering misspelled client searches."""
        target = self._make_job(
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            client_name="Weaver, Decker and Schultz",
        )

        jobs = list(
            KanbanService.perform_advanced_search(
                {"universal_search": "schultzz weavr"}
            )
        )

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_get_jobs_by_kanban_column_recovers_typo_tolerance(self):
        """Catches kanban column search losing typo tolerance."""
        target = self._make_job(
            name="Kick plates",
            client_name="Weaver, Decker and Schultz",
            status="in_progress",
        )

        result = KanbanService.get_jobs_by_kanban_column(
            "in_progress", search_term="schultzz weavr"
        )

        self.assertTrue(result["success"])
        self.assertEqual([job["id"] for job in result["jobs"]], [str(target.id)])

    def test_perform_advanced_search_does_not_fuzzy_match_invoice_numbers(self):
        """Catches invoice searches fuzzily matching the wrong invoice."""
        target = self._make_job(
            name="Kick plates",
            client_name="Weaver, Decker and Schultz",
        )
        other = self._make_job(
            name="Other work",
            client_name="Other Client",
        )
        self._make_invoice(target, number="INV-15152")
        self._make_invoice(other, number="INV-15153")

        jobs = list(
            KanbanService.perform_advanced_search({"universal_search": "INV-15151"})
        )

        self.assertEqual(jobs, [])

    def test_perform_advanced_search_matches_invoice_number_exactly_via_filter(self):
        """Catches the invoice filter failing to match a full invoice number."""
        target = self._make_job(
            name="Kick plates",
            client_name="Weaver, Decker and Schultz",
        )
        other = self._make_job(
            name="Other work",
            client_name="Other Client",
        )
        self._make_invoice(target, number="INV-15151")
        self._make_invoice(other, number="INV-15152")

        jobs = list(
            KanbanService.perform_advanced_search({"xero_invoice_params": "INV-15151"})
        )

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_matches_bare_invoice_number(self):
        """Catches the invoice filter failing to match bare invoice digits."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
        )
        other = self._make_job(
            name="Other work",
            client_name="Other Client",
        )
        self._make_invoice(target, number="INV-56005")
        self._make_invoice(other, number="INV-12345")

        jobs = list(
            KanbanService.perform_advanced_search({"xero_invoice_params": "56005"})
        )

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_unrecognised_invoice_returns_empty(self):
        """Catches invalid invoice filters returning unrelated jobs."""
        target = self._make_job(
            name="Kick plates",
            client_name="Weaver, Decker and Schultz",
        )
        self._make_invoice(target, number="INV-15151")

        jobs = list(
            KanbanService.perform_advanced_search({"xero_invoice_params": "garbage!!!"})
        )

        self.assertEqual(jobs, [])

    def test_perform_advanced_search_quick_search_matches_order_number(self):
        """Catches universal search no longer matching order numbers."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
            order_number="8057",
        )
        self._make_job(
            name="Other work",
            client_name="Other Client",
            order_number="99999",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "8057"}))

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_order_number_filter(self):
        """Catches the explicit order-number filter returning the wrong job."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
            order_number="8057",
        )
        self._make_job(
            name="Other work",
            client_name="Other Client",
            order_number="99999",
        )

        jobs = list(KanbanService.perform_advanced_search({"order_number": "8057"}))

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_quick_search_matches_invoice_number(self):
        """Catches universal search no longer matching full invoice numbers."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
        )
        other = self._make_job(
            name="Other work",
            client_name="Other Client",
        )
        self._make_invoice(target, number="INV-56005")
        self._make_invoice(other, number="INV-99999")

        jobs = list(
            KanbanService.perform_advanced_search({"universal_search": "INV-56005"})
        )

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_quick_search_matches_bare_invoice_number(self):
        """Catches universal search no longer matching bare invoice digits."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
        )
        other = self._make_job(
            name="Other work",
            client_name="Other Client",
        )
        self._make_invoice(target, number="INV-56005")
        self._make_invoice(other, number="INV-99999")

        jobs = list(
            KanbanService.perform_advanced_search({"universal_search": "56005"})
        )

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_invoice_match_returns_job_once_with_multiple_invoices(
        self,
    ):
        """Catches invoice joins duplicating jobs with multiple matching invoices."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
        )
        self._make_invoice(target, number="INV-56005")
        self._make_invoice(target, number="INV-56005-REV")

        jobs = list(
            KanbanService.perform_advanced_search({"universal_search": "56005"})
        )

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_text_match_returns_job_once_with_multiple_invoices(
        self,
    ):
        """Catches text search duplicating jobs that have multiple invoices."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
        )
        self._make_invoice(target, number="INV-56005")
        self._make_invoice(target, number="INV-99999")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "Cool"}))

        self.assertEqual([job.id for job in jobs], [target.id])

    def test_perform_advanced_search_invoice_reason_present(self):
        """Catches invoice matches losing their explainable search reason."""
        target = self._make_job(
            name="Cool Awnings",
            client_name="Cool Awnings Ltd",
        )
        self._make_invoice(target, number="INV-56005")

        jobs = list(
            KanbanService.perform_advanced_search({"universal_search": "56005"})
        )

        reasons = getattr(jobs[0], "search_reasons", {})
        token_reasons = reasons.get("tokens", [])
        reason_names = [t.get("reason") for t in token_reasons]
        self.assertIn("invoice_contains", reason_names)

    def test_kanban_search_logging_records_ranked_results_and_reasons(self):
        """Catches search logs losing ranked result and scoring diagnostics."""
        target = self._set_job_number(
            self._make_job(
                name="Workshop Closed due to new roof",
                client_name="Weaver, Decker and Schultz",
            ),
            96977,
        )
        jobs = list(KanbanService.perform_advanced_search({"universal_search": "977"}))
        request = RequestFactory().get("/api/job/jobs/advanced-search/", {"q": "977"})
        request.user = self.test_staff

        with self.assertLogs("kanban_search", level="INFO") as captured:
            KanbanService.log_kanban_search_results(
                request=request,
                source="advanced",
                query="977",
                jobs=jobs,
                filters={"universal_search": "977"},
            )

        payload = json.loads(captured.output[0].partition("kanban_search:")[2])

        self.assertEqual(payload["event"], "kanban_search_results")
        self.assertEqual(payload["query"], "977")
        self.assertEqual(payload["query_string"], "q=977")
        self.assertEqual(payload["user_email"], self.test_staff.email)
        self.assertEqual(payload["result_count"], len(jobs))
        self.assertEqual(payload["results"][0]["rank"], 1)
        self.assertEqual(payload["results"][0]["job_id"], str(target.id))
        self.assertEqual(payload["results"][0]["job_number"], 96977)
        self.assertIsInstance(payload["results"][0]["search_score"], float)
        self.assertGreaterEqual(
            payload["results"][0]["search_score"],
            KanbanService.SEARCH_SCORE_MIN_DISPLAY,
        )

        reasons = payload["results"][0]["search_reasons"]
        self.assertIn("tokens", reasons)
        self.assertGreater(len(reasons["tokens"]), 0)
        first_token = reasons["tokens"][0]
        self.assertEqual(first_token["token"], "977")
        self.assertIn("reason", first_token)
        self.assertIsInstance(first_token["reason"], str)
        self.assertIn("score", first_token)
        self.assertIsInstance(first_token["score"], (int, float))
