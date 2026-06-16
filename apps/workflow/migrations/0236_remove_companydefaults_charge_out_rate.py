from django.db import migrations


class Migration(migrations.Migration):
    """Drop CompanyDefaults.charge_out_rate.

    The per-subtype charge-out rate (LabourSubtype.default_charge_out_rate, with
    the Workshop subtype as the company baseline) is now the single source of
    truth (ADR 0017). Ordered after the latest job migration so the
    labour-subtype catalogue is in place before the column is dropped.
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
