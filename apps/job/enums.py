"""Enumerated choice types for the job application."""

from django.db import models
from django.utils.translation import gettext_lazy


class SpeedQualityTradeoff(models.TextChoices):
    """Speed vs quality tradeoff for workshop execution."""

    FAST = "fast", gettext_lazy("Fast - Prioritize Speed")
    NORMAL = "normal", gettext_lazy("Normal - Balanced")
    QUALITY = "quality", gettext_lazy("Quality - Prioritize Quality")


class RDTIType(models.TextChoices):
    """R&D Tax Incentive classification for jobs."""

    NON_RD = "non_rd", gettext_lazy("Non-R&D")
    CORE_RD = "core_rd", gettext_lazy("Core R&D")
    SUPPORTING_RD = "supporting_rd", gettext_lazy("Supporting R&D")


class MetalType(models.TextChoices):
    """Types of metal used in jobs."""

    STAINLESS_STEEL = "stainless_steel", gettext_lazy("Stainless Steel")
    MILD_STEEL = "mild_steel", gettext_lazy("Mild Steel")
    ALUMINIUM = "aluminium", gettext_lazy("Aluminium")
    BRASS = "brass", gettext_lazy("Brass")
    COPPER = "copper", gettext_lazy("Copper")
    TITANIUM = "titanium", gettext_lazy("Titanium")
    ZINC = "zinc", gettext_lazy("Zinc")
    GALVANIZED = "galvanized", gettext_lazy("Galvanized")
    OTHER = "other", gettext_lazy("Other")


class CostLineOwner(models.TextChoices):
    """The workflow responsible for a cost line's mutations."""

    LEAVE = "leave", gettext_lazy("Leave")
    STOCKTAKE = "stocktake", gettext_lazy("Stocktake")
    STOCK = "stock", gettext_lazy("Stock movement")
