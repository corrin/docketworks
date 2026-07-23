from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

DEPRECATED_GEMINI_MODELS = (
    "gemini-2.0-flash-exp",
    "gemini-2.5-flash",
)
GEMINI_FLASH_MODEL = "gemini-flash-latest"


def use_latest_gemini_flash_model(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    AIProvider = apps.get_model("workflow", "AIProvider")
    AIProvider.objects.filter(
        provider_type="Gemini",
        model_name__in=DEPRECATED_GEMINI_MODELS,
    ).update(model_name=GEMINI_FLASH_MODEL)


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0011_companydefaults_xero_sales_branding_theme_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aiprovider",
            name="model_name",
            field=models.CharField(
                blank=True,
                help_text="Model name (e.g., gemini-flash-latest)",
                max_length=100,
            ),
        ),
        migrations.RunPython(
            use_latest_gemini_flash_model,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
