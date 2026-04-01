import secrets
import uuid

from django.db import models
from django.utils import timezone


class ServiceAPIKey(models.Model):
    """
    API key for service-level authentication (e.g., chatbot MCP access).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100, help_text="Service name (e.g., 'Chatbot Service')"
    )
    key = models.CharField(
        max_length=64, unique=True, help_text="API key for authentication"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Service API Key"
        verbose_name_plural = "Service API Keys"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self.generate_api_key()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_api_key():
        """Generate a secure random API key."""
        return secrets.token_urlsafe(48)  # 64 character base64url string

    def mark_used(self):
        """Mark this API key as recently used."""
        self.last_used = timezone.now()
        self.save(update_fields=["last_used"])

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"
