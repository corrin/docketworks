"""Access logging middleware and the disallowed-host traceback filter.

The load-bearing case is an authenticated ``/api/**`` request. v1's middleware
read ``request.user`` before calling the view, which under ninja auth resolves
to AnonymousUser for every API request — a faithful port would have logged
nothing at all and looked correct in a v1-shaped test.
"""

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client

pytestmark = pytest.mark.django_db


def _access_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The formatted lines this request produced on the access logger."""
    return [record.getMessage() for record in caplog.records if record.name == "access"]


def test_authenticated_api_request_is_logged(
    api: Client,
    office_staff: AbstractBaseUser,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A cookie-authenticated API call produces one line naming the caller."""
    with caplog.at_level("INFO", logger="access"):
        response = api.get("/api/company-defaults/")

    assert response.status_code == 200
    lines = _access_records(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert "method=GET" in line
    assert "status=200" in line
    # get_username(), not a hardcoded field: v2 renamed Staff.email to
    # office_email, and v1's getattr(user, "email", str(user)) would have
    # degraded silently to the repr rather than failing.
    assert f"user={office_staff.get_username()}" in line
    assert "path=/api/company-defaults/" in line
    assert "replay=-" in line


def test_session_replay_header_is_carried_into_the_line(
    api: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``replay=`` is the only join between a request and its recording."""
    replay_id = "0f9f1b2e-2f4a-4c2e-9f1a-2b3c4d5e6f70"
    with caplog.at_level("INFO", logger="access"):
        api.get("/api/company-defaults/", headers={"X-Session-Replay-Id": replay_id})

    assert f"replay={replay_id}" in _access_records(caplog)[0]


def test_anonymous_request_is_not_logged(
    client: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No principal, no line: the log is a record of who did what."""
    with caplog.at_level("INFO", logger="access"):
        client.get("/api/company-defaults/")

    assert _access_records(caplog) == []


def test_disallowed_host_is_rejected_without_a_traceback(
    client: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Host probing is refused, recorded once, and logged without a traceback.

    The 400 is Django's own. What this asserts is that the record survives
    (the probe stays visible) while its traceback does not, which is the whole
    behaviour v1's DisallowedHostMiddleware was written to get.
    """
    with caplog.at_level("WARNING", logger="django.security.DisallowedHost"):
        response = client.get("/api/company-defaults/", headers={"Host": "evil.example"})

    assert response.status_code == 400
    records = [r for r in caplog.records if r.name == "django.security.DisallowedHost"]
    assert len(records) == 1
    assert "evil.example" in records[0].getMessage()
    assert records[0].exc_info is None
