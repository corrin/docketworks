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
        app_label = "workflow"

    def __str__(self):
        return f"{self.entity_key}: {self.last_modified.isoformat()}"
