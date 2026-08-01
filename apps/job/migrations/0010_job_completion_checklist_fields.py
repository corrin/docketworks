from django.db import migrations, models


class Migration(migrations.Migration):
    """Front-desk completion checklist as Job fields.

    ``collected`` is renamed rather than replaced: it meant the same thing and was
    never writable (no serializer, endpoint, admin or UI ever set it), so every
    row holds the default and the rename carries no stale data forward.
    """

    dependencies = [
        ("job", "0009_text_unset_constraints"),
    ]

    operations = [
        migrations.RenameField(
            model_name="job",
            old_name="collected",
            new_name="released",
        ),
        migrations.AlterField(
            model_name="job",
            name="released",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "The job has left our possession, by collection, delivery or "
                    "on-site install."
                ),
            ),
        ),
        migrations.AddField(
            model_name="job",
            name="foreman_signed_off",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="job",
            name="timesheets_collected",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="job",
            name="materials_checked",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="job",
            name="customer_called",
            field=models.BooleanField(default=False),
        ),
    ]
