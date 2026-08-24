"""The shared image-upload helpers: one validator and one guarded deleter for
every ImageField endpoint (company logos, staff icons), so a new upload surface
reuses the seam instead of writing a sibling."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.fields.files import FieldFile
from django.test import override_settings
from ninja.errors import HttpError
from PIL import Image

from apps.core.models import CompanyDefaults
from apps.core.uploads import delete_stored_image, validate_image_upload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_root(tmp_path: Path) -> Iterator[Path]:
    """Sandbox the on-disk writes per test (no repo-wide MEDIA_ROOT precedent)."""
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        yield tmp_path


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (10, 10), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="image/png")


def _field_file_named(name: str) -> FieldFile:
    """A FieldFile pointing at ``name`` without going through an upload."""
    instance = CompanyDefaults.get_solo()
    instance.logo.name = name
    return instance.logo


class TestDeleteStoredImage:
    def test_unlinks_a_file_under_the_allowed_prefix(self, tmp_path: Path) -> None:
        stored_dir = tmp_path / "staff_icons"
        stored_dir.mkdir()
        stored = stored_dir / "mugshot.png"
        stored.write_bytes(_png_bytes())

        delete_stored_image(
            _field_file_named("staff_icons/mugshot.png"), allowed_prefix="staff_icons"
        )

        assert not stored.exists()

    def test_leaves_a_file_outside_the_allowed_prefix(self, tmp_path: Path) -> None:
        seed_dir = tmp_path / "app_images"
        seed_dir.mkdir()
        seed = seed_dir / "seed.png"
        seed.write_bytes(_png_bytes())

        delete_stored_image(_field_file_named("app_images/seed.png"), allowed_prefix="staff_icons")

        assert seed.exists()

    def test_leaves_a_traversal_name_that_normpaths_outside_the_prefix(
        self, tmp_path: Path
    ) -> None:
        seed_dir = tmp_path / "app_images"
        seed_dir.mkdir()
        seed = seed_dir / "seed.png"
        seed.write_bytes(_png_bytes())

        delete_stored_image(
            _field_file_named("staff_icons/../app_images/seed.png"), allowed_prefix="staff_icons"
        )

        assert seed.exists()

    def test_tolerates_an_unset_field_file(self) -> None:
        delete_stored_image(_field_file_named(""), allowed_prefix="staff_icons")


class TestValidateImageUpload:
    def test_accepts_a_real_image_and_rewinds_it(self) -> None:
        file = _upload("mugshot.png", _png_bytes())
        validate_image_upload(file)
        assert file.tell() == 0

    def test_the_label_names_the_upload_kind_in_messages(self) -> None:
        big = _upload("mugshot.png", b"0" * (5 * 1024 * 1024 + 1))
        with pytest.raises(HttpError) as excinfo:
            validate_image_upload(big, label="Profile picture")
        assert "Profile picture files are limited to 5 MB" in str(excinfo.value)

    def test_rejects_a_mislabeled_non_image(self) -> None:
        bad = _upload("mugshot.png", b"not an image")
        with pytest.raises(HttpError):
            validate_image_upload(bad)
