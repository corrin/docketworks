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


def test_upload_and_delete_the_wide_logo(superuser_api: Client) -> None:
    """logo_wide takes the same path as logo; exercise it at least once."""
    response = superuser_api.post(URL.format(field="logo_wide"), {"file": _png()})
    assert response.status_code == 200
    assert response.json()["logo_wide_url"] is not None
    assert CompanyDefaults.get_solo().logo_wide

    response = superuser_api.delete(URL.format(field="logo_wide"))
    assert response.status_code == 200
    assert response.json()["logo_wide_url"] is None
    assert not CompanyDefaults.get_solo().logo_wide


def test_upload_rejects_an_unknown_field(superuser_api: Client) -> None:
    response = superuser_api.post(URL.format(field="wage_rate"), {"file": _png()})
    assert response.status_code == 422


def test_upload_rejects_a_disallowed_extension(superuser_api: Client) -> None:
    bad = BytesIO(b"not an image")
    bad.name = "logo.exe"
    response = superuser_api.post(URL.format(field="logo"), {"file": bad})
    assert response.status_code == 400


def test_upload_rejects_svg(superuser_api: Client) -> None:
    """PIL cannot open SVG, and the one consumer (the PO PDF) opens with PIL —
    an allowlisted-but-unopenable format would 400 at upload only to 500 the PDF
    later, so .svg is off the allowlist even though v1's upload accepted it."""
    svg = BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    svg.name = "logo.svg"
    response = superuser_api.post(URL.format(field="logo"), {"file": svg})
    assert response.status_code == 400


def test_upload_rejects_a_mislabeled_non_image(superuser_api: Client) -> None:
    """An allowlisted extension is not proof of content; PDF generation opens
    the stored file with PIL, so a non-image must be caught here, not there."""
    bad = BytesIO(b"not an image")
    bad.name = "logo.png"
    response = superuser_api.post(URL.format(field="logo"), {"file": bad})
    assert response.status_code == 400


def test_upload_rejects_an_empty_file(superuser_api: Client) -> None:
    empty = BytesIO(b"")
    empty.name = "logo.png"
    response = superuser_api.post(URL.format(field="logo"), {"file": empty})
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


def test_delete_leaves_a_non_company_logos_file_on_disk(
    superuser_api: Client, tmp_path: Path
) -> None:
    """The company_logos/ guard in _delete_stored_logo protects a file outside
    it — e.g. a git-tracked seed asset a restored row points at — from being
    unlinked by DELETE. Exercises the guard's protective branch directly: the
    row is pointed at a file under a different directory (never through the
    upload path, which always writes under company_logos/), so this is the one
    test that would fail if the guard were removed."""
    seed_dir = tmp_path / "app_images"
    seed_dir.mkdir()
    seed_file = seed_dir / "docketworks_logo.png"
    seed_file.write_bytes(_png().read())

    instance = CompanyDefaults.get_solo()
    instance.logo.name = "app_images/docketworks_logo.png"
    instance.save(update_fields=["logo"])

    response = superuser_api.delete(URL.format(field="logo"))

    assert response.status_code == 200
    assert response.json()["logo_url"] is None
    assert not CompanyDefaults.get_solo().logo
    assert seed_file.exists()
