"""Shared image-upload validation and guarded deletion.

One validator and one deleter for every ImageField endpoint (company logos,
staff icons). A new upload surface parameterises these — the label for its
error messages, the storage prefix for its delete guard — instead of writing
a sibling.
"""

import os
from pathlib import Path

# Fable: Django's UploadedFile, not ninja's subclass — the helpers need only
# .name/.size/stream, and the wider type lets tests exercise them with
# SimpleUploadedFile while every ninja endpoint still passes its File[...].
from django.core.files.uploadedfile import UploadedFile
from django.db.models.fields.files import FieldFile
from ninja.errors import HttpError
from PIL import Image

# Opus: .svg deliberately excluded even though v1's upload accepted it —
# PIL cannot open SVG, and both consumers (grep Image.open over apps/ finds
# apps/purchasing/services/purchase_order_pdf_service.py and
# apps/job/services/workshop_pdf_service.py) open the stored file with PIL, so
# an allowlisted-but-unopenable format would 400 at upload only to 500 every
# PO/workshop PDF later.
ALLOWED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def delete_stored_image(field_file: FieldFile, *, allowed_prefix: str) -> None:
    """Unlink the stored file, but only under MEDIA_ROOT/``allowed_prefix``.

    Opus: the guard exists so a git-tracked seed asset referenced by a restored
    row is never destroyed (v1 carried the same guard). normpath first: the
    guard exists for names that did NOT come through the upload path (e.g. a
    restored row), so a ``../`` cannot walk out of the prefix directory before
    the parts check runs.
    """
    if not field_file:
        return
    storage_path = Path(os.path.normpath(field_file.name or ""))
    if storage_path.parts[:1] != (allowed_prefix,):
        return
    field_file.delete(save=False)


def validate_image_upload(file: UploadedFile, *, label: str = "Image") -> None:
    """400 unless the upload is a real, allowlisted, size-capped image."""
    suffix = Path(file.name or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise HttpError(400, f"Unsupported file type {suffix or '(none)'}")
    if not file.size:
        raise HttpError(400, f"{label} files cannot be empty")
    if file.size > MAX_IMAGE_BYTES:
        raise HttpError(400, f"{label} files are limited to 5 MB")
    # Opus: content, not just suffix — the PO PDF consumer opens the stored
    # file with PIL and hard-fails (UnidentifiedImageError, a 500) on a mislabeled
    # non-image, so that must be a 400 here instead. verify() raises OSError for
    # both an unrecognised format and a truncated/corrupt one (UnidentifiedImageError
    # is itself an OSError subclass); rewind after, since a failed verify() leaves
    # the stream unusable for the caller's subsequent save.
    # DecompressionBombError is Image.DecompressionBombError, not an OSError
    # subclass — without it a small PNG declaring absurd dimensions raises
    # past this except tuple and 500s instead of 400ing.
    try:
        with Image.open(file) as image:
            image.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise HttpError(400, "Uploaded file is not a valid image") from exc
    finally:
        file.seek(0)
