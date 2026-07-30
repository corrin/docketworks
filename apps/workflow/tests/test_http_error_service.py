"""HTTP status mapping follows exception semantics across API boundaries."""

from django.core.exceptions import (
    ObjectDoesNotExist,
)
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APISimpleTestCase

from apps.workflow.exceptions import PreconditionFailedError
from apps.workflow.services.http_error_service import http_status_for_exception


class HttpStatusForExceptionTests(APISimpleTestCase):
    def test_maps_precondition_failure_to_412(self) -> None:
        self.assertEqual(
            http_status_for_exception(PreconditionFailedError("stale")),
            status.HTTP_412_PRECONDITION_FAILED,
        )

    def test_maps_not_found_variants_to_404(self) -> None:
        for error in (
            Http404("missing"),
            NotFound("missing"),
            ObjectDoesNotExist("missing"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(
                    http_status_for_exception(error),
                    status.HTTP_404_NOT_FOUND,
                )

    def test_maps_integrity_failure_to_409(self) -> None:
        self.assertEqual(
            http_status_for_exception(IntegrityError("conflict")),
            status.HTTP_409_CONFLICT,
        )

    def test_maps_permission_variants_to_403(self) -> None:
        for error in (
            PermissionError("denied"),
            DjangoPermissionDenied("denied"),
            DRFPermissionDenied("denied"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(
                    http_status_for_exception(error),
                    status.HTTP_403_FORBIDDEN,
                )

    def test_maps_validation_variants_to_400(self) -> None:
        for error in (
            ValueError("invalid"),
            DjangoValidationError("invalid"),
            DRFValidationError("invalid"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(
                    http_status_for_exception(error),
                    status.HTTP_400_BAD_REQUEST,
                )

    def test_maps_unknown_failure_to_500(self) -> None:
        self.assertEqual(
            http_status_for_exception(RuntimeError("unexpected")),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
