"""Resolve legacy per-vendor defaults without losing provider configuration."""

import pytest
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader

from apps.ai.models import AIProvider

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("defaults", [0, 1, 2])
def test_default_migration_preserves_credentials_and_clears_only_ambiguity(defaults: int) -> None:
    """Execute the historical data migration against zero, one and multiple defaults."""
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[("ai", "0002_one_application_default")]
    state = loader.project_state([("ai", "0001_initial")])
    historical = state.apps.get_model("ai", "AIProvider")
    constraint = next(op for op in migration.operations if isinstance(op, migrations.AddConstraint))
    transform = next(op for op in migration.operations if isinstance(op, migrations.RunPython))
    with connection.schema_editor() as editor:
        editor.remove_constraint(AIProvider, constraint.constraint)
        for index in range(2):
            historical.objects.create(
                name=f"Provider {index}",
                provider_type="OpenAI",
                api_key=f"key-{index}",
                model_name=f"model-{index}",
                default=index < defaults,
            )
        transform.code(state.apps, editor)
        editor.add_constraint(AIProvider, constraint.constraint)
    assert AIProvider.objects.count() == 2
    assert list(AIProvider.objects.order_by("name").values_list("api_key", "model_name")) == [
        ("key-0", "model-0"),
        ("key-1", "model-1"),
    ]
    assert AIProvider.objects.filter(default=True).count() == (1 if defaults == 1 else 0)
