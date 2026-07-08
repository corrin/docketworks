import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from encrypted_model_fields.fields import (
    EncryptedCharField,
)

from apps.company.models import Company
from apps.job.enums import MetalType
from apps.purchasing.models import Stock


class SupplierCredential(models.Model):
    """Encrypted credentials for a supplier portal or API."""

    class CredentialType(models.TextChoices):
        USERNAME_PASSWORD = "username_password", "Username and password"
        API_KEY = "api_key", "API key"
        API_KEY_HEADER = "api_key_header", "API key header"
        OAUTH2 = "oauth2", "OAuth 2"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="supplier_credentials"
    )
    label = models.CharField(max_length=255)
    credential_type = models.CharField(
        max_length=50,
        choices=CredentialType.choices,
    )
    username = EncryptedCharField(max_length=255, blank=True, null=True)
    password = EncryptedCharField(max_length=255, blank=True, null=True)
    api_key = EncryptedCharField(max_length=500, blank=True, null=True)
    extra_config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["supplier__name", "label"]
        verbose_name = "Supplier Credential"
        verbose_name_plural = "Supplier Credentials"
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "label"],
                name="unique_supplier_credential_label",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.credential_type == self.CredentialType.USERNAME_PASSWORD:
            if not self.username:
                raise ValidationError({"username": "Username is required."})
            if not self.password:
                raise ValidationError({"password": "Password is required."})
        elif self.credential_type in (
            self.CredentialType.API_KEY,
            self.CredentialType.API_KEY_HEADER,
        ):
            if not self.api_key:
                raise ValidationError({"api_key": "API key is required."})
        elif self.credential_type == self.CredentialType.OAUTH2:
            required_keys = {"client_id", "client_secret", "token_url"}
            missing = required_keys - set(self.extra_config)
            if missing:
                missing_keys = ", ".join(sorted(missing))
                raise ValidationError(
                    {"extra_config": f"Missing OAuth2 config keys: {missing_keys}."}
                )
        else:
            raise ValidationError(
                {"credential_type": f"Unknown credential type: {self.credential_type}"}
            )

    def get_credential_dict(self) -> dict[str, Any]:
        if self.credential_type == self.CredentialType.USERNAME_PASSWORD:
            return {"username": self.username, "password": self.password}
        if self.credential_type == self.CredentialType.API_KEY:
            return {"api_key": self.api_key}
        if self.credential_type == self.CredentialType.API_KEY_HEADER:
            header_name = self.extra_config.get("header_name")
            if not header_name:
                raise ValueError("api_key_header credentials require header_name")
            return {"header_name": header_name, "api_key": self.api_key}
        if self.credential_type == self.CredentialType.OAUTH2:
            return dict(self.extra_config)
        raise ValueError(f"Unknown credential type: {self.credential_type}")

    def __str__(self) -> str:
        return f"{self.supplier.name} - {self.label}"


class SupplierScraperConfig(models.Model):
    """Maps a supplier to the scraper implementation and credential to use."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.OneToOneField(
        Company, on_delete=models.PROTECT, related_name="scraper_config"
    )
    scraper_class = models.CharField(max_length=255, db_index=True)
    portal_url = models.URLField(max_length=1000)
    is_enabled = models.BooleanField(default=True)
    active_credential = models.ForeignKey(
        SupplierCredential,
        on_delete=models.PROTECT,
        related_name="scraper_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["supplier__name"]
        verbose_name = "Supplier Scraper Config"
        verbose_name_plural = "Supplier Scraper Configs"
        constraints = [
            models.UniqueConstraint(
                fields=["scraper_class"],
                name="unique_supplier_scraper_class",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.active_credential_id and self.supplier_id:
            if self.active_credential.supplier_id != self.supplier_id:
                raise ValidationError(
                    {
                        "active_credential": (
                            "Active credential must belong to the same supplier."
                        )
                    }
                )
            if not self.active_credential.is_active:
                raise ValidationError(
                    {"active_credential": "Active credential must be active."}
                )

    def __str__(self) -> str:
        return f"{self.supplier.name} - {self.scraper_class}"


class SupplierProduct(models.Model):
    """
    Products scraped from supplier websites for pricing/availability lookup.
    This is NOT our internal product catalog - it's external supplier data.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="scraped_products"
    )
    price_list = models.ForeignKey(
        "SupplierPriceList", on_delete=models.CASCADE, related_name="products"
    )
    product_name = models.CharField(max_length=500)
    item_no = models.CharField(max_length=100, help_text="Supplier's item/SKU number")
    description = models.TextField(blank=True, null=True)
    specifications = models.TextField(blank=True, null=True)
    variant_id = models.CharField(
        max_length=100, help_text="Unique variant identifier from supplier"
    )
    variant_width = models.CharField(max_length=50, blank=True, null=True)
    variant_length = models.CharField(max_length=50, blank=True, null=True)
    variant_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    price_unit = models.CharField(
        max_length=50, blank=True, null=True, help_text="e.g., 'per metre', 'each'"
    )
    variant_available_stock = models.IntegerField(blank=True, null=True)
    url = models.URLField(
        max_length=1000, help_text="Direct URL to this product on supplier's website"
    )

    is_discontinued = models.BooleanField(
        default=False,
        help_text="Product URL no longer in supplier sitemap; skip future scrapes",
    )

    # Standard audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_scraped = models.DateTimeField(auto_now=True)

    # # Inventory mapping fields (parsed from raw product data)
    # # These fields will be populated by the LLM parser to match Stock model structure
    parsed_item_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Item code parsed for inventory mapping",
    )
    parsed_description = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Standardized description for inventory",
    )
    parsed_metal_type = models.CharField(
        max_length=50,
        choices=MetalType.choices,
        blank=True,
        null=True,
        help_text="Metal type parsed from product specifications",
    )
    parsed_alloy = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Alloy specification (e.g., 304, 6061)",
    )
    parsed_specifics = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Specific details parsed from product data",
    )
    parsed_dimensions = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Standardized dimensions format",
    )
    parsed_unit_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Standardized unit cost",
    )
    parsed_price_unit = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Standardized price unit (e.g., 'per metre', 'each')",
    )

    # Parser metadata
    parsed_at = models.DateTimeField(blank=True, null=True)
    parser_version = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Version of parser used for this data",
    )
    parser_confidence = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Parser confidence score 0.00-1.00",
    )

    # Mapping relationship
    mapping_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="SHA-256 hash linking to ProductParsingMapping for this product",
    )

    class Meta:
        unique_together = ["supplier", "url", "item_no", "variant_id"]
        indexes = [
            models.Index(fields=["variant_id"]),
            models.Index(fields=["item_no"]),
            models.Index(fields=["url"]),
            models.Index(fields=["product_name"]),
        ]

    def __str__(self):
        return f"{self.supplier.name} - {self.product_name} - {self.variant_id}"


