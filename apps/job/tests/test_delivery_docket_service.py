"""Delivery-docket service tests (ported v1 test_delivery_docket_service.py).

The emitted JobEvent must carry the staff who triggered the print
(JobEvent.staff is NOT NULL), and the docket must persist as a JobFile.
"""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from django.test import override_settings

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import JobEvent, JobFile
from apps.job.services.delivery_docket_service import generate_delivery_docket
from apps.job.tests._pdf_golden_fixtures import _seed_company_defaults

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _workflow_folder(tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "workflow"
    folder.mkdir()
    with override_settings(DROPBOX_WORKFLOW_FOLDER=str(folder)):
        yield folder


def test_generate_attributes_jobevent_to_calling_staff(
    company: Company, office_staff: Staff, _workflow_folder: Path
) -> None:
    job = make_job(company, office_staff, name="Test Delivery Job")
    # The letterhead requires the wide logo on CompanyDefaults.
    _seed_company_defaults()

    pdf_buffer, job_file = generate_delivery_docket(job, staff=office_staff)

    assert isinstance(pdf_buffer, BytesIO)
    assert isinstance(job_file, JobFile)
    assert job_file.job_id == job.id
    assert job_file.print_on_jobsheet is False
    assert (_workflow_folder / job_file.file_path).exists()

    events = JobEvent.objects.filter(job=job, event_type="delivery_docket_generated")
    assert events.count() == 1
    event = events.get()
    assert event.staff_id == office_staff.id
    assert event.detail["filename"] == job_file.filename
    assert event.detail["file_id"] == str(job_file.id)
