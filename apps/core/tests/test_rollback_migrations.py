"""The rollback_migrations command: target parsing, plan refusals, apply behaviour.

The migration graph is faked at the MigrationExecutor seam so each test states
its plan directly; running against the real graph would make every test depend
on whichever migrations happen to exist today.
"""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands import rollback_migrations as rollback_module
from apps.core.management.commands.rollback_migrations import (
    MigrationTarget,
    read_migration_targets,
)


class FakeOperation:
    """A migration operation that only knows whether it can be reversed."""

    def __init__(self, *, reversible: bool) -> None:
        self.reversible = reversible


class FakeMigration:
    """The three attributes of a Migration the command reads."""

    def __init__(self, app_label: str, name: str, *, reversible: bool = True) -> None:
        self.app_label = app_label
        self.name = name
        self.operations = [FakeOperation(reversible=reversible)]


class FakeLoader:
    """A loader exposing only the migrated-apps set the command consults."""

    def __init__(self, migrated_apps: set[str]) -> None:
        self.migrated_apps = migrated_apps


class FakeExecutor:
    """Records the targets it was asked to plan and to migrate."""

    def __init__(
        self,
        migrated_apps: set[str],
        plan: list[tuple[FakeMigration, bool]],
    ) -> None:
        self.loader = FakeLoader(migrated_apps)
        self._plan = plan
        self.plan_requests: list[list[MigrationTarget]] = []
        self.migrate_calls: list[list[MigrationTarget]] = []

    def migration_plan(self, targets: list[MigrationTarget]) -> list[tuple[FakeMigration, bool]]:
        self.plan_requests.append(list(targets))
        return self._plan

    def migrate(self, targets: list[MigrationTarget]) -> None:
        self.migrate_calls.append(list(targets))


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeExecutor) -> None:
    def _executor_factory(_connection: object) -> FakeExecutor:
        return fake

    monkeypatch.setattr(rollback_module, "MigrationExecutor", _executor_factory)


def _write_targets(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "targets.tsv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(*args: str) -> str:
    out = StringIO()
    call_command("rollback_migrations", *args, stdout=out)
    return out.getvalue()


class TestReadMigrationTargets:
    """The tab-separated leaf list rollback.sh captures from the old release."""

    def test_parses_targets_and_skips_blank_lines(self, tmp_path: Path) -> None:
        path = _write_targets(tmp_path, "job\t0004_alpha", "", "core\t0002_beta")

        assert read_migration_targets(path) == [("job", "0004_alpha"), ("core", "0002_beta")]

    def test_malformed_line_is_refused_with_its_location(self, tmp_path: Path) -> None:
        path = _write_targets(tmp_path, "job\t0004_alpha", "core 0002_beta")

        with pytest.raises(CommandError, match=rf"{path}:2"):
            read_migration_targets(path)

    def test_line_with_empty_field_is_refused(self, tmp_path: Path) -> None:
        path = _write_targets(tmp_path, "job\t")

        with pytest.raises(CommandError, match="Invalid migration target"):
            read_migration_targets(path)

    def test_empty_file_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "targets.tsv"
        path.write_text("\n\n", encoding="utf-8")

        with pytest.raises(CommandError, match="No migration targets found"):
            read_migration_targets(path)


class TestPlanRefusals:
    """A rollback must only ever unapply reversible migrations."""

    def test_forward_migrations_are_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = FakeExecutor(
            migrated_apps={"job"},
            plan=[(FakeMigration("job", "0005_gamma"), False)],
        )
        _install(monkeypatch, fake)
        path = _write_targets(tmp_path, "job\t0005_gamma")

        with pytest.raises(CommandError, match=r"forward migrations: job\.0005_gamma"):
            _run("--targets-file", str(path))
        assert fake.migrate_calls == []

    def test_irreversible_migrations_are_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = FakeExecutor(
            migrated_apps={"job"},
            plan=[(FakeMigration("job", "0005_gamma", reversible=False), True)],
        )
        _install(monkeypatch, fake)
        path = _write_targets(tmp_path, "job\t0004_alpha")

        with pytest.raises(
            CommandError, match=r"Irreversible migrations in rollback plan: job\.0005_gamma"
        ):
            _run("--targets-file", str(path), "--apply")
        assert fake.migrate_calls == []


class TestPlanAndApply:
    """Plan by default; migrate only on --apply."""

    def test_untargeted_apps_are_unmigrated_to_zero_in_sorted_order(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = FakeExecutor(migrated_apps={"job", "crm", "accounts"}, plan=[])
        _install(monkeypatch, fake)
        path = _write_targets(tmp_path, "job\t0004_alpha")

        _run("--targets-file", str(path))

        assert fake.plan_requests == [[("job", "0004_alpha"), ("accounts", None), ("crm", None)]]

    def test_empty_plan_reports_and_does_not_migrate(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = FakeExecutor(migrated_apps={"job"}, plan=[])
        _install(monkeypatch, fake)
        path = _write_targets(tmp_path, "job\t0004_alpha")

        output = _run("--targets-file", str(path), "--apply")

        assert "No migration changes required." in output
        assert fake.migrate_calls == []

    def test_default_run_prints_plan_without_migrating(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = FakeExecutor(
            migrated_apps={"job"},
            plan=[
                (FakeMigration("job", "0006_delta"), True),
                (FakeMigration("job", "0005_gamma"), True),
            ],
        )
        _install(monkeypatch, fake)
        path = _write_targets(tmp_path, "job\t0004_alpha")

        output = _run("--targets-file", str(path))

        assert "UNAPPLY job.0006_delta" in output
        assert "UNAPPLY job.0005_gamma" in output
        assert "Plan only; pass --apply to execute." in output
        assert fake.migrate_calls == []

    def test_apply_migrates_to_the_resolved_targets(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = FakeExecutor(
            migrated_apps={"job", "crm"},
            plan=[(FakeMigration("job", "0005_gamma"), True)],
        )
        _install(monkeypatch, fake)
        path = _write_targets(tmp_path, "job\t0004_alpha")

        output = _run("--targets-file", str(path), "--apply")

        assert fake.migrate_calls == [[("job", "0004_alpha"), ("crm", None)]]
        assert "Reverse migrations complete." in output

    def test_missing_targets_file_option_is_refused(self) -> None:
        with pytest.raises(CommandError, match="targets-file"):
            _run()
