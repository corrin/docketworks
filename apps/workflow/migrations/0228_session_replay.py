import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0227_delete_xero_journal"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SessionReplayRecording",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("initial_path", models.CharField(max_length=500)),
                ("latest_path", models.CharField(max_length=500)),
                ("job_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("user_agent", models.TextField(blank=True)),
                ("viewport_width", models.PositiveIntegerField(blank=True, null=True)),
                ("viewport_height", models.PositiveIntegerField(blank=True, null=True)),
                ("event_count", models.PositiveIntegerField(default=0)),
                ("compressed_bytes", models.PositiveIntegerField(default=0)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="session_replay_recordings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
        migrations.CreateModel(
            name="SessionReplayChunk",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("sequence", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("first_event_timestamp_ms", models.BigIntegerField()),
                ("last_event_timestamp_ms", models.BigIntegerField()),
                ("event_count", models.PositiveIntegerField()),
                ("compressed_bytes", models.PositiveIntegerField()),
                ("events_gzip", models.BinaryField()),
                ("path", models.CharField(max_length=500)),
                ("job_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("viewport_width", models.PositiveIntegerField(blank=True, null=True)),
                ("viewport_height", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "recording",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="workflow.sessionreplayrecording",
                    ),
                ),
            ],
            options={
                "ordering": ["recording_id", "sequence"],
            },
        ),
        migrations.AddField(
            model_name="apperror",
            name="session_replay",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="app_errors",
                to="workflow.sessionreplayrecording",
            ),
        ),
        migrations.AddIndex(
            model_name="sessionreplayrecording",
            index=models.Index(
                fields=["user", "-started_at"], name="workflow_se_user_id_04e004_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="sessionreplayrecording",
            index=models.Index(fields=["started_at"], name="workflow_se_started_b2d73c_idx"),
        ),
        migrations.AddIndex(
            model_name="sessionreplayrecording",
            index=models.Index(
                fields=["job_id", "-started_at"], name="workflow_se_job_id_c58f78_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="sessionreplaychunk",
            index=models.Index(
                fields=["recording", "sequence"], name="workflow_se_recordi_6fd6ad_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="sessionreplaychunk",
            index=models.Index(fields=["created_at"], name="workflow_se_created_4d2352_idx"),
        ),
        migrations.AddConstraint(
            model_name="sessionreplaychunk",
            constraint=models.UniqueConstraint(
                fields=("recording", "sequence"),
                name="workflow_session_replay_chunk_recording_sequence_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="apperror",
            index=models.Index(
                fields=["session_replay", "timestamp"],
                name="workflow_ap_session_3fb195_idx",
            ),
        ),
    ]
