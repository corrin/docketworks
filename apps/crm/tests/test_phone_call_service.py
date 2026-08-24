"""Service-level tests for phone-provider calls.

Contact ownership invariants are covered in the company app, while malformed
job-link behavior is covered at the observable API boundary.
"""

import hashlib
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pytest
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from apps.company.models import ContactMethod
from apps.core.models import AppError, IntegrationSettings
from apps.core.test_data import silent_wav
from apps.crm.migrations import _0003_helpers as backfill
from apps.crm.models import PhoneCallRecord, PhoneCallRecording, PhoneEndpoint
from apps.crm.services.phone_call_service import (
    PhoneMatcher,
    PhoneProviderCallPage,
    PhoneProviderPortalClient,
    _positive_int,
    assign_phone_number,
    delete_archived_provider_recordings,
    delete_local_recording,
    measure_audio_duration_ms,
    normalize_phone,
    rematch_calls_for_numbers,
    store_recording_bytes,
    sync_call_history,
    upsert_call_record,
)
from apps.crm.tests.helpers import (
    link_person,
    make_call,
    make_company,
    make_job,
    make_office_staff,
    make_recording,
)


class TestPhoneProviderPortalClient:
    """Provider call pagination can return intermittent empty pages. Stopping
    at the first empty page would silently miss billable customer calls later
    in the provider export.
    """

    def test_iter_call_pages_walks_pages_until_two_empty_pages(self) -> None:
        client = PhoneProviderPortalClient.__new__(PhoneProviderPortalClient)
        pages: dict[int, list[dict[str, str]]] = {
            1: [{"id": "call-1"}],
            2: [{"id": "call-2"}],
            3: [],
            4: [{"id": "call-4"}],
            5: [],
            6: [],
        }

        def fake_fetch(*, page: int, **_kwargs: date | None) -> list[dict[str, str]]:
            return pages[page]

        with mock.patch.object(client, "fetch_cdr_page", side_effect=fake_fetch):
            results = list(client.iter_call_pages(page_delay=0))

        assert results == [
            PhoneProviderCallPage(page=1, calls=[{"id": "call-1"}]),
            PhoneProviderCallPage(page=2, calls=[{"id": "call-2"}]),
            PhoneProviderCallPage(page=4, calls=[{"id": "call-4"}]),
        ]


class TestNormalizePhone:
    """The same NZ number appears in local, international, and spacing-heavy
    formats across CRM and call-provider exports. If these do not normalize to
    one value, calls stop attaching to the right customer.
    """

    def test_normalize_phone_matches_nz_variants_by_local_tail(self) -> None:
        assert normalize_phone("+64 9 636 5131") == "+6496365131"
        assert normalize_phone("6496365131") == "+6496365131"
        assert normalize_phone("09 636 5131") == "+6496365131"
        assert normalize_phone("027 530 3238") == "+64275303238"

    def test_no_number_normalizes_to_none_not_blank(self) -> None:
        # A withheld caller arrives from the provider as origin "" — the call
        # row's number columns are nullable with not-blank constraints, so
        # "no number" must be NULL, never "".
        assert normalize_phone("") is None
        assert normalize_phone(None) is None
        assert normalize_phone("Anonymous") is None


class TestCallDurationCoercion:
    """`duration_seconds` is coerced from an external provider payload.

    The documented contract is "unparseable duration is zero". It was false for
    non-finite floats: they passed the isinstance gate, and int(float("inf"))
    raises OverflowError, not ValueError, so a payload carrying Infinity took
    down the whole sync rather than costing one call a duration.
    """

    def test_non_finite_durations_are_zero_not_a_crash(self) -> None:
        assert _positive_int(float("inf")) == 0
        assert _positive_int(float("-inf")) == 0
        assert _positive_int(float("nan")) == 0

    def test_ordinary_durations_still_coerce(self) -> None:
        assert _positive_int(42) == 42
        assert _positive_int("42") == 42
        assert _positive_int(42.7) == 42
        assert _positive_int(-5) == 0
        assert _positive_int("not-a-number") == 0
        assert _positive_int(None) == 0


