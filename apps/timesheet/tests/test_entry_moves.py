"""Moving a timesheet entry to another job, through the entry endpoint.

The office moves anyone's entry and a worker his own by PATCHing ``job_id``;
workshop_timesheet_service.update_entry retargets the line, reprices it on the
destination's rates and applies move_time_line's billing rules.
"""

from collections.abc import Callable, Iterable
from decimal import Decimal
from uuid import UUID

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.errors import AccessDeniedError, ConflictError
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet, lock_costing_jobs
from apps.timesheet.models import TimesheetEvent
from apps.timesheet.services import workshop_timesheet_service
from apps.timesheet.tests.conftest import authenticated_client
from apps.timesheet.tests.test_workshop_timesheet_api import URL, _create, _entry_id

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.timesheet.tests.urls"),
]


def _office_enters(office_staff: Staff, job: Job, worker: Staff, **overrides: object) -> str:
    """The office enters an hour of the worker's time on ``job``; return its id."""
    entry = _create(
        authenticated_client(office_staff), job, staff_id=str(worker.id), hours="1.00", **overrides
    )
    return _entry_id(entry)


def _move(client: Client, entry_id: str, destination: Job) -> CostLine:
    """PATCH the entry onto ``destination``; return the stored line."""
    response = client.patch(
        URL,
        data={"entry_id": entry_id, "job_id": str(destination.id)},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return CostLine.objects.get(id=entry_id)


def _actual_hours(job: Job) -> float:
    return float(CostSet.objects.get(job=job, kind="actual").summary["hours"])


class TestMove:
    def test_a_move_retargets_reprices_and_updates_both_jobs(
        self, office_staff: Staff, job: Job, company: Company, worker: Staff
    ) -> None:
        """Guards update_entry's move branch: both summaries, latest_actual and the event."""
        destination = make_job(company, office_staff, name="Destination")
        destination.labour_rates.update(charge_out_rate=Decimal("200.00"))
        entry_id = _office_enters(office_staff, job, worker)
        assert _actual_hours(job) == 1.0

        line = _move(authenticated_client(office_staff), entry_id, destination)

        assert (line.unit_cost, line.unit_rev) == (Decimal("48.00"), Decimal("200.00"))
        assert line.cost_set.job_id == destination.id
        assert _actual_hours(job) == 0.0
        assert _actual_hours(destination) == 1.0
        destination.refresh_from_db()
        assert destination.latest_actual_id == line.cost_set_id
        event = TimesheetEvent.objects.get(cost_line_id=entry_id, event_type="entry_moved")
        assert event.description.startswith(
            f"Moved from #{job.job_number} to #{destination.job_number}"
        )

    def test_onto_a_shop_job_the_entry_is_unbillable(
        self, office_staff: Staff, job: Job, worker: Staff
    ) -> None:
        """Guards move_time_line's destination rule: shop work cannot be invoiced."""
        shop_company = CompanyDefaults.get_solo().shop_company
        assert shop_company is not None
        shop = make_job(shop_company, office_staff, name="Shop work", status="special")
        entry_id = _office_enters(office_staff, job, worker, bill_rate_multiplier="1.5")

        line = _move(authenticated_client(office_staff), entry_id, shop)

        assert line.meta["is_billable"] is False
        assert line.meta["bill_rate_multiplier"] == 0.0
        assert line.unit_rev == Decimal("0.00")

    def test_onto_a_special_job_the_entry_is_unbillable(
        self, office_staff: Staff, job: Job, company: Company, worker: Staff
    ) -> None:
        """Guards move_time_line's same rule keyed on status: a 'special' job bills nothing."""
        special = make_job(company, office_staff, name="Training", status="special")
        entry_id = _office_enters(office_staff, job, worker)

        line = _move(authenticated_client(office_staff), entry_id, special)

        assert line.meta["is_billable"] is False

    def test_off_a_shop_job_the_bill_rate_is_derived_again(
        self, office_staff: Staff, job: Job, worker: Staff
    ) -> None:
        """Guards move_time_line's source rule: the stored zero was the shop's, not the entry's."""
        shop_company = CompanyDefaults.get_solo().shop_company
        assert shop_company is not None
        shop = make_job(shop_company, office_staff, name="Shop work", status="special")
        job.labour_rates.update(charge_out_rate=Decimal("120.00"))
        entry_id = _office_enters(
            office_staff, shop, worker, is_billable=False, bill_rate_multiplier="0.0"
        )

        line = _move(authenticated_client(office_staff), entry_id, job)

        assert line.meta["is_billable"] is True
        assert line.meta["bill_rate_multiplier"] == 1.0
        assert line.unit_rev == Decimal("120.00")

    def test_a_move_keeps_an_explicit_bill_multiplier(
        self, office_staff: Staff, job: Job, company: Company, worker: Staff
    ) -> None:
        """Owner ruling: a move keeps the multipliers; pick defaults would reset 2.0 to 1.0.

        Guards move_time_line carrying the entry's meta to the destination.
        """
        destination = make_job(company, office_staff, name="Destination")
        destination.labour_rates.update(charge_out_rate=Decimal("100.00"))
        entry_id = _office_enters(office_staff, job, worker, bill_rate_multiplier="2.0")

        line = _move(authenticated_client(office_staff), entry_id, destination)

        assert line.meta["bill_rate_multiplier"] == 2.0
        assert line.unit_rev == Decimal("200.00")

    def test_a_destination_without_the_subtype_rate_is_400(
        self, office_staff: Staff, job: Job, company: Company, worker: Staff
    ) -> None:
        """Guards update_entry's repricing failing early on a job with no rate for the subtype."""
        destination = make_job(company, office_staff, name="Destination")
        destination.labour_rates.all().delete()
        entry_id = _office_enters(office_staff, job, worker)

        response = authenticated_client(office_staff).patch(
            URL,
            data={"entry_id": entry_id, "job_id": str(destination.id)},
            content_type="application/json",
        )

        assert response.status_code == 400, response.content
        assert "has no labour rate" in response.json()["detail"]
        assert CostLine.objects.get(id=entry_id).cost_set.job_id == job.id


class TestMoveRaces:
    """What update_entry reads again once it holds the jobs' locks."""

    def test_the_owner_read_under_the_locks_authorizes_a_move(  # noqa: PLR0913, PLR0917 -- pytest fixtures: the jobs, the people and the patch
        self,
        worker_client: Client,
        job: Job,
        office_staff: Staff,
        worker: Staff,
        other_worker: Staff,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The entry is handed to another person while the move waits for its
        job locks, as a second transaction would.

        Guards workshop_timesheet_service.update_entry's re-read after locking.
        """
        entry_id = _entry_id(_create(worker_client, job))
        assert job.company is not None
        destination = make_job(job.company, office_staff, name="Destination")
        events = list(TimesheetEvent.objects.filter(cost_line_id=entry_id).values())
        summaries = list(CostSet.objects.filter(job__in=[job, destination]).values("id", "summary"))
        _while_locking_jobs(monkeypatch, lambda: _hand_to(entry_id, other_worker))

        with pytest.raises(AccessDeniedError):
            workshop_timesheet_service.update_entry(
                worker, {"entry_id": UUID(entry_id), "job_id": destination.id}
            )

        # Not moved. (The hand-over ran inside the refused transaction, so it
        # rolled back with it; another writer's would have stood.)
        assert CostLine.objects.get(id=entry_id).cost_set.job_id == job.id
        assert list(TimesheetEvent.objects.filter(cost_line_id=entry_id).values()) == events
        assert (
            list(CostSet.objects.filter(job__in=[job, destination]).values("id", "summary"))
            == summaries
        )

    def test_a_source_changed_since_the_first_read_is_refused(
        self,
        job: Job,
        company: Company,
        office_staff: Staff,
        worker: Staff,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An entry moved elsewhere while this move waited for its locks is refused.

        The locks taken were for the job first read; the entry is no longer
        there, so taking another job's lock now could deadlock.
        Guards workshop_timesheet_service.update_entry's check after locking.
        """
        entry_id = _office_enters(office_staff, job, worker)
        elsewhere = make_job(company, office_staff, name="Elsewhere")
        destination = make_job(company, office_staff, name="Destination")
        _while_locking_jobs(monkeypatch, lambda: _move_behind_its_back(entry_id, elsewhere))
        events = list(TimesheetEvent.objects.filter(cost_line_id=entry_id).values())

        with pytest.raises(ConflictError, match="moved to another job"):
            workshop_timesheet_service.update_entry(
                office_staff, {"entry_id": UUID(entry_id), "job_id": destination.id}
            )

        # Not moved to the destination. (The other move ran inside the refused
        # transaction, so it rolled back with it; another writer's would have stood.)
        assert CostLine.objects.get(id=entry_id).cost_set.job_id == job.id
        assert list(TimesheetEvent.objects.filter(cost_line_id=entry_id).values()) == events


def _while_locking_jobs(monkeypatch: pytest.MonkeyPatch, change: Callable[[], None]) -> None:
    """Run ``change`` the first time the entry service locks jobs, as another writer would."""
    real = lock_costing_jobs
    done: list[bool] = []

    def lock_then_change(job_ids: Iterable[UUID]) -> None:
        real(job_ids)
        if not done:
            done.append(True)
            change()

    monkeypatch.setattr(workshop_timesheet_service, "lock_costing_jobs", lock_then_change)


def _hand_to(line_id: str, person: Staff) -> None:
    """Make the entry another person's, behind the service's back."""
    line = CostLine.objects.get(id=line_id)
    CostLine.objects.filter(id=line_id).update(
        staff=person, meta={**line.meta, "staff_id": str(person.id)}
    )


def _move_behind_its_back(line_id: str, destination: Job) -> None:
    """Put the entry on another job, behind the service's back."""
    CostLine.objects.filter(id=line_id).update(
        cost_set=CostSet.objects.get(job=destination, kind="actual")
    )
