"""Architecture gates must reject real imports and string ORM dependencies."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.apps import apps
from django.db import models
from django.test.utils import isolate_apps

from config.architecture import forbidden_model_relations, model_relations

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_migrated_contexts_obey_orm_ownership() -> None:
    assert forbidden_model_relations(model_relations(apps.get_models())) == []


@pytest.mark.parametrize(
    ("source_context", "target_context", "allowed"),
    [
        ("platform", "legacy", False),
        ("platform", "crm", False),
        ("legacy", "platform", False),
        ("work", "platform", False),
        ("work", "legacy", False),
        ("work", "crm", True),
        ("crm", "work", False),
        ("work", "work", True),
        ("legacy", "legacy", True),
    ],
)
@isolate_apps()
def test_string_foreign_keys_and_many_to_many_obey_context_direction(
    source_context: str, target_context: str, allowed: bool
) -> None:
    class Target(models.Model):
        __module__ = "boundary.target.models"

        class Meta:
            app_label = "boundary"

        def __str__(self) -> str:
            return "boundary target"

    class Source(models.Model):
        __module__ = "boundary.source.models"

        class Meta:
            app_label = "boundary"

        def __str__(self) -> str:
            return "boundary source"

    Source.add_to_class("target", models.ForeignKey("boundary.Target", on_delete=models.PROTECT))
    Source.add_to_class("targets", models.ManyToManyField("boundary.Target"))

    ownership = {
        package: context
        for package, context in (
            ("boundary.source", source_context),
            ("boundary.target", target_context),
        )
        if context != "legacy"
    }
    violations = forbidden_model_relations(model_relations([Source, Target]), ownership)
    if allowed:
        assert violations == []
    else:
        assert violations == [
            "boundary.Source.target -> boundary.Target",
            "boundary.Source.targets -> boundary.Target",
        ]


@pytest.mark.parametrize(
    ("imports", "allowed"),
    [
        ({"apps/platform/integrations/google.py": "import apps.core.models\n"}, False),
        ({"apps/platform/integrations/google.py": "import apps.job\n"}, False),
        (
            {
                "apps/platform/integrations/google.py": (
                    "import apps.platform.integrations.models\n"
                ),
                "apps/platform/integrations/models.py": (
                    "import apps.platform.integrations.google\n"
                ),
            },
            False,
        ),
        ({"apps/platform/integrations/api.py": "import apps.core.auth\n"}, True),
    ],
)
def test_production_import_contracts_reject_inversions_and_cycles(
    tmp_path: Path, imports: dict[str, str], allowed: bool
) -> None:
    # GPT: use the shipped contracts against an importable miniature tree, not
    # a second rule implementation or mutations to the shared working tree.
    for package in (
        "config",
        "apps",
        "apps/core",
        "apps/ai",
        "apps/job",
        "apps/accounts",
        "apps/company",
        "apps/crm",
        "apps/purchasing",
        "apps/quoting",
        "apps/accounting",
        "apps/timesheet",
        "apps/operations",
        "apps/process",
        "apps/xero",
        "apps/search",
        "apps/diagnostics",
        "apps/platform",
        "apps/platform/integrations",
    ):
        directory = tmp_path / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("")
    (tmp_path / "apps/core/models.py").write_text("")
    (tmp_path / "apps/core/auth.py").write_text("import apps.core.models\n")
    # GPT: the one inherited ignore must still match; no new violation is ignored.
    (tmp_path / "apps/job/models").mkdir()
    (tmp_path / "apps/job/models/__init__.py").write_text("")
    (tmp_path / "apps/job/models/job.py").write_text("import apps.xero.models\n")
    (tmp_path / "apps/xero/models.py").write_text("")
    for path, source in imports.items():
        (tmp_path / path).write_text(source)
    (tmp_path / "pyproject.toml").write_text((REPO_ROOT / "pyproject.toml").read_text())
    result = subprocess.run(  # noqa: S603 -- fixed installed checker, isolated test source tree
        [str(Path(sys.executable).with_name("lint-imports")), "--no-cache"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    if allowed:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert "BROKEN" in result.stdout, result.stdout + result.stderr
