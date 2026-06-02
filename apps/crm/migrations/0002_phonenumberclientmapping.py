import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("client", "0020_suppliersearchalias_and_more"),
        ("crm", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PhoneNumberClientMapping",
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
                ("phone_number", models.CharField(max_length=150, unique=True)),
                ("label", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="phone_number_mappings",
                        to="client.client",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="phone_number_mappings",
                        to="client.clientcontact",
                    ),
                ),
            ],
            options={
                "ordering": ["phone_number"],
            },
        ),
        migrations.AddIndex(
            model_name="phonenumberclientmapping",
            index=models.Index(
                fields=["client", "phone_number"],
                name="crm_phone_map_idx",
            ),
        ),
    ]
