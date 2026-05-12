"""
GIN index on the weighted tsvector that backs stock FTS.

The expression matches `STOCK_SEARCH_VECTOR` in
`apps/purchasing/services/stock_search_service.py` exactly: any divergence
between the two will cause Postgres to ignore the index.
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0030_add_stock_updated_at"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="stock",
            index=GinIndex(
                SearchVector("description", weight="A", config="english")
                + SearchVector("item_code", weight="A", config="english")
                + SearchVector("metal_type", weight="B", config="english")
                + SearchVector("alloy", weight="B", config="english")
                + SearchVector("specifics", weight="B", config="english")
                + SearchVector("location", weight="C", config="english"),
                name="stock_fts_idx",
            ),
        ),
    ]
