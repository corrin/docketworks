import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_create_system_automation_user"),
        ("workflow", "0234_nullable_company_defaults_optional_urls"),
    ]

    operations = [
        migrations.CreateModel(
            name="SearchTelemetryEvent",
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
                    "event_type",
                    models.CharField(
                        choices=[("search", "Search"), ("click", "Click")],
                        max_length=20,
                    ),
                ),
                (
                    "domain",
                    models.CharField(
                        choices=[
                            ("client", "Client"),
                            ("kanban", "Kanban"),
                            ("stock", "Stock"),
                        ],
                        max_length=20,
                    ),
                ),
                ("source", models.CharField(blank=True, max_length=100)),
                ("query", models.CharField(blank=True, max_length=255)),
                ("normalized_query", models.CharField(blank=True, max_length=255)),
                ("filters", models.JSONField(blank=True, default=dict)),
                ("result_count", models.PositiveIntegerField(default=0)),
                ("returned_count", models.PositiveIntegerField(default=0)),
                ("returned_result_ids", models.JSONField(blank=True, default=list)),
                ("selected_result_id", models.CharField(blank=True, max_length=255)),
                ("selected_label", models.CharField(blank=True, max_length=255)),
                (
                    "selected_rank",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "source_event_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "occurred_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="search_telemetry_events",
                        to="accounts.staff",
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="searchtelemetryevent",
            index=models.Index(
                fields=["domain", "event_type", "-occurred_at"],
                name="wf_search_domain_event_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="searchtelemetryevent",
            index=models.Index(
                fields=["domain", "normalized_query", "-occurred_at"],
                name="wf_search_domain_query_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="searchtelemetryevent",
            index=models.Index(
                fields=["source", "-occurred_at"],
                name="workflow_search_source_idx",
            ),
        ),
    ]
