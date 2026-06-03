from django.db import migrations, models

OPTIONAL_URL_FIELDS = (
    "master_quote_template_url",
    "gdrive_quotes_folder_url",
    "company_url",
    "phone_provider_base_url",
)


def blank_optional_urls_to_null(apps, schema_editor):
    company_defaults = apps.get_model("workflow", "CompanyDefaults")
    for field_name in OPTIONAL_URL_FIELDS:
        company_defaults.objects.filter(**{field_name: ""}).update(
            **{field_name: None}
        )


def null_optional_urls_to_blank(apps, schema_editor):
    company_defaults = apps.get_model("workflow", "CompanyDefaults")
    for field_name in OPTIONAL_URL_FIELDS:
        company_defaults.objects.filter(**{field_name: None}).update(
            **{field_name: ""}
        )


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0233_companydefaults_job_delta_soft_fail_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="companydefaults",
            name="phone_provider_base_url",
            field=models.URLField(
                blank=True,
                default=None,
                help_text="Base URL for the configured phone provider portal.",
                null=True,
            ),
        ),
        migrations.RunPython(
            blank_optional_urls_to_null,
            reverse_code=null_optional_urls_to_blank,
        ),
    ]
