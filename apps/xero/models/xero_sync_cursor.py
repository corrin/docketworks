"""Xero sync cursor model, ported from v1 ``apps/workflow/models/xero_sync_cursor.py``."""

from django.db import models


class XeroSyncCursor(models.Model):
    """Stores per-entity high-water marks for the hourly Xero sync.

    Only the hourly sync reads/writes these cursors. Webhooks never touch them.
    This prevents webhooks from advancing the cursor past data the hourly sync
    hasn't processed yet.
    """

    entity_key = models.CharField(max_length=50, unique=True)
    last_modified = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # v1 set ``app_label = "workflow"``; in v2 the app label is "xero" and
        # the v1 table name is kept via the db_table pin instead.
        db_table = "workflow_xerosynccursor"

    def __str__(self) -> str:
        return f"{self.entity_key}: {self.last_modified.isoformat()}"
