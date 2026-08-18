"""The one matching rule behind every job picker's search box."""

from typing import TypedDict
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.job.models import Job

# A picker never renders more than a screenful, and the term is what narrows
# the set — an unbounded search would let a two-character term return the whole
# table over the wire.
DEFAULT_SEARCH_LIMIT = 50

# Below this a substring match is not selective enough to be worth a round
# trip: two characters match most of the table. The frontend gates on the same
# number so a short term costs no request at all.
MIN_SEARCH_TERM_LENGTH = 3


class JobOptionData(TypedDict):
    """One job as a picker draws it."""

    id: UUID
    job_number: int
    name: str
    company_name: str | None
    status: str


def job_options(status: str) -> list[JobOptionData]:
    """List one status's jobs, narrowed to what a picker renders.

    Status is required rather than optional: this exists for the admin mapping
    screens, which each bind one fixed kind of job, and an unfiltered call
    would be an unbounded list of the whole table wearing a picker's clothes.
    """
    if status not in dict(Job.JOB_STATUS_CHOICES):
        raise ValueError(f"Unknown job status {status!r}.")

    jobs = Job.objects.filter(status=status).select_related("company").order_by("name")
    return [
        {
            "id": job.id,
            "job_number": job.job_number,
            "name": job.name,
            "company_name": job.company.name if job.company else None,
            "status": job.status,
        }
        for job in jobs
    ]


def search_jobs(
    queryset: QuerySet[Job], term: str, limit: int = DEFAULT_SEARCH_LIMIT
) -> QuerySet[Job]:
    """Narrow a job queryset by a picker's search term.

    Substring over job number, name and company name — deliberately the SAME
    rule the picker applies to its locally held list, so the background results
    and the instant ones agree on what matches. The rejected alternative is
    KanbanService._apply_kanban_search: it is weighted-trigram with a
    Python-side re-rank of every candidate, and Job carries no trigram index,
    so measured against 2,409 jobs it costs 308-2231ms where this costs 6-22ms
    — and its fuzzy hits would appear only in the background half of the list,
    which reads as the picker disagreeing with itself.
    """
    cleaned = term.strip()
    if len(cleaned) < MIN_SEARCH_TERM_LENGTH:
        raise ValueError(f"A job search term needs at least {MIN_SEARCH_TERM_LENGTH} characters.")
    if limit <= 0:
        raise ValueError("A job search limit must be positive.")

    return queryset.filter(
        Q(name__icontains=cleaned)
        | Q(company__name__icontains=cleaned)
        | Q(job_number__icontains=cleaned)
    ).order_by("-job_number")[:limit]
