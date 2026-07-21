"""Status-code mapping for service-layer exceptions.

The raising site chooses the exception *type* — the semantic claim. The
boundary chooses the *number*. Dispatch is by isinstance so a subclass
answers its base's status: AllocationDeletionError subclasses ValueError
and must be a 400, not a 500. Under the previous name-string dispatch it
was a 500, which is the regression these tests pin.

Bodies are asserted alongside statuses because the frontend consumes them
through the generated client, where `error` is a required key.
"""

from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import NotFound

from apps.accounting.services.invoice_calculation import InvoiceCalculationError
from apps.job.services.job_rest_service import DeltaValidationError, PreconditionFailed
from apps.job.views.job_rest_views import BaseJobRestView
from apps.purchasing.services.allocation_service import AllocationDeletionError
from apps.testing import BaseTestCase
from apps.workflow.models import AppError


class HandleServiceErrorMappingTests(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.view = BaseJobRestView()

    def assert_maps_to(
        self, error: Exception, expected_status: int, expected_body: dict[str, str]
    ) -> None:
        response = self.view.handle_service_error(error)
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(response.data, expected_body)

    def test_value_error_is_a_bad_request(self) -> None:
        self.assert_maps_to(
            ValueError("Job with id abc not found"),
            status.HTTP_400_BAD_REQUEST,
            {"error": "Job with id abc not found"},
        )

    def test_value_error_subclasses_are_bad_requests_not_server_errors(self) -> None:
        """The regression: name-string dispatch sent these to 500."""
        for error in (
            AllocationDeletionError("cannot delete allocation"),
            InvoiceCalculationError("bad invoice total"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assert_maps_to(
                    error,
                    status.HTTP_400_BAD_REQUEST,
                    {"error": str(error)},
                )

    def test_precondition_failed_is_412(self) -> None:
        self.assert_maps_to(
            PreconditionFailed("etag mismatch"),
            status.HTTP_412_PRECONDITION_FAILED,
            {
                "error": (
                    "Precondition failed (ETag mismatch). Reload the job and retry."
                )
            },
        )

    def test_delta_validation_error_is_412_not_shadowed(self) -> None:
        """DeltaValidationError subclasses PreconditionFailed; it must not
        fall through to the generic ValueError or default arm."""
        self.assert_maps_to(
            DeltaValidationError("checksum mismatch"),
            status.HTTP_412_PRECONDITION_FAILED,
            {
                "error": (
                    "Precondition failed (ETag mismatch). Reload the job and retry."
                )
            },
        )

    def test_not_found_variants_are_404(self) -> None:
        for error in (Http404("gone"), NotFound("gone")):
            with self.subTest(error=type(error).__name__):
                self.assert_maps_to(
                    error,
                    status.HTTP_404_NOT_FOUND,
                    {"error": "Resource not found"},
                )

    def test_integrity_error_is_409(self) -> None:
        self.assert_maps_to(
            IntegrityError("duplicate key"),
            status.HTTP_409_CONFLICT,
            {"error": "Duplicate event prevented by database constraint"},
        )

    def test_permission_error_is_403(self) -> None:
        self.assert_maps_to(
            PermissionError("not allowed"),
            status.HTTP_403_FORBIDDEN,
            {"error": "not allowed"},
        )

    def test_unmapped_exception_is_500_without_leaking_the_message(self) -> None:
        self.assert_maps_to(
            RuntimeError("internal detail that should not ship"),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            {"error": "Internal server error"},
        )


class HandleServiceErrorPersistenceTests(BaseTestCase):
    def test_every_handled_error_is_persisted_exactly_once(self) -> None:
        BaseJobRestView().handle_service_error(ValueError("boom"))

        self.assertEqual(AppError.objects.count(), 1)

    def test_an_error_persisted_upstream_is_not_persisted_again(self) -> None:
        from apps.workflow.services.error_persistence import persist_app_error

        error = ValueError("boom")
        persist_app_error(error)

        BaseJobRestView().handle_service_error(error)

        self.assertEqual(AppError.objects.count(), 1)
