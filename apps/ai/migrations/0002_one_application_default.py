"""Require an explicit choice when legacy vendor defaults disagree."""

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def clear_ambiguous_defaults(apps: Apps, _editor: BaseDatabaseSchemaEditor) -> None:
    """Preserve credentials and models; never guess which vendor the operator intended."""
    providers = apps.get_model("ai", "AIProvider")
    if providers.objects.filter(default=True).count() > 1:
        providers.objects.filter(default=True).update(default=False)


class Migration(migrations.Migration):
    dependencies = [("ai", "0001_initial")]
    operations = [
        migrations.RunPython(clear_ambiguous_defaults, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="aiprovider",
            constraint=models.UniqueConstraint(
                fields=["default"],
                condition=models.Q(default=True),
                name="ai_one_application_default",
            ),
        ),
    ]
