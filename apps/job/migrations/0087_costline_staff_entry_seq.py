import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("job", "0086_repoint_stale_time_pay_items"),
    ]

    operations = [
        migrations.AddField(
            model_name="costline",
            name="entry_seq",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Sequence number within a staff member's daily actual time entries.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="costline",
            name="staff",
            field=models.ForeignKey(
                blank=True,
                help_text="Staff member for actual time entries.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cost_lines",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
