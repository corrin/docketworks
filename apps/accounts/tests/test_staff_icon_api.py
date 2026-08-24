"""API tests for the staff icon upload and removal.

POST/DELETE /api/accounts/staff/{staff_id}/icon/ — multipart, superuser only,
through the shared apps/core/uploads seam. The icon rides outside the JSON
write path (multipart cannot share a body with the create/update payload), and
DELETE exists because the E2E database restore does not clean MEDIA_ROOT.
"""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from django.test import Client, override_settings
from PIL import Image

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

URL = "/api/accounts/staff/{id}/icon/"
PASSWORD = "s3cret-Pass!"


@pytest.fixture(autouse=True)
def _media_root(tmp_path: Path) -> Iterator[Path]:
    """Sandbox the on-disk icon writes per test (no repo-wide MEDIA_ROOT precedent)."""
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        yield tmp_path


def _png() -> BytesIO:
    buffer = BytesIO()
    Image.new("RGB", (10, 10), "white").save(buffer, format="PNG")
    buffer.seek(0)
    buffer.name = "mugshot.png"
    return buffer


def make_staff(email: str, **extra: object) -> Staff:
    return Staff.objects.create_user(
        office_email=email,
        password=PASSWORD,
        first_name="Test",
        last_name="Person",
        **extra,
    )


def client_for(staff: Staff) -> Client:
    client = Client()
    authenticate(client, staff)
    return client


def superuser_client() -> Client:
    return client_for(make_staff("super@example.com", is_superuser=True, is_office_staff=True))


class TestAuth:
    def test_anonymous_cannot_upload(self) -> None:
        target = make_staff("target@example.com")
        assert Client().post(URL.format(id=target.id), {"file": _png()}).status_code == 401

    def test_office_staff_cannot_upload(self) -> None:
        office = make_staff("office@example.com", is_office_staff=True)
        target = make_staff("target@example.com")
        response = client_for(office).post(URL.format(id=target.id), {"file": _png()})
        assert response.status_code == 403

    def test_office_staff_cannot_destroy(self) -> None:
        office = make_staff("office@example.com", is_office_staff=True)
        target = make_staff("target@example.com")
        assert client_for(office).delete(URL.format(id=target.id)).status_code == 403


class TestUpload:
    def test_upload_stores_the_icon_and_returns_the_row(self) -> None:
        target = make_staff("target@example.com")

        response = superuser_client().post(URL.format(id=target.id), {"file": _png()})

        assert response.status_code == 200
        body = response.json()
        assert body["icon_url"] is not None
        assert body["icon_url"].startswith("/")
        target.refresh_from_db()
        assert target.icon
        assert Path(target.icon.path).parent.name == "staff_icons"

    def test_replacing_the_icon_unlinks_the_old_file(self) -> None:
        target = make_staff("target@example.com")
        admin = superuser_client()
        admin.post(URL.format(id=target.id), {"file": _png()})
        target.refresh_from_db()
        old_path = Path(target.icon.path)

        admin.post(URL.format(id=target.id), {"file": _png()})

        assert not old_path.exists()

    def test_upload_rejects_a_disallowed_extension(self) -> None:
        target = make_staff("target@example.com")
        bad = BytesIO(b"not an image")
        bad.name = "mugshot.exe"
        response = superuser_client().post(URL.format(id=target.id), {"file": bad})
        assert response.status_code == 400

    def test_upload_rejects_a_mislabeled_non_image(self) -> None:
        target = make_staff("target@example.com")
        bad = BytesIO(b"not an image")
        bad.name = "mugshot.png"
        response = superuser_client().post(URL.format(id=target.id), {"file": bad})
        assert response.status_code == 400

    def test_upload_rejects_an_empty_file(self) -> None:
        target = make_staff("target@example.com")
        empty = BytesIO(b"")
        empty.name = "mugshot.png"
        response = superuser_client().post(URL.format(id=target.id), {"file": empty})
        assert response.status_code == 400

    def test_upload_rejects_an_oversized_file(self) -> None:
        target = make_staff("target@example.com")
        big = BytesIO(b"0" * (5 * 1024 * 1024 + 1))
        big.name = "mugshot.png"
        response = superuser_client().post(URL.format(id=target.id), {"file": big})
        assert response.status_code == 400

    def test_unknown_staff_is_a_404(self) -> None:
        response = superuser_client().post(
            URL.format(id="00000000-0000-0000-0000-000000000000"), {"file": _png()}
        )
        assert response.status_code == 404


class TestDestroy:
    def test_destroy_clears_the_icon_and_unlinks_the_file(self) -> None:
        target = make_staff("target@example.com")
        admin = superuser_client()
        admin.post(URL.format(id=target.id), {"file": _png()})
        target.refresh_from_db()
        stored = Path(target.icon.path)

        response = admin.delete(URL.format(id=target.id))

        assert response.status_code == 200
        assert response.json()["icon_url"] is None
        target.refresh_from_db()
        assert not target.icon
        assert not stored.exists()

    def test_destroy_without_an_icon_is_a_200(self) -> None:
        """Idempotent by design — the E2E cleanup may run against any state."""
        target = make_staff("target@example.com")
        response = superuser_client().delete(URL.format(id=target.id))
        assert response.status_code == 200
        assert response.json()["icon_url"] is None
