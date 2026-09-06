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
GET_TARGET = "apps.platform.integrations.google.places.requests.get"
GET_URL = "https://places.googleapis.com/v1/places/place-id"


def places_reply(
    status: int, *, method: str = "POST", url: str = POST_URL, **attributes: object
) -> MagicMock:
    """A Places response the recorder can read as well as the parser can.

    ``request`` and ``elapsed`` are what ``record_response`` needs: a lookup
    records what it spent, so a fake without them is a shape requests never
    returns.

    The verb and URL are arguments rather than constants because the two
    endpoints differ in both, and a search-shaped fake standing in for a
    fetch would record the wrong endpoint while every assertion still passed.
    """
    response = MagicMock()
    response.status_code = status
    response.request = requests.Request(method=method, url=url).prepare()
    response.elapsed = timedelta(milliseconds=5)
    for name, value in attributes.items():
        setattr(response, name, value)
    return response


def places_ok(payload: object, *, method: str = "POST", url: str = POST_URL) -> MagicMock:
    """A 200 carrying this JSON body."""
    response = places_reply(200, method=method, url=url)
    response.json.return_value = payload
    return response
