"""Make the migrated SDK payload the single conversation representation."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("job", "0006_migrate_quote_chat")]

    operations = [
        migrations.RemoveIndex("jobquotechat", "job_jobquot_job_id_c83a63_idx"),
        migrations.RemoveIndex("jobquotechat", "job_jobquot_message_786ba1_idx"),
        migrations.RemoveField("jobquotechat", "job"),
        migrations.RemoveField("jobquotechat", "role"),
        migrations.RemoveField("jobquotechat", "content"),
        migrations.RemoveField("jobquotechat", "metadata"),
        migrations.AlterField(
            "jobquotechat",
            "thread",
            models.ForeignKey(
                to="job.jobquotechatthread", on_delete=models.CASCADE, related_name="items"
            ),
        ),
        migrations.AlterField("jobquotechat", "payload", models.JSONField()),
        migrations.AlterField("jobquotechat", "timestamp", models.DateTimeField()),
        migrations.AlterField(
            "jobquotechat", "message_id", models.CharField(max_length=100, unique=True)
        ),
        migrations.AlterModelOptions("jobquotechat", {"ordering": ["timestamp", "message_id"]}),
        migrations.AddIndex(
            "jobquotechat",
            models.Index(
                fields=["thread", "timestamp", "message_id"], name="job_chat_item_created_idx"
            ),
        ),
    ]
