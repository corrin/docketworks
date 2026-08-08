"""sync_companies: the link / archive / merge decision table.

These run the real pipeline — SDK Contact objects through process_xero_data
and set_company_fields — because the production failure this guards against
(Xero merging two contacts, leaving an ARCHIVED duplicate name) broke exactly
at the seam between those pieces.
"""

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.xero.raw_fields import set_company_fields
from apps.xero.transforms import sync_companies

from .xero_fixtures import make_contact_raw_json, make_xero_contact


@pytest.mark.django_db
class TestSyncCompaniesLinking:
    """Linking Xero contacts to local companies must never duplicate a company."""

    def test_links_unlinked_company_by_name(self) -> None:
        # A pre-Xero company (created locally, no contact id) must be claimed
        # by the matching Xero contact, not shadowed by a new record.
        existing = Company.objects.create(
            name="Steel Supplies Ltd", xero_last_modified=timezone.now()
        )

        result = sync_companies([make_xero_contact("contact-link-1", "Steel Supplies Ltd")])

        assert len(result) == 1
        assert result[0].id == existing.id
        existing.refresh_from_db()
        assert existing.xero_contact_id == "contact-link-1"
        assert Company.objects.filter(name="Steel Supplies Ltd").count() == 1

    def test_creates_company_when_name_unknown(self) -> None:
        result = sync_companies([make_xero_contact("contact-new-9", "Brand New Co")])

        assert len(result) == 1
        company = result[0]
        assert company.name == "Brand New Co"
        assert company.xero_contact_id == "contact-new-9"
        assert not company.xero_archived
        assert company.allow_jobs

    def test_already_linked_contact_updates_in_place(self) -> None:
        # The contact was archived in Xero since the last sync: same DB row,
        # archived flag mirrored — never a second record.
        existing = Company.objects.create(
            name="Linked Ltd",
            xero_contact_id="contact-linked-1",
            xero_last_modified=timezone.now(),
        )

        result = sync_companies(
            [make_xero_contact("contact-linked-1", "Linked Ltd", status="ARCHIVED")]
        )

        assert len(result) == 1
        assert result[0].id == existing.id
        existing.refresh_from_db()
        assert existing.xero_archived


@pytest.mark.django_db
class TestArchivedNameCollisions:
    """The production scenario: Xero merges two contacts — the survivor stays
    ACTIVE, the loser becomes ARCHIVED with the same name. Sync must handle
    both without crashing, but a *live* duplicate name is still a data error.
    """

    ACTIVE_XERO_ID = "9568adbc-aaaa-bbbb-cccc-000000000001"
    ARCHIVED_XERO_ID = "17aa5e1e-aaaa-bbbb-cccc-000000000002"
    COMPANY_NAME = "Powder Coating Group NZ Limited"

    @pytest.fixture(autouse=True)
    def _existing_client(self) -> None:
        self.existing_client = Company.objects.create(
            name=self.COMPANY_NAME,
            xero_contact_id=self.ACTIVE_XERO_ID,
            xero_last_modified=timezone.now(),
        )

    def test_archived_contact_creates_separate_record(self) -> None:
        archived_contact = make_xero_contact(
            self.ARCHIVED_XERO_ID,
            self.COMPANY_NAME,
            status="ARCHIVED",
            merged_to=self.ACTIVE_XERO_ID,
        )

        result = sync_companies([archived_contact])

        assert len(result) == 1
        new_client = result[0]
        assert new_client.id != self.existing_client.id
        assert new_client.xero_contact_id == self.ARCHIVED_XERO_ID
        assert new_client.xero_archived
        assert new_client.xero_merged_into_id == self.ACTIVE_XERO_ID

        # Original company keeps its link and stays active.
        self.existing_client.refresh_from_db()
        assert self.existing_client.xero_contact_id == self.ACTIVE_XERO_ID
        assert not self.existing_client.xero_archived

    def test_active_contact_name_collision_raises(self) -> None:
        # Two live contacts with one name is a data conflict a human must
        # resolve; the error must name the already-linked Xero id (ADR 0038).
        conflicting = make_xero_contact(
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", self.COMPANY_NAME, status="ACTIVE"
        )

        with pytest.raises(ValueError, match=self.ACTIVE_XERO_ID):
            sync_companies([conflicting])


