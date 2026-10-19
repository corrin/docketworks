"""AI-related enumerations."""

from django.db import models
from django.utils.translation import gettext_lazy


class AIProviderTypes(models.TextChoices):
    """Supported AI provider types."""

    ANTHROPIC = "Claude"
    GOOGLE = "Gemini"
    MISTRAL = "Mistral"
    OPENAI = "OpenAI"


class NotebookLmRestriction(models.TextChoices):
    """Who may see a NotebookLM link in the training menu."""

    NONE = "none", gettext_lazy("All staff")
    SUPERUSER = "superuser", gettext_lazy("Superusers only")
