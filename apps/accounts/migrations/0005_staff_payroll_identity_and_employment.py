"""Separate Staff account identity from Xero payroll identity and employment."""

from typing import Any

import django.utils.timezone
from django.db import migrations, models


def copy_employment_start_dates(apps: Any, schema_editor: Any) -> None:
    """Preserve the date that the previous active-staff queries treated as employment."""
    del schema_editor
    for model_name in ("Staff", "HistoricalStaff"):
        model = apps.get_model("accounts", model_name)
        rows = list(model.objects.all())
        for row in rows:
            row.employment_start_date = row.date_joined.date()
        model.objects.bulk_update(rows, ["employment_start_date"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_historicalstaff_xero_tenant_id_staff_xero_tenant_id_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("job", "0004_costline_managed_by_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="historicalstaff",
            old_name="email",
            new_name="office_email",
        ),
        migrations.RenameField(
            model_name="staff",
            old_name="email",
            new_name="office_email",
        ),
        migrations.AddField(
            model_name="historicalstaff",
            name="employment_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="staff",
            name="employment_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="historicalstaff",
            name="pay_basis",
            field=models.CharField(
                blank=True,
                choices=[("hourly", "Hourly"), ("salary", "Salary")],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="staff",
            name="pay_basis",
            field=models.CharField(
                blank=True,
                choices=[("hourly", "Hourly"), ("salary", "Salary")],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalstaff",
            name="payroll_email",
            field=models.EmailField(blank=True, db_index=True, max_length=254, null=True),
        ),
        migrations.AddField(
            model_name="staff",
            name="payroll_email",
            field=models.EmailField(blank=True, max_length=254, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="historicalstaff",
            name="xero_last_modified",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="staff",
            name="xero_last_modified",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(copy_employment_start_dates, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="historicalstaff",
            name="employment_start_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
        migrations.AlterField(
            model_name="staff",
            name="employment_start_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
        migrations.RemoveField(model_name="historicalstaff", name="date_joined"),
        migrations.RemoveField(model_name="staff", name="date_joined"),
        migrations.AddConstraint(
            model_name="staff",
            constraint=models.CheckConstraint(
                condition=~models.Q(payroll_email=""),
                name="staff_payroll_email_not_blank",
            ),
        ),
        migrations.AddConstraint(
            model_name="staff",
            constraint=models.CheckConstraint(
                condition=~models.Q(pay_basis=""),
                name="staff_pay_basis_not_blank",
            ),
        ),
    ]
