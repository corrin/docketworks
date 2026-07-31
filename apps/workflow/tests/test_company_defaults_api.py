import uuid

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from apps.testing import BaseAPITestCase
from apps.workflow.models import CompanyDefaults


class CompanyDefaultsAPITests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)

    def test_get_returns_shop_company_fk_without_name_alias(self) -> None:
        response = self.client.get("/api/company-defaults/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("shop_company", response.data)
        self.assertNotIn("shop_company_name", response.data)

    def test_get_does_not_query_company_for_shop_company_display_name(self) -> None:
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/api/company-defaults/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        company_queries = [
            query["sql"]
            for query in captured.captured_queries
            if 'FROM "company_company"' in query["sql"]
        ]
        self.assertEqual(company_queries, [])

    def test_patch_clears_optional_urls_with_null(self) -> None:
        """Clearing a URL sends null; NULL is the only unset these columns hold."""
        response = self.client.patch(
            "/api/company-defaults/",
            {
                "master_quote_template_url": None,
                "gdrive_quotes_folder_url": None,
                "company_url": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["master_quote_template_url"])
        self.assertIsNone(response.data["gdrive_quotes_folder_url"])
        self.assertIsNone(response.data["company_url"])

        company_defaults = CompanyDefaults.get_solo()
        self.assertIsNone(company_defaults.master_quote_template_url)
        self.assertIsNone(company_defaults.gdrive_quotes_folder_url)
        self.assertIsNone(company_defaults.company_url)

    def test_patch_rejects_blank_optional_urls(self) -> None:
        """ "" is not a second way to say unset — it is rejected, not coerced."""
        response = self.client.patch(
            "/api/company-defaults/",
            {"company_url": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company_url", response.json())

    def test_patch_persists_and_clears_xero_sales_branding_theme(self) -> None:
        """Admins can operate the required Xero document theme setting."""
        theme_id = uuid.uuid4()
        client = APIClient()
        client.force_authenticate(user=self.test_staff)

        response = client.patch(
            "/api/company-defaults/",
            {"xero_sales_branding_theme_id": str(theme_id)},
            format="json",
        )
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(payload["xero_sales_branding_theme_id"], str(theme_id))

        response = client.patch(
            "/api/company-defaults/",
            {"xero_sales_branding_theme_id": None},
            format="json",
        )
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(payload["xero_sales_branding_theme_id"])

    def test_patch_persists_multiline_xero_quote_terms_exactly(self) -> None:
        terms = "First line\n\n  Indented final line  "

        response = self.client.patch(
            "/api/company-defaults/",
            {"xero_quote_terms": terms},
            format="json",
        )
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(payload["xero_quote_terms"], terms)
        self.assertEqual(CompanyDefaults.get_solo().xero_quote_terms, terms)

    def test_patch_of_other_xero_field_round_trips_existing_terms(self) -> None:
        """The settings form PATCHes every field in a section, terms included.

        A round-trip of the stored terms alongside another field must not be
        mistaken for an attempt to clear them, or no Xero setting is editable.
        """
        terms = CompanyDefaults.get_solo().xero_quote_terms
        self.assertTrue(terms)

        response = self.client.patch(
            "/api/company-defaults/",
            {"xero_quote_terms": terms, "xero_shortcode": "ABC123"},
            format="json",
        )
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(payload["xero_shortcode"], "ABC123")
        self.assertEqual(payload["xero_quote_terms"], terms)

    def test_patch_rejects_blank_xero_quote_terms(self) -> None:
        response = self.client.patch(
            "/api/company-defaults/",
            {"xero_quote_terms": " \n "},
            format="json",
        )
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            payload["xero_quote_terms"],
            ["Xero quote terms must not be blank."],
        )

    def test_patch_rejects_null_xero_quote_terms(self) -> None:
        response = self.client.patch(
            "/api/company-defaults/",
            {"xero_quote_terms": None},
            format="json",
        )
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            payload["xero_quote_terms"],
            ["This field may not be null."],
        )

    def test_patch_rejects_xero_quote_terms_over_4000_characters(self) -> None:
        response = self.client.patch(
            "/api/company-defaults/",
            {"xero_quote_terms": "x" * 4001},
            format="json",
        )
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            payload["xero_quote_terms"],
            ["Ensure this field has no more than 4000 characters."],
        )
