"""Per-dataset version strings, so the SPA can refetch only what changed.

The frontend polls this on every tab-focus and compares each string against the
one it cached; a difference invalidates that dataset's store. Deliberately a
separate channel from ``/api/build-id/``: that one fires on a code deploy, this
one on data changing underneath a tab that stayed open.

Lives in ``apps.operations`` rather than beside build-id in ``apps.core``
because every provider reads a domain model, and core sits BELOW the domain
apps in the layer contract. Reaching them through the app registry would work
and would be wrong — that seam exists for core-to-integration, and using it to
dodge the layering would hide a real dependency. Operations is a domain app, so
it may import its siblings honestly.

Each version string only has to CHANGE when the data changes; its content is
opaque to the client. Max(updated_at) alone would miss a deletion, so every
provider pairs the timestamp with a row count.
"""

from collections.abc import Callable

from django.db.models import Count, Max, Model
from django.http import HttpRequest, HttpResponse
from ninja import Router, Schema

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.core.auth import CookieJWTAuth
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.job.kanban_version import KanbanDatasetVersion
from apps.job.models import Job
from apps.purchasing.models import Stock

router = Router(tags=["operations"])
auth = CookieJWTAuth()


class DataVersions(Schema):
    """One opaque version string per dataset the SPA caches."""

    stock: str
    kanban: str
    kanban_related: str
    crm_calls: str


def _model_version(model: type[Model], updated_field: str) -> str:
    """Build a string that changes whenever the table's contents change.

    The count is not decoration: a row deleted after the newest surviving row
    leaves Max(updated_at) untouched, so a timestamp alone would tell a client
    its cache was still good.
    """
    # _default_manager rather than .objects: `objects` is declared on each
    # concrete model, not on Model, so a generic helper cannot see it.
    aggregate = model._default_manager.aggregate(latest=Max(updated_field), rows=Count("id"))
    latest = aggregate["latest"].timestamp() if aggregate["latest"] is not None else 0.0
    return f"{latest}-{aggregate['rows']}"


def _stock_version() -> str:
    return _model_version(Stock, "updated_at")


def _kanban_version() -> str:
    """Job rows, encoded the way incremental Kanban reconciliation reads them."""
    aggregate = Job.objects.aggregate(
        updated=Max("updated_at"), created=Max("created_at"), count=Count("id")
    )
    return KanbanDatasetVersion.from_values(
        updated_at=aggregate["updated"],
        created_at=aggregate["created"],
        count=aggregate["count"],
    ).encode()


def _kanban_related_version() -> str:
    """Track the display inputs a Kanban card reads beyond the Job row itself.

    Deliberately conservative: a company rename changes no Job row, but it does
    change what the card shows, so it has to invalidate the dataset.
    """
    return "|".join(
        [
            _model_version(Company, "django_updated_at"),
            _model_version(CompanyPersonLink, "updated_at"),
            _model_version(Person, "updated_at"),
            _model_version(Staff, "updated_at"),
        ]
    )


def _crm_calls_version() -> str:
    """Call rows, recording availability, and the labels the call table renders."""
    return "|".join(
        [
            _model_version(PhoneCallRecord, "updated_at"),
            _model_version(PhoneCallRecording, "updated_at"),
            _model_version(Company, "django_updated_at"),
            _model_version(CompanyPersonLink, "updated_at"),
            _model_version(Person, "updated_at"),
            _model_version(Job, "updated_at"),
        ]
    )


#: Adding a dataset means a provider here and a field on DataVersions; the two
#: are checked against each other by test_data_versions.py rather than by
#: anything at runtime.
DATASET_VERSION_PROVIDERS: dict[str, Callable[[], str]] = {
    "stock": _stock_version,
    "kanban": _kanban_version,
    "kanban_related": _kanban_related_version,
    "crm_calls": _crm_calls_version,
}


@router.get(
    "/data-versions/",
    auth=auth,
    operation_id="data_versions_retrieve",
    response=DataVersions,
    summary="Per-dataset version strings for cache invalidation",
    tags=["operations"],
)
def data_versions_retrieve(request: HttpRequest, response: HttpResponse) -> dict[str, str]:
    """Return every dataset's current version string.

    ``no-store`` because a cached copy of this response defeats its only
    purpose: the client would keep comparing against the version it already had.
    """
    response["Cache-Control"] = "no-store"
    return {key: provider() for key, provider in DATASET_VERSION_PROVIDERS.items()}
