"""The standard error envelope at its authenticated and public boundaries.

Authenticated staff receive actionable details and a persisted ``error_id``.
Expected anonymous auth refusals are generic security outcomes and do not
amplify internet traffic into database writes.
"""

from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest
from ninja import NinjaAPI, Router
from ninja.errors import HttpError
from ninja.testing import TestClient

from apps.core.envelope import (
    NOT_AUTHENTICATED_DETAIL,
    NOT_FOUND_DETAIL,
    PERMISSION_DENIED_DETAIL,
    register_exception_handlers,
)
from apps.core.errors import (
    AccessDeniedError,
    AppErrorContext,
    ConflictError,
    InvalidInputError,
    persist_app_error,
)
from apps.core.models import AppError

api = NinjaAPI(urls_namespace="core-envelope-tests")
register_exception_handlers(api)

router = Router(auth=lambda _request: "trusted-staff")


class FeatureInputError(InvalidInputError):
    """Feature-specific subtype proving category handlers apply through MRO."""


# ninja requires every view's first parameter to be named exactly ``request``;
# these fixture endpoints don't use it, so each deletes it (the errors.py
# pattern for deliberately-unused required parameters).


@router.get("/boom")
def boom(request: HttpRequest) -> dict[str, str]:
    del request
    raise RuntimeError("kaboom")


@router.get("/public-boom", auth=None)
def public_boom(request: HttpRequest) -> dict[str, str]:
    del request
    raise RuntimeError("database host is db.internal.example")


@router.get("/prepersisted")
def prepersisted(request: HttpRequest) -> dict[str, str]:
    """The ADR 0019 handler shape: persist with rich context, then re-raise."""
    del request
    try:
        raise ValueError("service failure")
    except ValueError as exc:
        persist_app_error(exc, AppErrorContext(additional_context={"layer": "service"}))
        raise


@router.get("/missing")
def missing(request: HttpRequest) -> dict[str, str]:
    del request
    raise Http404("job 42 does not exist")


@router.get("/forbidden")
def forbidden(request: HttpRequest) -> dict[str, str]:
    del request
    raise PermissionDenied


@router.get("/forbidden-custom")
def forbidden_custom(request: HttpRequest) -> dict[str, str]:
    del request
    raise PermissionDenied("no access to job 5")


@router.get("/conflict")
def conflict(request: HttpRequest) -> dict[str, str]:
    del request
    raise HttpError(409, "job was modified by someone else")


@router.get("/public-conflict", auth=None)
def public_conflict(request: HttpRequest) -> dict[str, str]:
    del request
    raise HttpError(409, "private provider account 123 conflicted")


@router.get("/application-input")
def application_input(request: HttpRequest) -> dict[str, str]:
    del request
    raise FeatureInputError("week_start_date must be a Monday")


@router.get("/application-denied")
def application_denied(request: HttpRequest) -> dict[str, str]:
    del request
    raise AccessDeniedError("You can only update your own timesheet entries.")


@router.get("/application-conflict")
def application_conflict(request: HttpRequest) -> dict[str, str]:
    del request
    raise ConflictError("Company already exists in the accounting provider")


@router.get("/public-application-conflict", auth=None)
def public_application_conflict(request: HttpRequest) -> dict[str, str]:
    del request
    raise ConflictError("private provider account 123 conflicted")


@router.get("/plain-value-error")
def plain_value_error(request: HttpRequest) -> dict[str, str]:
    del request
    raise ValueError("malformed provider data")


@router.get("/private", auth=lambda _request: None)
def private(request: HttpRequest) -> dict[str, str]:
    del request
    return {"ok": "yes"}


@router.get("/typed")
def typed(request: HttpRequest, n: int) -> dict[str, int]:
    del request
    return {"n": n}


api.add_router("", router)
client = TestClient(api)


def _single_row_matching(error_id: object) -> AppError:
    assert isinstance(error_id, str)
    row = AppError.objects.get()  # exactly one row — persistence is idempotent
    assert row.id == UUID(error_id)
    return row


