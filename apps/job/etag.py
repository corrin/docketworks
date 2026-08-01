"""ETag utilities for the Job aggregate."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.workflow.etag import generate_updated_at_etag, updated_at_etag_value

if TYPE_CHECKING:
    from apps.job.models import Job


def current_job_etag_value(job: Job) -> str:
    """Return the full-precision validator value for a Job."""
    return updated_at_etag_value("job", job.id, job.updated_at)


def generate_job_etag(job: Job) -> str:
    """Return the strong HTTP ETag for a Job."""
    return generate_updated_at_etag("job", job.id, job.updated_at)
