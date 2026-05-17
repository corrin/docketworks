from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0089_backfill_costline_staff_entry_seq"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="costline",
            index=models.Index(
                fields=["staff", "accounting_date", "entry_seq"],
                name="job_costlin_staff_i_2efa8d_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="costline",
            constraint=models.UniqueConstraint(
                condition=Q(
                    kind="time",
                    staff__isnull=False,
                    entry_seq__isnull=False,
                ),
                fields=("staff", "accounting_date", "entry_seq"),
                name="unique_time_entry_staff_day_seq",
            ),
        ),
        migrations.AddConstraint(
            model_name="costline",
            constraint=models.CheckConstraint(
                condition=(
                    Q(staff__isnull=True, entry_seq__isnull=True)
                    | Q(staff__isnull=False, entry_seq__isnull=False)
                ),
                name="costline_staff_entry_seq_pair",
            ),
        ),
    ]
