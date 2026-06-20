from django.db import migrations


class Migration(migrations.Migration):
    """Drop CompanyDefaults.charge_out_rate.

    The per-subtype charge-out rate (LabourSubtype.default_charge_out_rate, with
    the Workshop subtype as the company baseline) is now the single source of
    truth (ADR 0017). Depends on job 0103 because the labour-subtype catalogue
    (seeded in job 0093) must exist before the column is dropped; the prerequisite
    is the catalogue, not the later 0104 non-negative-rate constraint.
    """

    dependencies = [
        ("workflow", "0235_searchtelemetryevent"),
        ("job", "0103_add_job_is_urgent"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="companydefaults",
            name="charge_out_rate",
        ),
    ]
