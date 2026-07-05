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

    def test_get_returns_shop_client_fk_without_name_alias(self):
        response = self.client.get("/api/company-defaults/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("shop_client", response.data)
        self.assertNotIn("shop_client_name", response.data)

    def test_get_does_not_query_client_for_shop_client_display_name(self):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/api/company-defaults/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        client_queries = [
            query["sql"]
            for query in captured.captured_queries
            if 'FROM "client_client"' in query["sql"]
        ]
        self.assertEqual(client_queries, [])

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
