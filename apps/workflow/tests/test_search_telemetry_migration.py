from typing import ClassVar

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SearchTelemetryTerminologyMigrationTests(TransactionTestCase):
    migrate_from: ClassVar[tuple[tuple[str, str], ...]] = (
        ("workflow", "0007_rename_search_telemetry_client_domain"),
    )
    migrate_to: ClassVar[tuple[tuple[str, str], ...]] = (
        ("workflow", "0009_rename_remaining_crm_telemetry_sources"),
    )

    def setUp(self) -> None:
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        self.old_apps = self.executor.loader.project_state(self.migrate_from).apps

    def tearDown(self) -> None:
        self.executor.loader.build_graph()
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_forward_and_reverse_rename_company_lookup_source(self) -> None:
        SearchTelemetryEvent = self.old_apps.get_model(
            "workflow", "SearchTelemetryEvent"
        )
        event = SearchTelemetryEvent.objects.create(
            event_type="click",
            domain="company",
            source="client_lookup",
            query="Acme",
            normalized_query="acme",
        )
        companies_table = SearchTelemetryEvent.objects.create(
            event_type="click",
            domain="company",
            source="crm_clients_table",
            query="Beta",
            normalized_query="beta",
        )
        company_detail = SearchTelemetryEvent.objects.create(
            event_type="click",
            domain="company",
            source="crm_client_detail_phone_numbers",
            query="Gamma",
            normalized_query="gamma",
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        SearchTelemetryEvent = new_apps.get_model("workflow", "SearchTelemetryEvent")

        event = SearchTelemetryEvent.objects.get(pk=event.pk)
        self.assertEqual(event.source, "company_lookup")
        self.assertEqual(
            SearchTelemetryEvent.objects.get(pk=companies_table.pk).source,
            "crm_companies_table",
        )
        self.assertEqual(
            SearchTelemetryEvent.objects.get(pk=company_detail.pk).source,
            "crm_company_detail_phone_numbers",
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_from)
        reversed_apps = self.executor.loader.project_state(self.migrate_from).apps
        SearchTelemetryEvent = reversed_apps.get_model(
            "workflow", "SearchTelemetryEvent"
        )

        event = SearchTelemetryEvent.objects.get(pk=event.pk)
        self.assertEqual(event.source, "client_lookup")
        self.assertEqual(
            SearchTelemetryEvent.objects.get(pk=companies_table.pk).source,
            "crm_clients_table",
        )
        self.assertEqual(
            SearchTelemetryEvent.objects.get(pk=company_detail.pk).source,
            "crm_client_detail_phone_numbers",
        )