class SupplierPriceList(models.Model):
    """
    Represents a specific import of a supplier's price list.J
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="price_lists"
    )
    file_name = models.CharField(
        max_length=255, help_text="Original filename of the uploaded price list"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "Supplier Price List"
        verbose_name_plural = "Supplier Price Lists"

    def __str__(self):
        return f"{self.supplier.name} - {self.file_name} ({self.uploaded_at.strftime('%Y-%m-%d %H:%M')})"


class ScrapeJob(models.Model):
    """
    Tracks scraping job execution for monitoring and preventing concurrent runs.
    """

    STATUS_CHOICES = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="scrape_jobs"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    products_scraped = models.IntegerField(default=0)
    products_failed = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Scrape Job"
        verbose_name_plural = "Scrape Jobs"

    def __str__(self):
        return f"{self.supplier.name} - {self.status} ({self.started_at.strftime('%Y-%m-%d %H:%M')})"


class ProductParsingMapping(models.Model):
    """
    Permanent mapping for LLM parsing results to ensure consistent parsing
    of identical input data. Once parsed, the same input always produces
    the same structured output.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Input hash for mapping lookup
    input_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 hash of normalized input data",
    )

    # Original input data for reference
    input_data = models.JSONField(help_text="Original input data that was parsed")

    derived_key = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Derived key for this mapping, if applicable",
    )  # **Format**: `{METAL_TYPE}-{ALLOY}-{FORM}-{DIMENSIONS}-{SEQUENCE}`

    # Mapped output fields matching Stock model structure
    mapped_item_code = models.CharField(
        max_length=100, blank=True, null=True
    )  # IN Xero

    mapped_description = models.CharField(max_length=255, blank=True, null=True)
    mapped_metal_type = models.CharField(
        max_length=50, choices=MetalType.choices, blank=True, null=True
    )
    mapped_alloy = models.CharField(max_length=50, blank=True, null=True)
    mapped_specifics = models.CharField(max_length=255, blank=True, null=True)
    mapped_dimensions = models.CharField(max_length=100, blank=True, null=True)
    mapped_unit_cost = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    mapped_price_unit = models.CharField(max_length=50, blank=True, null=True)

    # Parser metadata
    parser_version = models.CharField(max_length=50, blank=True, null=True)
    parser_confidence = models.DecimalField(
        max_digits=3, decimal_places=2, blank=True, null=True
    )
    llm_response = models.JSONField(
        blank=True, null=True, help_text="Full LLM response for debugging"
    )

    # Validation fields
    is_validated = models.BooleanField(
        default=False, help_text="Whether this mapping has been manually validated"
    )
    validated_by = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Staff member who validated this mapping",
    )
    validated_at = models.DateTimeField(
        null=True, blank=True, help_text="When this mapping was validated"
    )
    validation_notes = models.TextField(
        blank=True, null=True, help_text="Notes from manual validation"
    )

    # Xero integration field
    item_code_is_in_xero = models.BooleanField(
        default=False,
        help_text="Whether the mapped item code exists in Xero inventory (Stock model)",
    )
    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product Parsing Mapping"
        verbose_name_plural = "Product Parsing Mappings"
        indexes = [
            models.Index(fields=["input_hash"]),
            models.Index(fields=["created_at"]),
        ]

    def update_xero_status(self):
        """Update the item_code_is_in_xero field based on Stock model.
        If item doesn't exist in Xero, clear mapped_item_code to maintain FK integrity.
        """
        if self.mapped_item_code:
            self.item_code_is_in_xero = Stock.objects.filter(
                item_code=self.mapped_item_code
            ).exists()

            # If item doesn't exist in Xero, clear the mapped_item_code
            if not self.item_code_is_in_xero:
                self.mapped_item_code = None
        else:
            self.item_code_is_in_xero = False

    def __str__(self):
        return f"Mapping: {self.input_hash[:8]}... → {self.mapped_description or 'No description'}"
