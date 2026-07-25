from django.db import migrations, models

# Kept as a literal so this migration stays self-contained; the model's copy of
# the same starting text may drift without changing what was written here.
DEFAULT_QUOTE_TERMS = "Terms of trade can be found on our website."


def populate_default_quote_terms(apps, schema_editor):
    """Point rows with a known website at its terms-of-trade page.

    AddField has already given every row DEFAULT_QUOTE_TERMS, so this only
    upgrades the ones where a company URL makes a more specific sentence possible.
    """
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")
    for defaults in CompanyDefaults.objects.exclude(company_url__isnull=True):
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
                default=DEFAULT_QUOTE_TERMS,
                help_text=(
                    "Terms sent on every quote created by DocketWorks. Required — "
                    "Xero does not apply its own Terms (Quotes) default to quotes "
                    "created through the API. Copy the same text to Xero's Terms "
                    "(Quotes) setting so quotes created directly in Xero during an "
                    "outage use the same terms."
                ),
                max_length=4000,
                verbose_name="Xero quote terms",
            ),
        ),
        migrations.RunPython(populate_default_quote_terms, migrations.RunPython.noop),
    ]