@pytest.mark.django_db
class TestMergeResolution:
    """A merged loser's records must move to the winner — or wait, visibly,
    until the winner has synced. Losing this reassignment strands jobs and
    invoices on a tombstone company.
    """

    def test_merge_resolves_and_reassigns_when_winner_synced(self) -> None:
        winner = Company.objects.create(
            name="Merge Winner Ltd",
            xero_contact_id="contact-winner-1",
            xero_last_modified=timezone.now(),
        )
        loser_contact = make_xero_contact(
            "contact-loser-1",
            "Merge Loser Ltd",
            status="ARCHIVED",
            merged_to="contact-winner-1",
        )

        with patch(
            "apps.company.services.company_merge_service.reassign_company_fk_records"
        ) as reassign:
            result = sync_companies([loser_contact])

        loser = result[0]
        loser.refresh_from_db()
        assert loser.merged_into_id == winner.id
        assert not loser.allow_jobs
        assert reassign.call_count == 1
        source, destination, staff = reassign.call_args[0]
        assert source.id == loser.id
        assert destination.id == winner.id
        assert staff == Staff.get_automation_user()

    def test_deferred_merge_retries_next_sync_when_winner_unsynced(self) -> None:
        loser_contact = make_xero_contact(
            "contact-loser-2",
            "Deferred Loser Ltd",
            status="ARCHIVED",
            merged_to="contact-winner-2",
        )

        with patch(
            "apps.company.services.company_merge_service.reassign_company_fk_records"
        ) as reassign:
            result = sync_companies([loser_contact])

        # Winner not synced yet: the merge is deferred, not dropped — the
        # xero_merged_into_id marker stays so the next sync can resolve it.
        loser = result[0]
        loser.refresh_from_db()
        assert loser.merged_into_id is None
        assert loser.xero_merged_into_id == "contact-winner-2"
        assert reassign.call_count == 0

        winner = Company.objects.create(
            name="Deferred Winner Ltd",
            xero_contact_id="contact-winner-2",
            xero_last_modified=timezone.now(),
        )

        with patch(
            "apps.company.services.company_merge_service.reassign_company_fk_records"
        ) as reassign:
            sync_companies([loser_contact])

        loser.refresh_from_db()
        assert loser.merged_into_id == winner.id
        assert reassign.call_count == 1


@pytest.mark.django_db
class TestAllowJobsTransitions:
    """xero_archived mirrors Xero both ways; allow_jobs follows only on the
    archive transitions, so an admin's manual block survives routine syncs.
    """

    def test_archive_then_unarchive_roundtrip_restores_allow_jobs(self) -> None:
        company = Company.objects.create(
            name="Archive Roundtrip Ltd",
            xero_last_modified=timezone.now(),
            allow_jobs=True,
            raw_json=make_contact_raw_json(
                "contact-t1", "Archive Roundtrip Ltd", status="ARCHIVED"
            ),
        )

        set_company_fields(company)
        assert company.xero_archived
        assert not company.allow_jobs

        company.raw_json = make_contact_raw_json(
            "contact-t1", "Archive Roundtrip Ltd", status="ACTIVE"
        )
        set_company_fields(company)

        assert not company.xero_archived
        assert company.allow_jobs

    def test_batch_sync_unarchive_restores_allow_jobs(self) -> None:
        """The hourly path fires the ADR 0034 restore (dead code in v1).

        v1 pre-wrote xero_archived in sync_companies before calling
        set_company_fields, so the was_archived transition never saw the
        change on the batch path — un-archiving in Xero only restored
        allow_jobs via the webhook. Pin the batch path (ledgered fix).
        """
        company = Company.objects.create(
            name="Batch Unarchive Ltd",
            xero_last_modified=timezone.now(),
            xero_contact_id="contact-batch-1",
            xero_archived=True,
            allow_jobs=False,
            raw_json=make_contact_raw_json("contact-batch-1", "Batch Unarchive Ltd"),
        )

        sync_companies([make_xero_contact("contact-batch-1", "Batch Unarchive Ltd")])

        company.refresh_from_db()
        assert not company.xero_archived
        assert company.allow_jobs

    def test_manual_block_survives_steady_state_sync(self) -> None:
        # No transition, no touch: an admin's allow_jobs=False on an active
        # company must not be flipped back by a routine sync.
        company = Company.objects.create(
            name="Blocked But Active Ltd",
            xero_last_modified=timezone.now(),
            allow_jobs=False,
            xero_archived=False,
            raw_json=make_contact_raw_json("contact-t2", "Blocked But Active Ltd"),
        )

        set_company_fields(company)

        assert not company.xero_archived
        assert not company.allow_jobs

    def test_unarchived_merged_tombstone_stays_blocked(self) -> None:
        # A merged loser's jobs belong to the winner; un-archiving its Xero
        # contact must not re-open it for jobs.
        winner = Company.objects.create(name="Tombstone Winner", xero_last_modified=timezone.now())
        loser = Company.objects.create(
            name="Tombstone Loser",
            xero_last_modified=timezone.now(),
            allow_jobs=False,
            xero_archived=True,
            merged_into=winner,
            raw_json=make_contact_raw_json("contact-t3", "Tombstone Loser", status="ACTIVE"),
        )

        set_company_fields(loser)

        assert not loser.xero_archived
        assert not loser.allow_jobs
