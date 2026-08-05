"""AI-related enumerations."""

from django.db import models


class AIProviderTypes(models.TextChoices):
    """Supported AI provider types."""

    ANTHROPIC = "Claude"
    GOOGLE = "Gemini"
    MISTRAL = "Mistral"
    OPENAI = "OpenAI"


class NotebookLmRestriction(models.TextChoices):
    """Who may see a NotebookLM link in the training menu."""

    NONE = "none", "All staff"
    SUPERUSER = "superuser", "Superusers only"
