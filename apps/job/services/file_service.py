"""Job file storage helpers, ported from v1 ``apps/job/services/file_service.py``.

Thumbnails live in a ``thumbnails/`` subfolder of the job folder;
``sync_job_folder`` reconciles JobFile rows with what is on disk.
"""

import logging
import mimetypes
import os
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from pdf2image import convert_from_path
from PIL import Image

from apps.job.helpers import get_job_folder_path

if TYPE_CHECKING:
    from apps.job.models import Job, JobFile

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = (400, 400)


def get_thumbnail_folder(job_number: int | str) -> str:
    """Return (and create) the thumbnails subfolder path for a job."""
    thumb_folder = Path(get_job_folder_path(job_number)) / "thumbnails"
    thumb_folder.mkdir(parents=True, exist_ok=True)
    return str(thumb_folder)


def create_thumbnail(
    source_path: str, thumb_path: str, size: tuple[int, int] = THUMBNAIL_SIZE
) -> None:
    """Create a JPEG thumbnail for an image or PDF source file.

    Fails loudly (as v1) when the file type is unsupported or conversion
    fails — callers persist the error with context.
    """
    if source_path.lower().endswith(".pdf"):
        pages = convert_from_path(source_path, first_page=1, last_page=1)
        if pages:
            first_page = pages[0]
            first_page.thumbnail(size)
            first_page.save(thumb_path, "JPEG", quality=85)
            return

    # Pillow handles everything else
    with Image.open(source_path) as img:
        converted: Image.Image = img
        if img.mode in ("RGBA", "LA"):
            background = Image.new("RGB", img.size, "white")
            background.paste(img, mask=img.split()[-1])
            converted = background
        converted.thumbnail(size)
        converted.save(thumb_path, "JPEG", quality=85)


def sync_job_folder(job: "Job") -> None:
    """Scan a job's folder and reconcile JobFile records and thumbnails."""
    # JobFile's thumbnail_path property imports this module, so the model
    # import must stay function-local (v1 had the same inversion).
    from apps.job.models import JobFile  # noqa: PLC0415 -- model->service import cycle (v1 parity)

    job_folder = Path(get_job_folder_path(job.job_number))
    if not job_folder.exists():
        return

    thumb_folder = Path(get_thumbnail_folder(job.job_number))
    existing_files = {jf.filename: jf for jf in job.files.all()}
    found_files = {entry.name for entry in job_folder.iterdir()}

    # Don't include the thumbnail folder in file scanning
    found_files.discard("thumbnails")

    # Mark missing files as deleted
    for filename, job_file in existing_files.items():
        if filename not in found_files and job_file.status == "active":
            job_file.status = "deleted"
            job_file.save()

    # Process new files
    for filename in found_files:
        filepath = job_folder / filename
        if not filepath.is_file():
            continue

        if filename not in existing_files:
            mime_type, _ = mimetypes.guess_type(filename)
            JobFile.objects.create(
                job=job,
                filename=filename,
                file_path=f"Job-{job.job_number}/{filename}",
                mime_type=mime_type or None,
            )

        # Generate thumbnail if needed
        thumb_path = thumb_folder / f"{filename}.thumb.jpg"
        if not thumb_path.exists():
            create_thumbnail(str(filepath), str(thumb_path))


def workflow_root() -> Path:
    """Return the resolved workflow-folder root, failing early when unset."""
    root = settings.DROPBOX_WORKFLOW_FOLDER
    if not root:
        raise ValueError("DROPBOX_WORKFLOW_FOLDER is not configured")
    return Path(root).resolve()


def job_file_full_path(job_file: "JobFile") -> Path:
    """Resolve a JobFile's on-disk path, refusing paths escaping the root.

    Mirrors the crm recording-download hardening: ``file_path`` is
    DB-controlled, but any row that resolves outside the workflow folder is
    data corruption and must not be served.
    """
    root = workflow_root()
    full_path = (root / job_file.file_path).resolve()
    if not full_path.is_relative_to(root):
        raise ValueError("job file path escapes the workflow folder")
    return full_path


def save_uploaded_job_file(
    job: "Job", file_obj: UploadedFile, print_on_jobsheet: bool
) -> "JobFile":
    """Save an uploaded file into the job folder and upsert its JobFile row.

    Re-uploading a filename overwrites the file and reactivates the row
    (v1 update_or_create semantics). Raises ValueError for empty uploads.
    """
    from apps.job.models import JobFile  # noqa: PLC0415 -- model->service import cycle (v1 parity)

    if not file_obj.name:
        raise ValueError("Uploaded file has no filename")

    # Fail early if empty
    if file_obj.size == 0:
        raise ValueError(f"Uploaded file {file_obj.name} is empty (0 bytes)")

    job_folder = Path(get_job_folder_path(job.job_number))
    job_folder.mkdir(parents=True, exist_ok=True)
    safe_filename = Path(file_obj.name).name
    file_path = job_folder / safe_filename

    with file_path.open("wb") as destination:
        for chunk in file_obj.chunks():
            destination.write(chunk)

    job_file, created = JobFile.objects.update_or_create(
        job=job,
        filename=safe_filename,
        defaults={
            "file_path": f"Job-{job.job_number}/{safe_filename}",
            "mime_type": file_obj.content_type,
            "print_on_jobsheet": print_on_jobsheet,
            "status": "active",
        },
    )

    logger.info(
        "%s file: %s for job %s",
        "Created" if created else "Updated",
        file_obj.name,
        job.job_number,
    )
    return job_file


def update_job_file(
    job_file: "JobFile",
    *,
    print_on_jobsheet: bool | None = None,
    filename: str | None = None,
) -> "JobFile":
    """Update job-file metadata; a filename change renames the file on disk.

    Raises ValueError for the v1 client-error cases (empty filename, missing
    original, or a rename that would overwrite another file).
    """
    if print_on_jobsheet is not None:
        job_file.print_on_jobsheet = print_on_jobsheet

    if filename is not None:
        if not filename:
            raise ValueError("Filename cannot be empty")

        old_path = job_file_full_path(job_file)
        new_path = old_path.parent / filename

        if not old_path.exists():
            raise ValueError("Original file does not exist; cannot rename.")

        # Prevent overwriting an existing file with a different path
        if new_path.exists() and os.path.normcase(str(new_path)) != os.path.normcase(str(old_path)):
            raise ValueError("A file with the requested new filename already exists.")

        old_path.rename(new_path)

        # Update database only after successful rename
        job_file.filename = filename
        job_file.file_path = str(new_path.relative_to(workflow_root()))

    job_file.save()
    return job_file


def delete_job_file(job_file: "JobFile") -> None:
    """Delete a job file from disk (with its thumbnail) and its DB row."""
    full_path = job_file_full_path(job_file)
    if full_path.exists():
        full_path.unlink()

    thumbnail_path = job_file.thumbnail_path
    if thumbnail_path and Path(thumbnail_path).exists():
        Path(thumbnail_path).unlink()

    job_file.delete()
