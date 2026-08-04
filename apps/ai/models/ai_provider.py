"""AI provider configuration model, ported from v1 ``apps/workflow/models/ai_provider.py``."""

from typing import ClassVar

from django.db import models

from apps.ai.enums import AIProviderTypes


class AIProvider(models.Model):
    """A configured AI provider (API key + model) selectable as the default."""

    name = models.CharField(max_length=100, help_text="Friendly name for this provider")
    api_key = models.CharField(  # noqa: DJ001
        max_length=255, null=True, blank=True, help_text="API Key for this AI Provider"
    )
    default = models.BooleanField(default=False, help_text="Use this provider as the default")
    model_name = models.CharField(  # noqa: DJ001
        max_length=100,
        help_text="Model name (e.g., gemini-flash-latest)",
        blank=True,
        null=True,
    )
    provider_type = models.CharField(
        max_length=20, choices=AIProviderTypes, help_text="Type of AI provider"
    )

    class Meta:
        db_table = "workflow_aiprovider"  # v1 home was the workflow app
        verbose_name = "AI Provider"
        verbose_name_plural = "AI Providers"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(api_key=""), name="workflow_aiprovider_api_key_not_blank"
            ),
            models.CheckConstraint(condition=~models.Q(model_name=""), name="model_name_not_blank"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.provider_type})"
