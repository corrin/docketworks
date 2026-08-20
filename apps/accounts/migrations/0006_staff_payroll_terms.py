import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_staff_payroll_identity_and_employment")]

    operations = [
        migrations.CreateModel(
            name="StaffPayrollTerm",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("effective_from", models.DateField()),
                (
                    "pay_basis",
                    models.CharField(
                        choices=[("hourly", "Hourly"), ("salary", "Salary")], max_length=10
                    ),
                ),
                (
                    "annual_salary",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
                ),
                (
                    "hourly_rate",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                ("working_weeks", models.JSONField(default=list)),
                (
                    "xero_salary_wage_id",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "xero_working_pattern_id",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "staff",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payroll_terms",
                        to="accounts.staff",
                    ),
                ),
            ],
            options={"ordering": ["staff_id", "effective_from"]},
        ),
        migrations.AddConstraint(
            model_name="staffpayrollterm",
            constraint=models.UniqueConstraint(
                fields=("staff", "effective_from"), name="unique_staff_payroll_term_date"
            ),
        ),
    ]
