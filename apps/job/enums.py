from django.db import models


class SpeedQualityTradeoff(models.TextChoices):
    """
    Speed vs quality tradeoff for workshop execution
    """

    FAST = "fast", "Fast - Prioritize Speed"
    NORMAL = "normal", "Normal - Balanced"
    QUALITY = "quality", "Quality - Prioritize Quality"


class RDTIType(models.TextChoices):
    """
    R&D Tax Incentive classification for jobs.
    """

    NON_RD = "non_rd", "Non-R&D"
    CORE_RD = "core_rd", "Core R&D"
    SUPPORTING_RD = "supporting_rd", "Supporting R&D"


class MetalType(models.TextChoices):
    """
    Types of metal used in jobs
    """

    STAINLESS_STEEL = "stainless_steel", "Stainless Steel"
    MILD_STEEL = "mild_steel", "Mild Steel"
    ALUMINUM = "aluminum", "Aluminum"
    BRASS = "brass", "Brass"
    COPPER = "copper", "Copper"
    TITANIUM = "titanium", "Titanium"
    ZINC = "zinc", "Zinc"
    GALVANIZED = "galvanized", "Galvanized"
    UNSPECIFIED = "unspecified", "Unspecified"
    OTHER = "other", "Other"
