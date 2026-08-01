"""OCC state tokens remain strong when response representations are gzipped."""

from django.http import HttpRequest, HttpResponse
from django.middleware.gzip import GZipMiddleware
from django.test import RequestFactory, SimpleTestCase

from apps.workflow.middleware import ResourceVersionMiddleware


class ResourceVersionMiddlewareTests(SimpleTestCase):
    def setUp(self) -> None:
        self.request = RequestFactory().get("/", HTTP_ACCEPT_ENCODING="gzip")

    @staticmethod
    def _response(etag: str) -> HttpResponse:
        response = HttpResponse("compressible response " * 100)
        response.headers["ETag"] = etag
        return response

    def _process(self, etag: str) -> HttpResponse:
        def view(_request: HttpRequest) -> HttpResponse:
            return self._response(etag)

        preserve_version = ResourceVersionMiddleware(view)
        gzip_response = GZipMiddleware(preserve_version)
        response = gzip_response(self.request)
        if not isinstance(response, HttpResponse):
            raise TypeError("Synchronous middleware returned a non-HTTP response")
        return response

    def test_preserves_job_and_po_versions_before_gzip_weakens_etag(self) -> None:
        for strong_etag in (
            '"job:00000000-0000-0000-0000-000000000000:version"',
            '"po:00000000-0000-0000-0000-000000000000:version"',
        ):
            with self.subTest(etag=strong_etag):
                response = self._process(strong_etag)

                self.assertEqual(response.headers["Content-Encoding"], "gzip")
                self.assertEqual(response.headers["ETag"], f"W/{strong_etag}")
                self.assertEqual(
                    response.headers["X-Resource-Version"],
                    strong_etag,
                )

    def test_does_not_publish_unrelated_etag_as_a_resource_version(self) -> None:
        response = self._process('"static-content-digest"')

        self.assertEqual(response.headers["ETag"], 'W/"static-content-digest"')
        self.assertNotIn("X-Resource-Version", response.headers)
