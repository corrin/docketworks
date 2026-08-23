"""Tests for the phone-call E2E seed.

The seed is a subprocess contract: the spec parses one JSON line and then
plays the recording through the API, so both the line and the served file are
behaviour, not implementation detail.
"""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.conf import settings as django_settings
from django.core.management import CommandError, call_command
from django.http import StreamingHttpResponse
from pytest_django.fixtures import SettingsWrapper

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.test_data import TEST_DATA_PREFIX, is_e2e_name
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.crm.tests.helpers import cookie_client, make_company
from apps.job.models import Job

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def storage_root(settings: SettingsWrapper, tmp_path: Path) -> Path:
    settings.PHONE_RECORDING_STORAGE_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def company() -> Company:
    return make_company(f"{TEST_DATA_PREFIX} Phone Co")


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    return make_job(company, office_staff, name=f"{TEST_DATA_PREFIX} CRM phone call job link")


def _seed(job_id: object) -> str:
    output = StringIO()
    call_command("e2e_seed_phone_call", "--job", str(job_id), stdout=output)
    return output.getvalue()


class TestSeedOutput:
    """One JSON line, and a recording the app will actually serve."""

    def test_seeds_a_matched_call_whose_recording_downloads(
        self, job: Job, company: Company, office_staff: Staff, storage_root: Path
    ) -> None:
        raw = _seed(job.id)

        lines = [line for line in raw.splitlines() if line.strip()]
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert set(payload) == {"call_id", "recording_id", "job_number", "download_url"}
        assert payload["job_number"] == job.job_number

        call = PhoneCallRecord.objects.get(id=payload["call_id"])
        assert call.description is not None
        assert is_e2e_name(call.description)
        assert call.company_id == company.id
        # Unlinked on purpose: linking the call to the job is what the spec
        # drives through the UI, so a seed that did it would prove nothing.
        assert call.job_id is None
        assert call.direction == PhoneCallRecord.Direction.INBOUND
        assert call.external_number == "+6421555123"
        assert call.our_number == "+6496365131"
        assert call.description == f"{TEST_DATA_PREFIX} CRM phone call job link"
        # Nothing the seed invents may pass for a value the provider sent.
        assert call.account_code == TEST_DATA_PREFIX
        assert call.provider_call_id.startswith(TEST_DATA_PREFIX)

        recording = PhoneCallRecording.objects.get(id=payload["recording_id"])
        assert recording.account_code == TEST_DATA_PREFIX
        assert recording.provider_recording_id.startswith(TEST_DATA_PREFIX)
        assert recording.storage_path is not None
        assert recording.storage_path.endswith(".wav")
        assert (storage_root / recording.storage_path).exists()

        # The provider's own payload shape: readers index raw_json rather than
        # probe it (download_recording reads raw["RecordingId"]), so a subset
        # here would be a KeyError in production code.
        assert set(call.raw_json) == {
            "id",
            "calldate",
            "calltime",
            "origin",
            "destination",
            "seconds",
            "charge",
            "type",
            "status",
            "description",
            "RecordingId",
        }
        assert call.raw_json["RecordingId"] == recording.provider_recording_id

        response = cookie_client(office_staff).get(payload["download_url"])

        assert response.status_code == 200
        assert isinstance(response, StreamingHttpResponse)
        assert response["Content-Type"].startswith("audio/")
        assert b"".join(response.streaming_content).startswith(b"RIFF")


class TestSeedRefusals:
    """Every refusal happens before a write: a half-seeded call is a row
    nothing points at and no later run will clean up.
    """

    def test_refuses_a_production_database(self, job: Job, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(django_settings.DATABASES["default"], "NAME", "dw_msm_prod")

        with pytest.raises(CommandError, match="production database"):
            _seed(job.id)

        assert not PhoneCallRecord.objects.exists()

    def test_refuses_an_unknown_job(self) -> None:
        with pytest.raises(CommandError, match="No job"):
            _seed("00000000-0000-0000-0000-000000000000")

        assert not PhoneCallRecord.objects.exists()

    def test_refuses_a_job_with_no_company(self, job: Job) -> None:
        Job.objects.filter(pk=job.pk).untracked_update(company=None)

        with pytest.raises(CommandError, match="no company"):
            _seed(job.id)

        assert not PhoneCallRecord.objects.exists()

    def test_refuses_a_job_the_cleanup_would_not_remove(
        self, company: Company, office_staff: Staff
    ) -> None:
        real_job = make_job(company, office_staff, name="Real customer job")

        with pytest.raises(CommandError, match="E2E"):
            _seed(real_job.id)

        assert not PhoneCallRecord.objects.exists()
