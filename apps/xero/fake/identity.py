"""The identity endpoint: a token refresh that rotates nothing.

The application refreshes through the SDK's ``TokenApi`` (auth.refresh_token),
which posts the stored refresh token and saves whatever comes back. Xero
issues refresh tokens single-use, so the real endpoint would kill the stored
one; this one hands the same refresh token back, which is what lets a fake
run end with the real connection exactly as it found it — the E2E teardown
has nothing to re-inject.

The response shape is OAuth 2.0's (RFC 6749 §5.1), not a recording: a token
response is a credential and is never written to disk.
"""

import re
from uuid import uuid4

from xero_python.rest import RESTResponse

from apps.xero.fake.http import FakeRequest, json_response
from apps.xero.fake.wire import Json

ACCESS_TOKEN_LIFETIME_SECONDS = 1800


def answer_refresh(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST identity.xero.com/connect/token with grant_type=refresh_token."""
    del match
    grant = request.form.get("grant_type")
    if grant != "refresh_token":
        # The authorization-code exchange never reaches the SDK (auth.py posts
        # it with requests directly) and is refused under XERO_FAKE there.
        raise ValueError(
            f"the fake identity endpoint answers refresh_token grants only, not {grant!r}"
        )
    sent = request.form.get("refresh_token")
    if not sent:
        raise ValueError("a refresh_token grant carries the refresh token")
    body: Json = {
        "id_token": None,
        "access_token": f"fake-access-token-{uuid4()}",
        "expires_in": ACCESS_TOKEN_LIFETIME_SECONDS,
        "token_type": "Bearer",
        "refresh_token": sent,
        "scope": request.form.get("scope", ""),
    }
    return json_response(200, body, {})
