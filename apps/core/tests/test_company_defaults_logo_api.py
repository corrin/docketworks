"""The logo endpoints exist so PDFs can carry the letterhead: the PO PDF service
hard-fails without a wide logo, and PATCH deliberately excludes ImageFields."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from django.test import Client, override_settings
from PIL import Image

from apps.core.models import CompanyDefaults

pytestmark = pytest.mark.django_db

URL = "/api/company-defaults/logo/{field}/"


@pytest.fixture(autouse=True)
def _media_root(tmp_path: Path) -> Iterator[Path]:
    """Sandbox the on-disk logo writes per test (no repo-wide MEDIA_ROOT precedent)."""
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        yield tmp_path


def _png(width: int = 100, height: int = 100) -> BytesIO:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    buffer.seek(0)
    buffer.name = "logo.png"
    return buffer


def test_upload_requires_superuser(api: Client) -> None:
    response = api.post(URL.format(field="logo"), {"file": _png()})
    assert response.status_code == 403


def test_upload_sets_the_logo_and_returns_its_url(superuser_api: Client) -> None:
    response = superuser_api.post(URL.format(field="logo"), {"file": _png()})
    assert response.status_code == 200
    assert response.json()["logo_url"] is not None
    assert CompanyDefaults.get_solo().logo


def test_upload_rejects_an_unknown_field(superuser_api: Client) -> None:
    response = superuser_api.post(URL.format(field="wage_rate"), {"file": _png()})
    assert response.status_code == 422


def test_upload_rejects_a_disallowed_extension(superuser_api: Client) -> None:
    bad = BytesIO(b"not an image")
    bad.name = "logo.exe"
    response = superuser_api.post(URL.format(field="logo"), {"file": bad})
    assert response.status_code == 400


def test_upload_rejects_an_oversized_file(superuser_api: Client) -> None:
    big = BytesIO(b"0" * (5 * 1024 * 1024 + 1))
    big.name = "logo.png"
    response = superuser_api.post(URL.format(field="logo"), {"file": big})
    assert response.status_code == 400


def test_delete_clears_the_logo(superuser_api: Client) -> None:
    superuser_api.post(URL.format(field="logo"), {"file": _png()})
    response = superuser_api.delete(URL.format(field="logo"))
    assert response.status_code == 200
    assert response.json()["logo_url"] is None
    assert not CompanyDefaults.get_solo().logo
