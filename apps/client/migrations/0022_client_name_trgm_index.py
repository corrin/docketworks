"""Trigram index for Python-owned client name search candidate lookup."""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("client", "0021_clientcontactmethod"),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="client",
            index=GinIndex(
                fields=["name"],
                name="client_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
