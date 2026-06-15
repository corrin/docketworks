from django.db import migrations


class Migration(migrations.Migration):
    """Drop CompanyDefaults.charge_out_rate.

    The per-subtype charge-out rate (LabourSubtype.default_charge_out_rate, with
    the Workshop subtype as the company baseline) is now the single source of
    truth (ADR 0017). The job migration 0104 still reads
    CompanyDefaults.charge_out_rate at apply time, so this removal must run after
    it — declared as a cross-app dependency so a fresh DB replays the chain in
    the correct order (0104 reads the column, then this drops it).
    """

    dependencies = [
        ("workflow", "0235_searchtelemetryevent"),
        ("job", "0104_add_urgent_labour_subtype"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="companydefaults",
            name="charge_out_rate",
        ),
    ]
