from django.db import migrations, models


def populate_default_quote_terms(apps, schema_editor):
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")
    for defaults in CompanyDefaults.objects.exclude(company_url__isnull=True):
        if defaults.xero_quote_terms is not None:
            continue
        if not defaults.company_url:
            continue
        company_url = defaults.company_url.rstrip("/")
        defaults.xero_quote_terms = (
            "Terms of trade can be found on our website: "
            f"{company_url}/terms-of-trade"
        )
        defaults.save(update_fields=["xero_quote_terms"])


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0013_notebooklmlink"),
    ]

    operations = [
        migrations.AlterField(
            model_name="companydefaults",
            name="xero_sales_branding_theme_id",
            field=models.UUIDField(
                blank=True,
                help_text=(
                    "Controls the layout and presentation of every quote and sales "
                    "invoice created in Xero. It is configured during Xero setup and "
                    "required before sales documents can be created."
                ),
                null=True,
                verbose_name="Xero sales branding theme",
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="xero_quote_terms",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Terms sent on every quote created by DocketWorks. Initially "
                    "derived from the company website's /terms-of-trade page. Copy "
                    "the same text to Xero's Terms (Quotes) setting so quotes created "
                    "directly in Xero during an outage use the same terms."
                ),
                max_length=4000,
                null=True,
                verbose_name="Xero quote terms",
            ),
        ),
        migrations.RunPython(populate_default_quote_terms, migrations.RunPython.noop),
    ]
