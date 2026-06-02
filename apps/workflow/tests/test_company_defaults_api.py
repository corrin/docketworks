from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from apps.testing import BaseTestCase


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
