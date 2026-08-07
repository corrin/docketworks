"""The navbar reads this on every page, so its absence blocks every spec.

The filtering is the substance: restricted links must not reach a non-superuser
at all, because a client-side hide would ship them in every page's response
body where anyone can read them.
"""

import pytest
from django.test import Client

from apps.ai.enums import NotebookLmRestriction
from apps.ai.models import NotebookLmLink

pytestmark = pytest.mark.django_db

URL = "/api/ai/notebook-lm-links/menu/"


@pytest.fixture
def links() -> None:
    NotebookLmLink.objects.create(name="Everyone", url="https://x/1", order=1)
    NotebookLmLink.objects.create(
        name="Superuser only",
        url="https://x/2",
        order=2,
        restriction=NotebookLmRestriction.SUPERUSER,
    )
    NotebookLmLink.objects.create(name="Disabled", url="https://x/3", order=3, enabled=False)


def test_requires_authentication(client: Client) -> None:
    """`client` is anonymous; `api` is the authenticated fixture."""
    assert client.get(URL).status_code == 401


@pytest.mark.usefixtures("links")
def test_disabled_links_are_never_returned(api: Client) -> None:
    names = {row["name"] for row in api.get(URL).json()}

    assert "Disabled" not in names


@pytest.mark.usefixtures("links")
def test_restricted_links_are_withheld_from_ordinary_staff(api: Client) -> None:
    """Withheld server-side, not hidden client-side.

    A client-side hide would put the restricted URLs in the response body of
    every page load, which is where anyone would read them.
    """
    body = api.get(URL).json()

    assert {row["name"] for row in body} == {"Everyone"}
    assert "https://x/2" not in str(body)


@pytest.mark.usefixtures("links")
def test_superusers_see_restricted_links(superuser_api: Client) -> None:
    names = {row["name"] for row in superuser_api.get(URL).json()}

    assert names == {"Everyone", "Superuser only"}


@pytest.mark.usefixtures("links")
def test_menu_order_is_respected(superuser_api: Client) -> None:
    """The navbar renders in response order; Meta.ordering is the contract."""
    names = [row["name"] for row in superuser_api.get(URL).json()]

    assert names == ["Everyone", "Superuser only"]
