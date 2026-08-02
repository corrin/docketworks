"""Job-domain filesystem helpers, ported from v1 ``apps/job/helpers.py``.

v1 stored job files under the locally synced Dropbox workflow folder;
v2 keeps the same local-filesystem layout (``Job-<number>/`` per job).
Dropbox-API synchronisation itself is a Phase 5 integration seam.
"""

from pathlib import Path

from django.conf import settings


def get_job_folder_path(job_number: int | str) -> str:
    """Return the absolute filesystem path for a job's folder."""
    return str(Path(settings.DROPBOX_WORKFLOW_FOLDER) / f"Job-{job_number}")
