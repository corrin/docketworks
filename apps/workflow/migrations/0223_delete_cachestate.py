# Generated for: drop CacheState (E2E cache-bypass) now that SOLO_CACHE
# routes through the cross-process "shared" Redis alias and the per-worker
# staleness it worked around no longer exists.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0222_remove_xero_sync_service"),
    ]

    operations = [
        migrations.DeleteModel(
            name="CacheState",
        ),
    ]
