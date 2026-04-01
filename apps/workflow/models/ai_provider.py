from django.db import models

from apps.workflow.enums import AIProviderTypes


class AIProvider(models.Model):
    name = models.CharField(max_length=100, help_text="Friendly name for this provider")
    api_key = models.CharField(
        max_length=255, null=True, blank=True, help_text="API Key for this AI Provider"
    )
    default = models.BooleanField(
        default=False, help_text="Use this provider as the default"
    )
    model_name = models.CharField(
        max_length=100,
        help_text="Specific model name (e.g., gemini-2.5-flash-lite-preview-06-17)",
        blank=True,
    )
    provider_type = models.CharField(
        max_length=20, choices=AIProviderTypes, help_text="Type of AI provider"
    )

    @classmethod
    def get_default(cls):
        """Get the default AI provider."""
        return cls.objects.filter(default=True).first()

    def __str__(self):
        return f"{self.name} ({self.provider_type})"

    class Meta:
        verbose_name = "AI Provider"
        verbose_name_plural = "AI Providers"
