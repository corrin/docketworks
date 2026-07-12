from typing import ClassVar

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SearchTelemetryTerminologyMigrationTests(TransactionTestCase):
    migrate_from: ClassVar[tuple[tuple[str, str], ...]] = (
        ("workflow", "0007_rename_search_telemetry_client_domain"),
    )
    migrate_to: ClassVar[tuple[tuple[str, str], ...]] = (
        ("workflow", "0008_rename_search_telemetry_company_lookup_source"),
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

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        SearchTelemetryEvent = new_apps.get_model("workflow", "SearchTelemetryEvent")

        event = SearchTelemetryEvent.objects.get(pk=event.pk)
        self.assertEqual(event.source, "company_lookup")

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_from)
        reversed_apps = self.executor.loader.project_state(self.migrate_from).apps
        SearchTelemetryEvent = reversed_apps.get_model(
            "workflow", "SearchTelemetryEvent"
        )

        event = SearchTelemetryEvent.objects.get(pk=event.pk)
        self.assertEqual(event.source, "client_lookup")
