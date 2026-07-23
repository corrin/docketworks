import uuid

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults


class CompanyDefaultsAPITests(BaseTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.test_staff)

    def test_get_returns_shop_company_fk_without_name_alias(self):
        response = self.client.get("/api/company-defaults/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("shop_company", response.data)
        self.assertNotIn("shop_company_name", response.data)

    def test_get_does_not_query_company_for_shop_company_display_name(self):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/api/company-defaults/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        company_queries = [
            query["sql"]
            for query in captured.captured_queries
            if 'FROM "company_company"' in query["sql"]
        ]
        self.assertEqual(company_queries, [])

    def test_patch_canonicalizes_blank_optional_urls_to_null(self):
        response = self.client.patch(
            "/api/company-defaults/",
            {
                "master_quote_template_url": "",
                "gdrive_quotes_folder_url": "",
                "company_url": "",
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

    def test_company_url_initializes_quote_terms_once(self) -> None:
        defaults = CompanyDefaults.get_solo()
        CompanyDefaults.objects.filter(pk=defaults.pk).update(
            company_url=None,
            xero_quote_terms=None,
        )
        CompanyDefaults.clear_cache()

        response = self.client.patch(
            "/api/company-defaults/",
            {"company_url": "https://example.co.nz/"},
            format="json",
        )
        payload = response.json()

        expected_terms = (
            "Terms of trade can be found on our website: "
            "https://example.co.nz/terms-of-trade"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(payload["xero_quote_terms"], expected_terms)

        response = self.client.patch(
            "/api/company-defaults/",
            {"company_url": "https://new.example.co.nz"},
            format="json",
        )
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(payload["xero_quote_terms"], expected_terms)

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
            ["Xero quote terms must not be blank."],
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
