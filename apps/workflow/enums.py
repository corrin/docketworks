from django.db import models


class AIProviderTypes(models.TextChoices):
    ANTHROPIC = "Claude"
    GOOGLE = "Gemini"
    MISTRAL = "Mistral"
    OPENAI = "OpenAI"


class NotebookLmRestriction(models.TextChoices):
    NONE = "none", "All staff"
    SUPERUSER = "superuser", "Superusers only"
