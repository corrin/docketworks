from datetime import timedelta

from django.core.cache import caches
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.workflow.middleware import E2ECacheBypassMiddleware
from apps.workflow.models import CacheState, CompanyDefaults


class E2ECacheBypassMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.cache = caches["default"]
        self.cache_key = CompanyDefaults.get_cache_key()
        self.cache.delete(self.cache_key)
        self.middleware = E2ECacheBypassMiddleware(lambda request: "dummy response")

    def test_cache_disabled_clears_solo_cache(self):
        CacheState.objects.update_or_create(
            pk=1,
            defaults={"disabled_until": timezone.now() + timedelta(hours=1)},
        )
        self.cache.set(self.cache_key, "sentinel", 300)
        self.middleware(self.factory.get("/"))
        self.assertIsNone(self.cache.get(self.cache_key))

    def test_cache_not_disabled_leaves_solo_cache_alone(self):
        CacheState.objects.update_or_create(pk=1, defaults={"disabled_until": None})
        self.cache.set(self.cache_key, "sentinel", 300)
        self.middleware(self.factory.get("/"))
        self.assertEqual(self.cache.get(self.cache_key), "sentinel")

    def test_expired_disable_treated_as_enabled(self):
        CacheState.objects.update_or_create(
            pk=1,
            defaults={"disabled_until": timezone.now() - timedelta(seconds=1)},
        )
        self.cache.set(self.cache_key, "sentinel", 300)
        self.middleware(self.factory.get("/"))
        self.assertEqual(self.cache.get(self.cache_key), "sentinel")

    def test_response_passed_through(self):
        response = self.middleware(self.factory.get("/"))
        self.assertEqual(response, "dummy response")