@pytest.mark.django_db
class TestEnvelopeShape:
    def test_unexpected_exception_returns_500_with_verbatim_message(self) -> None:
        response = client.get("/boom")

        assert response.status_code == 500
        body = response.json()
        assert set(body) == {"detail", "error_id"}
        assert body["detail"] == "kaboom"
        row = _single_row_matching(body["error_id"])
        assert row.data is not None
        assert row.data["request_path"] == "/boom"
        assert row.data["request_method"] == "GET"

    def test_anonymous_unexpected_exception_masks_detail_but_keeps_error_id(self) -> None:
        response = client.get("/public-boom")

        assert response.status_code == 500
        body = response.json()
        assert body["detail"] == "Unexpected server error."
        _single_row_matching(body["error_id"])

    def test_error_id_points_at_the_row_persisted_deeper_in_the_stack(self) -> None:
        response = client.get("/prepersisted")

        assert response.status_code == 500
        body = response.json()
        row = _single_row_matching(body["error_id"])
        # The service-layer write won; the boundary added no second row.
        assert row.data is not None
        assert row.data["layer"] == "service"
        assert row.function == "prepersisted"

    def test_http_404_maps_to_not_found_envelope(self) -> None:
        response = client.get("/missing")

        assert response.status_code == 404
        body = response.json()
        assert body["detail"] == NOT_FOUND_DETAIL
        _single_row_matching(body["error_id"])

    def test_permission_denied_maps_to_403(self) -> None:
        response = client.get("/forbidden")

        assert response.status_code == 403
        body = response.json()
        assert body["detail"] == PERMISSION_DENIED_DETAIL
        _single_row_matching(body["error_id"])

    def test_permission_denied_custom_message_is_carried_through(self) -> None:
        response = client.get("/forbidden-custom")

        assert response.status_code == 403
        assert response.json()["detail"] == "no access to job 5"

    def test_http_error_keeps_its_status_and_message(self) -> None:
        response = client.get("/conflict")

        assert response.status_code == 409
        body = response.json()
        assert body["detail"] == "job was modified by someone else"
        _single_row_matching(body["error_id"])

    @pytest.mark.parametrize(
        ("path", "status", "detail"),
        [
            ("/application-input", 400, "week_start_date must be a Monday"),
            (
                "/application-denied",
                403,
                "You can only update your own timesheet entries.",
            ),
            (
                "/application-conflict",
                409,
                "Company already exists in the accounting provider",
            ),
        ],
    )
    def test_application_error_uses_standard_envelope(
        self, path: str, status: int, detail: str
    ) -> None:
        response = client.get(path)

        assert response.status_code == status
        body = response.json()
        assert body["detail"] == detail
        _single_row_matching(body["error_id"])

    def test_plain_value_error_remains_an_unexpected_500(self) -> None:
        response = client.get("/plain-value-error")

        assert response.status_code == 500
        assert response.json()["detail"] == "malformed provider data"
        _single_row_matching(response.json()["error_id"])

    def test_anonymous_http_error_masks_domain_detail(self) -> None:
        response = client.get("/public-conflict")

        assert response.status_code == 409
        body = response.json()
        assert body["detail"] == "Request conflict."
        _single_row_matching(body["error_id"])

    def test_anonymous_application_error_masks_domain_detail(self) -> None:
        response = client.get("/public-application-conflict")

        assert response.status_code == 409
        body = response.json()
        assert body["detail"] == "Request conflict."
        _single_row_matching(body["error_id"])

    def test_failed_authentication_maps_to_401(self) -> None:
        response = client.get("/private")

        assert response.status_code == 401
        assert response.json() == {
            "detail": NOT_AUTHENTICATED_DETAIL,
            "code": "authentication_required",
            "error_id": None,
        }
        assert response.headers["WWW-Authenticate"] == "Cookie"
        assert not AppError.objects.exists()

    def test_request_validation_maps_to_422_with_error_list(self) -> None:
        response = client.get("/typed?n=not-an-int")

        assert response.status_code == 422
        body = response.json()
        assert isinstance(body["detail"], list)
        assert body["detail"][0]["loc"] == ["query", "n"]
        _single_row_matching(body["error_id"])
