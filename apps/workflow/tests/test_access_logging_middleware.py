from unittest.mock import patch

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.accounts.models import Staff
from apps.workflow.middleware import AccessLoggingMiddleware


@pytest.mark.django_db
def test_access_log_includes_response_status_and_duration():
    staff = Staff.objects.create_user(
        email="access-log@example.test",
        password="testpass123",
    )
    request = RequestFactory().get(
        "/api/job/kanban/",
        HTTP_X_SESSION_REPLAY_ID="11111111-1111-1111-1111-111111111111",
    )
    request.user = staff
    middleware = AccessLoggingMiddleware(lambda _request: HttpResponse(status=418))

    with (
        patch("apps.workflow.middleware.perf_counter", side_effect=[10.0, 10.12345]),
        patch("apps.workflow.middleware.access_logger.info") as log_info,
    ):
        response = middleware(request)

    assert response.status_code == 418
    log_info.assert_called_once()
    log_format, *log_args = log_info.call_args.args
    assert log_format == (
        "%s\tmethod=%s\tstatus=%s\tduration_ms=%.2f\treplay=%s\tuser=%s\tpath=%s"
    )
    assert log_args[1] == "GET"
    assert log_args[2] == 418
    assert log_args[3] == pytest.approx(123.45)
    assert log_args[4] == "11111111-1111-1111-1111-111111111111"
    assert log_args[5] == "access-log@example.test"
    assert log_args[6] == "/api/job/kanban/"


def test_access_log_skips_unauthenticated_requests():
    request = RequestFactory().get("/api/job/kanban/")
    request.user = type("AnonymousUser", (), {"is_authenticated": False})()
    middleware = AccessLoggingMiddleware(lambda _request: HttpResponse(status=401))

    with (
        patch(
            "apps.workflow.middleware.JWTAuthentication.authenticate",
            return_value=None,
        ),
        patch("apps.workflow.middleware.access_logger.info") as log_info,
    ):
        response = middleware(request)

    assert response.status_code == 401
    log_info.assert_not_called()
