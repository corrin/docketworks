"""One fake Places response, shared by every test that mocks the Maps boundary.

Three test files each built their own before this existed, and adding the two
fields the vendor-call recorder reads broke all three at once — which is the
duplication ADR 0039 exists to prevent, in the test tree where it is easiest to
excuse.
"""

from datetime import timedelta
from unittest.mock import MagicMock

import requests

POST_TARGET = "apps.platform.integrations.google.places.requests.post"
POST_URL = "https://places.googleapis.com/v1/places:searchText"


def places_reply(status: int, **attributes: object) -> MagicMock:
    """A Places response the recorder can read as well as the parser can.

    ``request`` and ``elapsed`` are what ``record_response`` needs: a lookup
    records what it spent, so a fake without them is a shape requests never
    returns.
    """
    response = MagicMock()
    response.status_code = status
    response.request = requests.Request(method="POST", url=POST_URL).prepare()
    response.elapsed = timedelta(milliseconds=5)
    for name, value in attributes.items():
        setattr(response, name, value)
    return response


def places_ok(payload: object) -> MagicMock:
    """A 200 carrying this JSON body."""
    response = places_reply(200)
    response.json.return_value = payload
    return response
