import json
import uuid

import django.db.models.deletion
from django.db import migrations, models

SYNC_TASK_NAME = "apps.crm.tasks.sync_phone_calls_task"
DELETE_TASK_NAME = "apps.crm.tasks.delete_archived_phone_recordings_task"
SYNC_PERIODIC_TASK_NAME = "sync_phone_calls_daily"
DELETE_PERIODIC_TASK_NAME = "delete_archived_phone_recordings_daily"


def seed_phone_call_schedules(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")

    sync_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="15",
        hour="1",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Pacific/Auckland",
    )
    PeriodicTask.objects.update_or_create(
        name=SYNC_PERIODIC_TASK_NAME,
        defaults={
            "task": SYNC_TASK_NAME,
            "interval": None,
            "crontab": sync_schedule,
            "enabled": True,
            "args": json.dumps([]),
            "kwargs": json.dumps({}),
        },
    )

    delete_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="45",
        hour="1",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Pacific/Auckland",
    )
    PeriodicTask.objects.update_or_create(
        name=DELETE_PERIODIC_TASK_NAME,
        defaults={
            "task": DELETE_TASK_NAME,
            "interval": None,
            "crontab": delete_schedule,
            "enabled": True,
            "args": json.dumps([]),
            "kwargs": json.dumps({"limit": 100}),
        },
    )


def remove_phone_call_schedules(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[SYNC_PERIODIC_TASK_NAME, DELETE_PERIODIC_TASK_NAME]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("client", "0020_suppliersearchalias_and_more"),
        ("django_celery_beat", "0016_alter_crontabschedule_timezone"),
    ]

    operations = [
        migrations.CreateModel(
            name="PhoneCallRecord",
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
                ("provider_call_id", models.CharField(max_length=255, unique=True)),
                ("account_code", models.CharField(max_length=100)),
                ("call_datetime", models.DateTimeField(db_index=True)),
                ("call_date", models.DateField(db_index=True)),
                ("call_time", models.TimeField()),
                ("call_type", models.CharField(blank=True, max_length=100)),
                ("status", models.CharField(blank=True, max_length=100)),
                ("description", models.TextField(blank=True)),
                ("origin", models.CharField(blank=True, max_length=150)),
                ("destination", models.CharField(blank=True, max_length=150)),
                ("duration_seconds", models.PositiveIntegerField(default=0)),
                (
                    "charge",
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        max_digits=12,
                        null=True,
                    ),
                ),
                ("raw_json", models.JSONField()),
                ("imported_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="phone_calls",
                        to="client.client",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="phone_calls",
                        to="client.clientcontact",
                    ),
                ),
            ],
            options={
                "ordering": ["-call_datetime"],
            },
        ),
        migrations.CreateModel(
            name="PhoneCallRecording",
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
                (
                    "provider_recording_id",
                    models.CharField(max_length=255, unique=True),
                ),
                ("account_code", models.CharField(max_length=100)),
                ("filename", models.CharField(blank=True, max_length=255)),
                ("storage_path", models.CharField(blank=True, max_length=500)),
                ("content_type", models.CharField(blank=True, max_length=100)),
                (
                    "byte_size",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("sha256", models.CharField(blank=True, max_length=64)),
                (
                    "archived_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "provider_deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("provider_delete_error", models.TextField(blank=True)),
                (
                    "local_deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "call",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recording",
                        to="crm.phonecallrecord",
                    ),
                ),
            ],
            options={
                "ordering": ["-call__call_datetime"],
            },
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(
                fields=["account_code", "-call_datetime"],
                name="crm_phone_acct_call_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(
                fields=["client", "-call_datetime"],
                name="crm_phone_client_call_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(
                fields=["contact", "-call_datetime"],
                name="crm_phone_contact_call_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="phonecallrecording",
            index=models.Index(
                fields=["account_code", "archived_at"],
                name="crm_phone_rec_archive_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="phonecallrecording",
            index=models.Index(
                fields=["provider_deleted_at", "archived_at"],
                name="crm_phone_rec_delete_idx",
            ),
        ),
        migrations.RunPython(seed_phone_call_schedules, remove_phone_call_schedules),
    ]
