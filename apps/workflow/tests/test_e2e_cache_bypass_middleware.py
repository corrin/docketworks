from django.core.cache import caches
from django.test import RequestFactory, SimpleTestCase

from apps.workflow.middleware import E2ECacheBypassMiddleware
from apps.workflow.models import CompanyDefaults


class E2ECacheBypassMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.cache = caches["default"]
        self.cache_key = CompanyDefaults.get_cache_key()
        self.cache.delete(self.cache_key)
        self.middleware = E2ECacheBypassMiddleware(lambda request: "dummy response")

    def test_header_present_clears_cache(self):
        self.cache.set(self.cache_key, "sentinel", 300)
        request = self.factory.get("/", HTTP_X_E2E_CACHE_BYPASS="1")
        self.middleware(request)
        self.assertIsNone(self.cache.get(self.cache_key))

    def test_header_absent_leaves_cache_alone(self):
        self.cache.set(self.cache_key, "sentinel", 300)
        request = self.factory.get("/")
        self.middleware(request)
        self.assertEqual(self.cache.get(self.cache_key), "sentinel")

    def test_header_wrong_value_leaves_cache_alone(self):
        self.cache.set(self.cache_key, "sentinel", 300)
        request = self.factory.get("/", HTTP_X_E2E_CACHE_BYPASS="0")
        self.middleware(request)
        self.assertEqual(self.cache.get(self.cache_key), "sentinel")

    def test_response_passed_through(self):
        request = self.factory.get("/")
        response = self.middleware(request)
        self.assertEqual(response, "dummy response")