@pytest.mark.django_db
class TestPhoneMatcher:
    """Call records drive customer history. The matcher should attach calls
    when ownership is unambiguous, and refuse ambiguous matches so one
    company's calls are not shown under another company or person.
    """

    def test_assign_phone_number_creates_primary_contact_method_and_matches_client(
        self,
    ) -> None:
        company = make_company("Acme Ltd")

        method = assign_phone_number(
            phone_number="09 636 5131",
            company_id=company.id,
            label="Reception",
        )
        matched_company, matched_contact = PhoneMatcher().match_customer(
            "+6496365131",
            "+6490000000",
        )

        assert method.normalized_value == "+6496365131"
        assert method.is_primary
        assert matched_company == company
        assert matched_contact is None

    def test_assign_number_allowed_on_contact_of_owning_client(self) -> None:
        """Assigning a company's number to one of its own contacts is not a conflict."""
        company = make_company("Acme Ltd")
        link = link_person(company, "Jane Smith")
        assign_phone_number(phone_number="021 555 900", company_id=company.id)

        method = assign_phone_number(
            phone_number="021 555 900",
            company_id=company.id,
            person_id=link.person_id,
        )

        assert method.person_id == link.person_id

    def test_assign_number_rejected_for_different_client(self) -> None:
        """A number owned by one company cannot be assigned to a different company."""
        owner = make_company("Acme Ltd")
        other = make_company("Beta Ltd")
        assign_phone_number(phone_number="021 555 901", company_id=owner.id)

        with pytest.raises(ValueError, match="already belongs"):
            assign_phone_number(phone_number="021 555 901", company_id=other.id)

    def test_single_contact_method_matches_contact(self) -> None:
        company = make_company("Acme Ltd")
        link = link_person(company, "Jane Smith")
        ContactMethod.objects.create(
            person=link.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
            is_primary=True,
        )

        matched_company, matched_contact = PhoneMatcher().match_customer(
            "+6490000000",
            "+6421555123",
        )

        assert matched_company == company
        assert matched_contact == link.person

    def test_same_number_across_contacts_on_one_client_is_allowed(self) -> None:
        """Two contacts of one company resolve to a single effective company owner."""
        company = make_company("Acme Ltd")
        jane = link_person(company, "Jane Smith")
        john = link_person(company, "John Smith")
        ContactMethod.objects.create(
            person=jane.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        on_john = ContactMethod.objects.create(
            person=john.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )

        matched_company, matched_contact = PhoneMatcher().match_customer("+6421555123")

        assert on_john.pk is not None
        assert matched_company == company
        assert matched_contact is None

    def test_unknown_call_with_two_parties_has_no_assignable_external_number(self) -> None:
        classification = PhoneMatcher().classify("021 555 123", "021 555 456")

        assert classification.direction == PhoneCallRecord.Direction.UNKNOWN
        assert classification.external_number is None

    def test_unknown_call_with_one_party_keeps_assignable_external_number(self) -> None:
        classification = PhoneMatcher().classify("021 555 123", "")

        assert classification.direction == PhoneCallRecord.Direction.UNKNOWN
        assert classification.external_number == "+6421555123"

    def test_rematch_clears_job_link_when_number_moves_to_other_client(self) -> None:
        first = make_company("Acme Ltd")
        second = make_company("Beta Ltd")
        staff = make_office_staff("rematch-link@example.com")
        job = make_job(first, "Linked Job", staff)
        ContactMethod.objects.create(
            company=second,
            method_type=ContactMethod.MethodType.PHONE,
            value="+6421555123",
        )
        call_datetime = timezone.now()
        call = make_call(
            "rematch-linked",
            company=first,
            origin="021 555 123",
            destination="+6490000000",
        )
        call.job = job
        call.job_linked_by = staff
        call.job_linked_at = call_datetime
        call.save(update_fields=["job", "job_linked_by", "job_linked_at"])

        rematch_calls_for_numbers(["+6421555123"])

        call.refresh_from_db()
        assert call.company == second
        assert call.person is None
        assert call.job is None
        assert call.job_linked_by is None
        assert call.job_linked_at is None


@pytest.mark.django_db
class TestProviderRecordingDeletion:
    """Provider recordings may be deleted only after DocketWorks has archived
    them locally and the retention window has passed. Deleting too early loses
    audit evidence; never deleting them grows provider storage.
    """

    @pytest.fixture(autouse=True)
    def provider_settings(self) -> None:
        IntegrationSettings.objects.filter(pk=1).update(
            phone_provider_base_url="https://phone.example.test",
            phone_provider_username="user",
            phone_provider_password="secret",
            phone_provider_account_code="account",
        )

    def test_deletes_only_downloaded_calls_more_than_one_month_old(self) -> None:
        now = timezone.now()
        old_call = make_call("old", call_datetime=now - timedelta(days=32))
        recent_call = make_call("recent", call_datetime=now - timedelta(days=15))
        not_downloaded_call = make_call("not-downloaded", call_datetime=now - timedelta(days=45))
        deleted_call = make_call("deleted", call_datetime=now - timedelta(days=50))

        old_recording = make_recording(old_call, "old", storage_path="old.mp3")
        make_recording(recent_call, "recent", storage_path="recent.mp3")
        make_recording(not_downloaded_call, "not-downloaded", storage_path=None)
        make_recording(
            deleted_call,
            "deleted",
            storage_path="deleted.mp3",
            provider_deleted_at=now,
        )

        with mock.patch(
            "apps.crm.services.phone_call_service.PhoneProviderPortalClient"
        ) as client_class:
            client = client_class.return_value
            result = delete_archived_provider_recordings(limit=100)

        assert result.candidates == 1
        assert result.deleted == 1
        assert result.failed == 0
        client.login.assert_called_once_with()
        client.delete_recording.assert_called_once_with("old")

        old_recording.refresh_from_db()
        assert old_recording.provider_deleted_at is not None
        assert old_recording.provider_delete_error is None


@pytest.mark.django_db
class TestPhoneCallSync:
    """Call imports are the source of CRM customer touchpoints. The provider
    path must be idempotent and preserve recording evidence.
    """

    @pytest.fixture(autouse=True)
    def provider_env(self, settings: SettingsWrapper, tmp_path: Path) -> Path:
        settings.PHONE_RECORDING_STORAGE_ROOT = str(tmp_path)
        IntegrationSettings.objects.filter(pk=1).update(
            phone_provider_base_url="https://phone.example.test",
            phone_provider_username="user",
            phone_provider_password="secret",
            phone_provider_account_code="account",
        )
        return tmp_path

    def test_sync_archives_recording_and_is_idempotent(self, provider_env: Path) -> None:
        company = make_company("Sync Company")
        ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        payload = self._payload()
        audio = silent_wav(1)

        with mock.patch(
            "apps.crm.services.phone_call_service.PhoneProviderPortalClient"
        ) as client_class:
            portal = client_class.return_value
            portal.iter_call_pages.return_value = [PhoneProviderCallPage(page=1, calls=[payload])]
            portal.download_recording.return_value = (
                audio,
                "call.mp3",
                "audio/mpeg",
            )

            first = sync_call_history()

            portal.iter_call_pages.return_value = [PhoneProviderCallPage(page=1, calls=[payload])]
            second = sync_call_history()

        assert first.calls_seen == 1
        assert first.calls_saved == 1
        assert first.recordings_seen == 1
        assert first.recordings_archived == 1
        assert second.calls_seen == 1
        assert second.calls_saved == 0
        assert second.recordings_archived == 0
        assert PhoneCallRecord.objects.count() == 1
        assert PhoneCallRecording.objects.count() == 1

        call = PhoneCallRecord.objects.get()
        assert call.company == company
        recording = call.recording
        assert recording.filename == "call.mp3"
        assert recording.byte_size == len(audio)
        assert recording.duration_ms == 1000
        assert recording.sha256
        assert recording.storage_path is not None
        assert (provider_env / recording.storage_path).exists()

    def test_recording_download_failure_persists_app_error(self) -> None:
        payload = self._payload(recording_id="broken-recording")

        with mock.patch(
            "apps.crm.services.phone_call_service.PhoneProviderPortalClient"
        ) as client_class:
            portal = client_class.return_value
            portal.iter_call_pages.return_value = [PhoneProviderCallPage(page=1, calls=[payload])]
            portal.download_recording.side_effect = ValueError("download failed")

            before = AppError.objects.count()
            result = sync_call_history()

        assert result.calls_seen == 1
        assert result.recordings_seen == 1
        assert result.recordings_archived == 0
        assert AppError.objects.count() == before + 1
        recording = PhoneCallRecording.objects.get()
        assert recording.archive_error == "download failed"
        assert not recording.storage_path

    def _payload(self, *, recording_id: str = "recording-1") -> dict[str, str]:
        return {
            "id": "provider-call-1",
            "calldate": "2026-06-01",
            "calltime": "10:11:12",
            "origin": "021 555 123",
            "destination": "09 636 5131",
            "seconds": "42",
            "charge": "0.1200",
            "type": "Inbound",
            "status": "Answered",
            "description": "Customer call",
            "RecordingId": recording_id,
        }


@pytest.mark.django_db
class TestStoreRecordingBytes:
    """The store half of the archive is public so non-provider producers (the
    E2E seed) reuse the path rules instead of re-deriving them.
    """

    @pytest.fixture(autouse=True)
    def storage_root(self, settings: SettingsWrapper, tmp_path: Path) -> Path:
        settings.PHONE_RECORDING_STORAGE_ROOT = str(tmp_path)
        return tmp_path

    def test_stores_wav_under_its_own_suffix(self, storage_root: Path) -> None:
        """A stored .wav must keep its suffix: the download endpoint derives
        Content-Type from the stored path, so a WAV under .mp3 is served as
        audio/mpeg and no browser plays it.
        """
        call = make_call("wav-call", company=make_company("Wav Co"))
        recording = make_recording(call, "wav-recording", storage_path=None)
        content = silent_wav(0.5)

        store_recording_bytes(
            call=call,
            recording=recording,
            content=content,
            filename="e2e-call.wav",
            content_type="audio/wav",
        )

        recording.refresh_from_db()
        assert recording.storage_path is not None
        assert recording.storage_path.endswith(".wav")
        assert (storage_root / recording.storage_path).read_bytes() == content
        assert recording.filename == "e2e-call.wav"
        assert recording.content_type == "audio/wav"
        assert recording.byte_size == len(content)
        assert recording.sha256 == hashlib.sha256(content).hexdigest()
        assert recording.archived_at is not None
        assert recording.account_code == call.account_code
        assert recording.duration_ms == 500


@pytest.mark.django_db
class TestWithheldNumberCalls:
    """2talk reports a withheld caller as origin "". The first real sync hit
    this on its first page: every number column is nullable with a not-blank
    check, so the row must store NULL for the missing party, not "".
    """

    def test_inbound_call_from_withheld_number_is_saved_with_null_external_number(self) -> None:
        PhoneEndpoint.objects.create(
            number="+6496365131",
            label="Main line",
            endpoint_type=PhoneEndpoint.EndpointType.MAIN_LINE,
            is_active=True,
        )
        payload = {
            "id": "10684389777",
            "type": "Inbound",
            "origin": "",
            "destination": "+6496365131",
            "calldate": "2026-08-21",
            "calltime": "13:43:13",
            "seconds": "60",
            "charge": "0.00000000",
            "status": "Ok",
            "description": "New Zealand",
        }

        call, created = upsert_call_record(
            payload=payload, account_code="15539090", matcher=PhoneMatcher()
        )

        assert created is True
        call.refresh_from_db()
        assert call.direction == PhoneCallRecord.Direction.INBOUND
        assert call.origin is None
        assert call.normalized_origin is None
        assert call.external_number is None
        assert call.our_number == "+6496365131"


class TestMeasureAudioDuration:
    """The archive measures what it stores; what it cannot measure is not a recording."""

    def test_reads_a_wav_to_the_millisecond(self) -> None:
        assert measure_audio_duration_ms(silent_wav(2.25)) == 2250

    def test_refuses_bytes_that_are_not_audio(self) -> None:
        with pytest.raises(ValueError, match="not audio"):
            measure_audio_duration_ms(b"RIFF....WAVEfmt ")


@pytest.mark.django_db
class TestRecordingDurationLifecycle:
    @pytest.fixture(autouse=True)
    def storage_root(self, settings: SettingsWrapper, tmp_path: Path) -> Path:
        settings.PHONE_RECORDING_STORAGE_ROOT = str(tmp_path)
        return tmp_path

    def test_local_delete_clears_the_measurement_with_the_file(self) -> None:
        call = make_call("measured-call", company=make_company("Measured Co"))
        recording = make_recording(call, "measured-recording", storage_path=None)
        store_recording_bytes(
            call=call,
            recording=recording,
            content=silent_wav(1),
            filename="call.wav",
            content_type="audio/wav",
        )
        recording.refresh_from_db()
        assert recording.duration_ms == 1000

        delete_local_recording(recording)

        recording.refresh_from_db()
        assert recording.duration_ms is None
        assert recording.storage_path is None


@pytest.mark.django_db
class TestDurationBackfill:
    """The 0003 migration's rule: measure every archived file present, leave the rest NULL."""

    def test_measures_present_files_and_leaves_missing_ones_null(self, tmp_path: Path) -> None:
        company = make_company("Backfill Co")
        present = make_recording(
            make_call("present-call", company=company), "present", storage_path="2026/01/01/p.wav"
        )
        (tmp_path / "2026/01/01").mkdir(parents=True)
        (tmp_path / "2026/01/01/p.wav").write_bytes(silent_wav(1.5))
        missing = make_recording(
            make_call("missing-call", company=company), "missing", storage_path="2026/01/01/m.wav"
        )

        measured = backfill.measure_archived_recordings(PhoneCallRecording, tmp_path)

        assert measured == 1
        present.refresh_from_db()
        missing.refresh_from_db()
        assert present.duration_ms == 1500
        assert missing.duration_ms is None

    def test_aborts_on_a_file_that_is_not_audio(self, tmp_path: Path) -> None:
        make_recording(
            make_call("junk-call", company=make_company("Junk Co")),
            "junk",
            storage_path="junk.mp3",
        )
        (tmp_path / "junk.mp3").write_bytes(b"not audio at all")

        with pytest.raises(RuntimeError, match="not audio"):
            backfill.measure_archived_recordings(PhoneCallRecording, tmp_path)
