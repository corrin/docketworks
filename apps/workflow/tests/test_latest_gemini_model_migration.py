from typing import ClassVar

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LatestGeminiModelMigrationTests(TransactionTestCase):
    migrate_from: ClassVar[tuple[tuple[str, str], ...]] = (
        ("workflow", "0011_companydefaults_xero_sales_branding_theme_id"),
    )
    migrate_to: ClassVar[tuple[tuple[str, str], ...]] = (
        ("workflow", "0012_use_latest_gemini_flash_model"),
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

    def test_deprecated_gemini_models_move_to_rolling_alias(self) -> None:
        AIProvider = self.old_apps.get_model("workflow", "AIProvider")
        obsolete_stable = AIProvider.objects.create(
            name="Gemini Stable",
            provider_type="Gemini",
            model_name="gemini-2.5-flash",
        )
        obsolete_preview = AIProvider.objects.create(
            name="Gemini Preview",
            provider_type="Gemini",
            model_name="gemini-2.0-flash-exp",
        )
        explicit_alias = AIProvider.objects.create(
            name="Gemini Pro",
            provider_type="Gemini",
            model_name="gemini-pro-latest",
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        AIProvider = new_apps.get_model("workflow", "AIProvider")

        self.assertEqual(
            AIProvider.objects.get(pk=obsolete_stable.pk).model_name,
            "gemini-flash-latest",
        )
        self.assertEqual(
            AIProvider.objects.get(pk=obsolete_preview.pk).model_name,
            "gemini-flash-latest",
        )
        self.assertEqual(
            AIProvider.objects.get(pk=explicit_alias.pk).model_name,
            "gemini-pro-latest",
        )
