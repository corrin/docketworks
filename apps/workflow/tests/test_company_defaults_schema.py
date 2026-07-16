"""
Tests for CompanyDefaults schema API and metadata.
"""

from django.db import models
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults
from apps.workflow.models.settings_metadata import (
    COMPANY_DEFAULTS_FIELD_SECTIONS,
    SettingsSection,
    get_field_metadata,
    get_ui_type_for_field,
)


class SettingsMetadataTests(TestCase):
    """Test settings metadata utilities."""

    def test_all_fields_have_sections(self):
        """Every CompanyDefaults field must have a section assigned."""
        model = CompanyDefaults
        missing = []

        for field in model._meta.get_fields():
            if not hasattr(field, "column"):
                continue
            if field.name not in COMPANY_DEFAULTS_FIELD_SECTIONS:
                missing.append(field.name)

        self.assertEqual(
            missing,
            [],
            f"Fields without sections: {missing}. "
            f"Add them to COMPANY_DEFAULTS_FIELD_SECTIONS.",
        )

    def test_all_sections_are_valid(self):
        """All section keys in mapping must be valid SettingsSection keys."""
        valid_keys = {s[0] for s in SettingsSection.all_sections()}

        for field_name, section_key in COMPANY_DEFAULTS_FIELD_SECTIONS.items():
            self.assertIn(
                section_key,
                valid_keys,
                f"Field '{field_name}' has invalid section '{section_key}'",
            )

    def test_ui_type_mapping_char_field(self):
        """Test CharField maps to 'text' UI type."""
        char_field = models.CharField(max_length=100)
        self.assertEqual(get_ui_type_for_field(char_field), "text")

    def test_ui_type_mapping_boolean_field(self):
        """Test BooleanField maps to 'boolean' UI type."""
        bool_field = models.BooleanField()
        self.assertEqual(get_ui_type_for_field(bool_field), "boolean")

    def test_ui_type_mapping_decimal_field(self):
        """Test DecimalField maps to 'number' UI type."""
        decimal_field = models.DecimalField(max_digits=5, decimal_places=2)
        self.assertEqual(get_ui_type_for_field(decimal_field), "number")

    def test_ui_type_mapping_time_field(self):
        """Test TimeField maps to 'time' UI type."""
        time_field = models.TimeField()
        self.assertEqual(get_ui_type_for_field(time_field), "time")

    def test_ui_type_mapping_url_field(self):
        """Test URLField maps to 'url' UI type."""
        url_field = models.URLField()
        self.assertEqual(get_ui_type_for_field(url_field), "url")

    def test_get_field_metadata_structure(self):
        """Test that get_field_metadata returns expected structure."""
        char_field = models.CharField(
            max_length=100,
            help_text="Test help text",
            verbose_name="Test Field",
        )
        char_field.blank = False
        char_field.null = False

        metadata = get_field_metadata(char_field, "test_field")

        self.assertEqual(metadata["key"], "test_field")
        self.assertEqual(metadata["label"], "Test Field")
        self.assertEqual(metadata["type"], "text")
        self.assertTrue(metadata["required"])
        self.assertEqual(metadata["help_text"], "Test help text")
        self.assertIn("section", metadata)

    def test_settings_section_all_sections(self):
        """Test SettingsSection.all_sections() returns expected sections."""
        sections = SettingsSection.all_sections()

        self.assertIsInstance(sections, list)
        self.assertTrue(len(sections) > 0)

        # Each section should be a tuple of (key, title, order)
        for section in sections:
            self.assertEqual(len(section), 3)
            self.assertIsInstance(section[0], str)  # key
            self.assertIsInstance(section[1], str)  # title
            self.assertIsInstance(section[2], int)  # order

    def test_settings_section_get_section_info(self):
        """Test SettingsSection.get_section_info() returns correct info."""
        info = SettingsSection.get_section_info("company")
        self.assertIsNotNone(info)
        self.assertEqual(info[0], "company")
        self.assertEqual(info[1], "Company")

        # Non-existent section returns None
        info = SettingsSection.get_section_info("nonexistent")
        self.assertIsNone(info)


class CompanyDefaultsSchemaAPITests(BaseTestCase):
    """Test the schema API endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.staff = Staff.objects.create_user(
            email="test@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
        )

    def test_schema_endpoint_returns_sections(self):
        """GET /api/company-defaults/schema/ returns section structure."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/company-defaults/schema/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("sections", response.data)
        self.assertIsInstance(response.data["sections"], list)

    def test_schema_sections_have_required_keys(self):
        """Each section has key, title, order, and fields."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/company-defaults/schema/")

        for section in response.data["sections"]:
            self.assertIn("key", section)
            self.assertIn("title", section)
            self.assertIn("order", section)
            self.assertIn("fields", section)

    def test_schema_fields_have_required_keys(self):
        """Each field has key, label, type, required, section."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/company-defaults/schema/")

        for section in response.data["sections"]:
            for field in section["fields"]:
                self.assertIn("key", field)
                self.assertIn("label", field)
                self.assertIn("type", field)
                self.assertIn("required", field)
                self.assertIn("section", field)

    def test_internal_fields_excluded(self):
        """Internal fields like created_at are not in response."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/company-defaults/schema/")

        all_field_keys = []
        for section in response.data["sections"]:
            all_field_keys.extend(f["key"] for f in section["fields"])

        self.assertNotIn("created_at", all_field_keys)
        self.assertNotIn("updated_at", all_field_keys)
        self.assertNotIn("is_primary", all_field_keys)

    def test_sections_are_ordered(self):
        """Sections are returned in order."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/company-defaults/schema/")

        orders = [s["order"] for s in response.data["sections"]]
        self.assertEqual(orders, sorted(orders))

    def test_requires_authentication(self):
        """Unauthenticated requests are rejected."""
        response = self.client.get("/api/company-defaults/schema/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expected_sections_present(self):
        """Expected sections are present in response."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/company-defaults/schema/")

        section_keys = {s["key"] for s in response.data["sections"]}

        expected_sections = {
            "company",
            "working_hours",
            "finances",
            "kpi",
            "setup",
            "xero",
        }
        for expected in expected_sections:
            self.assertIn(expected, section_keys, f"Section '{expected}' missing")

    def test_company_section_has_company_name(self):
        """Company section includes company_name field."""
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/company-defaults/schema/")

        company_section = next(
            (s for s in response.data["sections"] if s["key"] == "company"), None
        )
        self.assertIsNotNone(company_section)

        field_keys = [f["key"] for f in company_section["fields"]]
        self.assertIn("company_name", field_keys)

    def test_xero_section_exposes_sales_branding_theme_selector(self) -> None:
        """The theme is operable through Company Settings, not hidden config."""
        client = APIClient()
        client.force_authenticate(user=self.staff)
        response = client.get("/api/company-defaults/schema/")
        payload = response.json()

        xero_section = next(
            section for section in payload["sections"] if section["key"] == "xero"
        )
        theme_field = next(
            field
            for field in xero_section["fields"]
            if field["key"] == "xero_sales_branding_theme_id"
        )

        self.assertEqual(theme_field["type"], "xero_branding_theme")
        self.assertEqual(theme_field["label"], "Xero Sales Branding Theme")
        self.assertFalse(theme_field["read_only"])
        self.assertIn("terms and conditions", theme_field["help_text"])
