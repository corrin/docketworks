"""Quoting domain models, ported from v1 apps/quoting.

Supplier portal credentials, scraper configuration, scraped supplier
products/price lists, scrape-job tracking, and the permanent LLM
product-parsing mapping table.
"""

import uuid
from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.job.enums import MetalType
from apps.purchasing.models import Stock


class SupplierCredential(models.Model):
    """Encrypted credentials for a supplier portal or API."""

    class CredentialType(models.TextChoices):
        """Supported kinds of supplier credential."""

        USERNAME_PASSWORD = "username_password", "Username and password"
        API_KEY = "api_key", "API key"
        API_KEY_HEADER = "api_key_header", "API key header"
        OAUTH2 = "oauth2", "OAuth 2"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        "company.Company", on_delete=models.PROTECT, related_name="supplier_credentials"
    )
    label = models.CharField(max_length=255)
    credential_type = models.CharField(
        max_length=50,
        choices=CredentialType.choices,
    )
    # Plaintext by decision (2026-08-01): field-level encryption dropped in v2 —
    # per-instance DBs owned by per-client roles make it key-management theatre
    # (v1 already stored Xero tokens unencrypted). v1 ciphertext in these columns
    # must be decrypted (or re-entered) during the one-time data migration.
    username = models.TextField(blank=True, null=True)  # noqa: DJ001 -- v1 schema parity
    password = models.TextField(blank=True, null=True)  # noqa: DJ001 -- v1 schema parity
    api_key = models.TextField(blank=True, null=True)  # noqa: DJ001 -- v1 schema parity
    extra_config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar = ["supplier__name", "label"]
        verbose_name = "Supplier Credential"
        verbose_name_plural = "Supplier Credentials"
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["supplier", "label"],
                name="unique_supplier_credential_label",
            ),
            models.CheckConstraint(
                condition=~models.Q(api_key=""),
                name="quoting_suppliercredential_api_key_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(password=""),
                name="quoting_suppliercredential_password_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(username=""),
                name="quoting_suppliercredential_username_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.supplier.name} - {self.label}"

    def clean(self) -> None:
        """Validate that the fields required by credential_type are present."""
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
        """Return the credential material as a dict keyed by credential_type."""
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


class SupplierScraperConfig(models.Model):
    """Maps a supplier to the scraper implementation and credential to use."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.OneToOneField(
        "company.Company", on_delete=models.PROTECT, related_name="scraper_config"
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
        ordering: ClassVar = ["supplier__name"]
        verbose_name = "Supplier Scraper Config"
        verbose_name_plural = "Supplier Scraper Configs"
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["scraper_class"],
                name="unique_supplier_scraper_class",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.supplier.name} - {self.scraper_class}"

    def clean(self) -> None:
        """Validate that the active credential belongs to the supplier and is active."""
        super().clean()
        if self.active_credential_id and self.supplier_id:
            if self.active_credential.supplier_id != self.supplier_id:
                raise ValidationError(
                    {"active_credential": ("Active credential must belong to the same supplier.")}
                )
            if not self.active_credential.is_active:
                raise ValidationError({"active_credential": "Active credential must be active."})


class SupplierProduct(models.Model):
    """Products scraped from supplier websites for pricing/availability lookup.

    This is NOT our internal product catalog - it's external supplier data.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        "company.Company", on_delete=models.PROTECT, related_name="scraped_products"
    )
    price_list = models.ForeignKey(
        "SupplierPriceList", on_delete=models.CASCADE, related_name="products"
    )
    product_name = models.CharField(max_length=500)
    item_no = models.CharField(max_length=100, help_text="Supplier's item/SKU number")
    description = models.TextField(blank=True, null=True)  # noqa: DJ001 -- v1 schema parity
    specifications = models.TextField(blank=True, null=True)  # noqa: DJ001 -- v1 schema parity
    variant_id = models.CharField(
        max_length=100, help_text="Unique variant identifier from supplier"
    )
    variant_width = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50, blank=True, null=True
    )
    variant_length = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50, blank=True, null=True
    )
    variant_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    price_unit = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
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

    # Inventory mapping fields (parsed from raw product data)
    # These fields will be populated by the LLM parser to match Stock model structure
    parsed_item_code = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=100,
        blank=True,
        null=True,
        help_text="Item code parsed for inventory mapping",
    )
    parsed_description = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=255,
        blank=True,
        null=True,
        help_text="Standardized description for inventory",
    )
    parsed_metal_type = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50,
        choices=MetalType.choices,
        blank=True,
        null=True,
        help_text="Metal type parsed from product specifications",
    )
    parsed_alloy = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50,
        blank=True,
        null=True,
        help_text="Alloy specification (e.g., 304, 6061)",
    )
    parsed_specifics = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=255,
        blank=True,
        null=True,
        help_text="Specific details parsed from product data",
    )
    parsed_dimensions = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
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
    parsed_price_unit = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50,
        blank=True,
        null=True,
        help_text="Standardized price unit (e.g., 'per metre', 'each')",
    )

    # Parser metadata
    parsed_at = models.DateTimeField(blank=True, null=True)
    parser_version = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
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
    mapping_hash = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="SHA-256 hash linking to ProductParsingMapping for this product",
    )

    class Meta:
        unique_together: ClassVar = ["supplier", "url", "item_no", "variant_id"]
        indexes: ClassVar = [
            models.Index(fields=["variant_id"]),
            models.Index(fields=["item_no"]),
            models.Index(fields=["url"]),
            models.Index(fields=["product_name"]),
        ]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(description=""),
                name="quoting_supplierproduct_description_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(mapping_hash=""), name="mapping_hash_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parsed_alloy=""), name="parsed_alloy_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parsed_description=""), name="parsed_description_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parsed_dimensions=""), name="parsed_dimensions_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parsed_item_code=""), name="parsed_item_code_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parsed_metal_type=""), name="parsed_metal_type_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parsed_price_unit=""), name="parsed_price_unit_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parsed_specifics=""), name="parsed_specifics_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parser_version=""),
                name="quoting_supplierproduct_parser_version_not_blank",
            ),
            models.CheckConstraint(condition=~models.Q(price_unit=""), name="price_unit_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(specifications=""), name="specifications_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(variant_length=""), name="variant_length_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(variant_width=""), name="variant_width_not_blank"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.supplier.name} - {self.product_name} - {self.variant_id}"


class SupplierPriceList(models.Model):
    """Represents a specific import of a supplier's price list."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        "company.Company", on_delete=models.PROTECT, related_name="price_lists"
    )
    file_name = models.CharField(
        max_length=255, help_text="Original filename of the uploaded price list"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar = ["-uploaded_at"]
        verbose_name = "Supplier Price List"
        verbose_name_plural = "Supplier Price Lists"

    def __str__(self) -> str:
        uploaded = self.uploaded_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.supplier.name} - {self.file_name} ({uploaded})"


class ScrapeJob(models.Model):
    """Tracks scraping job execution for monitoring and preventing concurrent runs."""

    STATUS_CHOICES: ClassVar = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        "company.Company", on_delete=models.PROTECT, related_name="scrape_jobs"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    products_scraped = models.IntegerField(default=0)
    products_failed = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)  # noqa: DJ001 -- v1 schema parity

    class Meta:
        ordering: ClassVar = ["-started_at"]
        verbose_name = "Scrape Job"
        verbose_name_plural = "Scrape Jobs"
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(error_message=""), name="error_message_not_blank"
            ),
        ]

    def __str__(self) -> str:
        started = self.started_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.supplier.name} - {self.status} ({started})"


class ProductParsingMapping(models.Model):
    """Permanent mapping for LLM parsing results.

    Ensures consistent parsing of identical input data. Once parsed, the same
    input always produces the same structured output.
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

    derived_key = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=100,
        blank=True,
        null=True,
        help_text="Derived key for this mapping, if applicable",
    )  # **Format**: `{METAL_TYPE}-{ALLOY}-{FORM}-{DIMENSIONS}-{SEQUENCE}`

    # Mapped output fields matching Stock model structure
    mapped_item_code = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=100, blank=True, null=True
    )  # IN Xero

    mapped_description = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=255, blank=True, null=True
    )
    mapped_metal_type = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50, choices=MetalType.choices, blank=True, null=True
    )
    mapped_alloy = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50, blank=True, null=True
    )
    mapped_specifics = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=255, blank=True, null=True
    )
    mapped_dimensions = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=100, blank=True, null=True
    )
    mapped_unit_cost = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    mapped_price_unit = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50, blank=True, null=True
    )

    # Parser metadata
    parser_version = models.CharField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
        max_length=50, blank=True, null=True
    )
    parser_confidence = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
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
    validation_notes = models.TextField(  # noqa: DJ001 -- v1 schema parity; NULL means unset
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
        indexes: ClassVar = [
            models.Index(fields=["input_hash"]),
            models.Index(fields=["created_at"]),
        ]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(derived_key=""), name="derived_key_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(mapped_alloy=""), name="mapped_alloy_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(mapped_description=""), name="mapped_description_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(mapped_dimensions=""), name="mapped_dimensions_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(mapped_item_code=""), name="mapped_item_code_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(mapped_metal_type=""), name="mapped_metal_type_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(mapped_price_unit=""), name="mapped_price_unit_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(mapped_specifics=""), name="mapped_specifics_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parser_version=""),
                name="quoting_productparsingmapping_parser_version_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(validation_notes=""), name="validation_notes_not_blank"
            ),
        ]

    def __str__(self) -> str:
        return f"Mapping: {self.input_hash[:8]}... → {self.mapped_description or 'No description'}"

    def update_xero_status(self) -> None:
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
