from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError, OutputWrapper
from django.test import SimpleTestCase

from apps.workflow.management.commands.rollback_migrations import (
    Command,
    read_migration_targets,
)


class ReadMigrationTargetsTests(SimpleTestCase):
    def test_reads_release_leaf_nodes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "targets.tsv"
            path.write_text(
                "company\t0007_people\njob\t0012_events\n", encoding="utf-8"
            )

            self.assertEqual(
                read_migration_targets(path),
                [("company", "0007_people"), ("job", "0012_events")],
            )

    def test_rejects_malformed_target(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "targets.tsv"
            path.write_text("company-only\n", encoding="utf-8")

            with self.assertRaises(CommandError):
                read_migration_targets(path)


class RollbackMigrationsCommandTests(SimpleTestCase):
    def _targets_file(self, temp_dir: str) -> Path:
        path = Path(temp_dir) / "targets.tsv"
        path.write_text("company\t0007_people\n", encoding="utf-8")
        return path

    @patch("apps.workflow.management.commands.rollback_migrations.MigrationExecutor")
    def test_empty_plan_reports_code_only_rollback(
        self, executor_class: MagicMock
    ) -> None:
        executor = executor_class.return_value
        executor.loader.migrated_apps = {"company"}
        executor.migration_plan.return_value = []
        output = StringIO()
        command = Command()
        command.stdout = OutputWrapper(output)

        with TemporaryDirectory() as temp_dir:
            command.handle(targets_file=str(self._targets_file(temp_dir)), apply=False)

        self.assertEqual(output.getvalue(), "No migration changes required.\n")
        executor.migrate.assert_not_called()

    @patch("apps.workflow.management.commands.rollback_migrations.MigrationExecutor")
    def test_apply_executes_reversible_reverse_plan(
        self, executor_class: MagicMock
    ) -> None:
        executor = executor_class.return_value
        executor.loader.migrated_apps = {"company"}
        migration = MagicMock()
        migration.app_label = "company"
        migration.name = "0008_new_field"
        migration.operations = [MagicMock(reversible=True)]
        executor.migration_plan.return_value = [(migration, True)]
        output = StringIO()
        command = Command()
        command.stdout = OutputWrapper(output)

        with TemporaryDirectory() as temp_dir:
            command.handle(targets_file=str(self._targets_file(temp_dir)), apply=True)

        self.assertIn("UNAPPLY company.0008_new_field", output.getvalue())
        executor.migrate.assert_called_once_with([("company", "0007_people")])

    @patch("apps.workflow.management.commands.rollback_migrations.MigrationExecutor")
    def test_irreversible_reverse_plan_is_reported(
        self, executor_class: MagicMock
    ) -> None:
        executor = executor_class.return_value
        executor.loader.migrated_apps = {"company"}
        migration = MagicMock()
        migration.app_label = "company"
        migration.name = "0008_irreversible"
        migration.operations = [MagicMock(reversible=False)]
        executor.migration_plan.return_value = [(migration, True)]

        with (
            TemporaryDirectory() as temp_dir,
            self.assertRaisesMessage(
                CommandError, "Irreversible migrations in rollback plan"
            ),
        ):
            Command().handle(
                targets_file=str(self._targets_file(temp_dir)), apply=False
            )
