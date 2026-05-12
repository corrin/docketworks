"""GIN index on to_tsvector('english', name) for full-text client search."""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("client", "0018_client_allow_jobs"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="client",
            index=GinIndex(
                SearchVector("name", config="english"),
                name="client_name_fts_idx",
            ),
        ),
    ]
