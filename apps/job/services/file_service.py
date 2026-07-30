import logging
import mimetypes
import os

from pdf2image import convert_from_path
from PIL import Image

from apps.job.helpers import get_job_folder_path

logger = logging.getLogger(__name__)


def get_thumbnail_folder(job_number):
    """Get the thumbnails subfolder path for a job."""
    job_folder = get_job_folder_path(job_number)
    thumb_folder = os.path.join(job_folder, "thumbnails")
    os.makedirs(thumb_folder, exist_ok=True)
    return thumb_folder


def create_thumbnail(source_path, thumb_path, size=(400, 400)):
    """
    Try to create a thumbnail if possible. Returns True if successful.
    Fails early if the file type isn't supported or thumbnail fails.
    """

    try:
        if source_path.lower().endswith(".pdf"):
            pages = convert_from_path(source_path, first_page=1, last_page=1)
            if pages:
                first_page = pages[0]
                first_page.thumbnail(size)
                first_page.save(thumb_path, "JPEG", quality=85)
                return True

        # Try PIL for everything else
        with Image.open(source_path) as img:
            if img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", img.size, "white")
                background.paste(img, mask=img.split()[-1])
                img = background
            img.thumbnail(size)
            img.save(thumb_path, "JPEG", quality=85)
            return True

    except Exception as e:
        logger.debug(f"Thumbnail creation failed for {source_path}: {e}")
        raise e


def sync_job_folder(job):
    """Scan job folder and manage JobFile records and thumbnails."""
    from apps.job.models import JobFile

    job_folder = get_job_folder_path(job.job_number)
    if not os.path.exists(job_folder):
        return

    thumb_folder = get_thumbnail_folder(job.job_number)
    existing_files = {jf.filename: jf for jf in job.files.all()}
    found_files = set(os.listdir(job_folder))

    # Don't include thumbnail folder in file scanning
    if "thumbnails" in found_files:
        found_files.remove("thumbnails")

    # Mark missing files as deleted
    for filename, job_file in existing_files.items():
        if filename not in found_files and job_file.status == "active":
            job_file.status = "deleted"
            job_file.save()

    # Process new files
    for filename in found_files:
        filepath = os.path.join(job_folder, filename)
        if os.path.isfile(filepath):
            # Create or update JobFile record
            if filename not in existing_files:
                mime_type, _ = mimetypes.guess_type(filename)
                relative_path = os.path.join(f"Job-{job.job_number}", filename)
                JobFile.objects.create(
                    job=job,
                    filename=filename,
                    file_path=relative_path,
                    mime_type=mime_type or None,
                )

            # Generate thumbnail if needed
            thumb_path = os.path.join(thumb_folder, f"{filename}.thumb.jpg")
            if not os.path.exists(thumb_path):
                create_thumbnail(filepath, thumb_path)
