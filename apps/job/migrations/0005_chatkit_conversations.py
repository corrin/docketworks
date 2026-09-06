"""Add durable ChatKit storage before migrating the legacy transcript."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("job", "0004_costline_managed_by_and_more")]

    operations = [
        migrations.CreateModel(
            name="JobQuoteChatThread",
            fields=[
                ("id", models.CharField(primary_key=True, max_length=100, serialize=False)),
                ("created_at", models.DateTimeField()),
                ("payload", models.JSONField()),
                (
                    "job",
                    models.ForeignKey(
                        to="job.job", on_delete=models.CASCADE, related_name="quote_chat_threads"
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
                "indexes": [
                    models.Index(
                        fields=["job", "created_at", "id"], name="job_chat_thread_created_idx"
                    )
                ],
            },
        ),
        migrations.AddField(
            "jobquotechat",
            "thread",
            models.ForeignKey(
                to="job.jobquotechatthread",
                null=True,
                on_delete=models.CASCADE,
                related_name="items",
            ),
        ),
        migrations.AddField("jobquotechat", "payload", models.JSONField(null=True)),
    ]
