"""Map boundary exceptions to their HTTP status codes."""

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

from apps.workflow.exceptions import PreconditionFailedError


def http_status_for_exception(error: Exception) -> int:
    """Return the status that represents ``error`` at an HTTP boundary."""
    if isinstance(error, PreconditionFailedError):
        return status.HTTP_412_PRECONDITION_FAILED
    if isinstance(error, (Http404, NotFound, ObjectDoesNotExist)):
        return status.HTTP_404_NOT_FOUND
    if isinstance(error, IntegrityError):
        return status.HTTP_409_CONFLICT
    if isinstance(
        error,
        (PermissionError, DjangoPermissionDenied, DRFPermissionDenied),
    ):
        return status.HTTP_403_FORBIDDEN
    if isinstance(error, (ValueError, DjangoValidationError, DRFValidationError)):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_500_INTERNAL_SERVER_ERROR
