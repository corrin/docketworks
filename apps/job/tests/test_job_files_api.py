"""API tests for job file upload/list/serve/update/delete/thumbnail.

The tests ensure ``getFullJob`` serializes attached files, serving rejects path
traversal, and thumbnail generation works eagerly.
"""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import StreamingHttpResponse
from django.test import Client, override_settings
from PIL import Image

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job, JobFile

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.job.tests.urls"),
]


@pytest.fixture(autouse=True)
def _workflow_folder(tmp_path: Path) -> Iterator[Path]:
    """Sandbox the on-disk writes per test."""
    folder = tmp_path / "workflow"
    folder.mkdir()
    with override_settings(DROPBOX_WORKFLOW_FOLDER=str(folder)):
        yield folder


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    return make_job(company, office_staff, name="Attachment API Job")


def _upload(
    client: Client, job: Job, *files: SimpleUploadedFile, **extra: str
) -> "_MonkeyPatchedWSGIResponse":
    return client.post(f"/api/job/jobs/{job.id}/files/", {"files": list(files), **extra})


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "red").save(buffer, "PNG")
    return buffer.getvalue()


class TestUploadListServe:
    def test_upload_returns_full_job_file_and_file_is_immediately_available(
        self, client: Client, job: Job
    ) -> None:
        payload = b"job attachment contents"
        file_obj = SimpleUploadedFile("attachment.txt", payload, content_type="text/plain")

        response = _upload(client, job, file_obj)

        assert response.status_code == 201
        uploaded = response.json()["uploaded"][0]
        assert uploaded["filename"] == "attachment.txt"
        assert uploaded["mime_type"] == "text/plain"
        assert uploaded["size"] == len(payload)
        assert uploaded["status"] == "active"
        assert uploaded["download_url"]
        assert "uploaded_at" in uploaded
        assert "thumbnail_url" in uploaded

        list_response = client.get(f"/api/job/jobs/{job.id}/files/")
        assert list_response.status_code == 200
        assert list_response.json()[0]["id"] == uploaded["id"]

        download_response = client.get(uploaded["download_url"])
        assert download_response.status_code == 200
        assert isinstance(download_response, StreamingHttpResponse)
        assert download_response.getvalue() == payload
        assert 'inline; filename="attachment.txt"' in download_response["Content-Disposition"]

    def test_upload_accepts_twenty_megabyte_attachment(self, client: Client, job: Job) -> None:
        payload = b"7" * (20 * 1024 * 1024)
        file_obj = SimpleUploadedFile("large-attachment.txt", payload, content_type="text/plain")

        response = _upload(client, job, file_obj)

        assert response.status_code == 201
        uploaded = response.json()["uploaded"][0]
        assert uploaded["filename"] == "large-attachment.txt"
        assert uploaded["size"] == len(payload)

    def test_empty_file_answers_400_with_error_detail(self, client: Client, job: Job) -> None:
        file_obj = SimpleUploadedFile("empty.txt", b"", content_type="text/plain")

        response = _upload(client, job, file_obj)

        assert response.status_code == 400
        payload = response.json()
        assert payload["status"] == "error"
        assert payload["uploaded"] == []
        assert "empty" in payload["errors"][0]

    def test_get_full_job_serialises_files(self, client: Client, job: Job) -> None:
        """The 3b-1 flagged gap: getFullJob must work for a job WITH files."""
        payload = b"full job file body"
        _upload(client, job, SimpleUploadedFile("spec.txt", payload, content_type="text/plain"))

        response = client.get(f"/api/job/jobs/{job.id}/")

        assert response.status_code == 200
        job_files = response.json()["data"]["job"]["job_files"]
        assert len(job_files) == 1
        assert job_files[0]["filename"] == "spec.txt"
        assert job_files[0]["size"] == len(payload)
        assert job_files[0]["download_url"].endswith(f"/files/{job_files[0]['id']}/")

    def test_upload_requires_office_staff(self, job: Job, workshop_staff: Staff) -> None:
        workshop_client = Client()
        authenticate(workshop_client, workshop_staff)
        file_obj = SimpleUploadedFile("nope.txt", b"nope", content_type="text/plain")

        response = _upload(workshop_client, job, file_obj)

        assert response.status_code == 403
        # Reads stay open to any staff.
        assert workshop_client.get(f"/api/job/jobs/{job.id}/files/").status_code == 200


class TestThumbnails:
    def test_image_upload_creates_thumbnail_and_serves_it(self, client: Client, job: Job) -> None:
        """Eager celery runs the thumbnail task inline during the upload."""
        file_obj = SimpleUploadedFile("photo.png", _png_bytes(), content_type="image/png")

        response = _upload(client, job, file_obj)

        assert response.status_code == 201
        file_id = response.json()["uploaded"][0]["id"]

        job_file = JobFile.objects.get(id=file_id)
        thumbnail_path = job_file.thumbnail_path
        assert thumbnail_path is not None
        assert Path(thumbnail_path).exists()

        thumb_response = client.get(f"/api/job/jobs/{job.id}/files/{file_id}/thumbnail/")
        assert thumb_response.status_code == 200
        assert thumb_response["Content-Type"] == "image/jpeg"

        # The list now reports the thumbnail URL.
        listed = client.get(f"/api/job/jobs/{job.id}/files/").json()[0]
        assert listed["thumbnail_url"] == f"/api/job/jobs/{job.id}/files/{file_id}/thumbnail/"

    def test_thumbnail_missing_answers_404(self, client: Client, job: Job) -> None:
        file_obj = SimpleUploadedFile("doc.txt", b"text", content_type="text/plain")
        file_id = _upload(client, job, file_obj).json()["uploaded"][0]["id"]

        response = client.get(f"/api/job/jobs/{job.id}/files/{file_id}/thumbnail/")

        assert response.status_code == 404


class TestUpdateDelete:
    def test_rename_moves_file_on_disk(
        self, client: Client, job: Job, _workflow_folder: Path
    ) -> None:
        file_obj = SimpleUploadedFile("old-name.txt", b"body", content_type="text/plain")
        file_id = _upload(client, job, file_obj).json()["uploaded"][0]["id"]

        response = client.put(
            f"/api/job/jobs/{job.id}/files/{file_id}/",
            {"filename": "new-name.txt", "print_on_jobsheet": False},
            content_type="application/json",
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["filename"] == "new-name.txt"
        assert payload["print_on_jobsheet"] is False
        job_folder = _workflow_folder / f"Job-{job.job_number}"
        assert (job_folder / "new-name.txt").exists()
        assert not (job_folder / "old-name.txt").exists()

    def test_rename_cannot_escape_the_workflow_folder(
        self, client: Client, job: Job, _workflow_folder: Path
    ) -> None:
        """A traversal filename must never move the file outside the root.

        Regression: the rename path took the client filename verbatim, so
        "../../pwned.txt" wrote outside DROPBOX_WORKFLOW_FOLDER and poisoned
        file_path for every later read, delete and stat.
        """
        file_obj = SimpleUploadedFile("safe.txt", b"body", content_type="text/plain")
        file_id = _upload(client, job, file_obj).json()["uploaded"][0]["id"]

        response = client.put(
            f"/api/job/jobs/{job.id}/files/{file_id}/",
            {"filename": "../../pwned.txt"},
            content_type="application/json",
        )

        assert response.status_code == 200
        # Sanitised to a bare name inside the job folder, never above the root.
        job_folder = _workflow_folder / f"Job-{job.job_number}"
        assert (job_folder / "pwned.txt").exists()
        assert not (_workflow_folder.parent / "pwned.txt").exists()
        assert ".." not in response.json().get("file_path", "")
        assert response.json()["filename"] == "pwned.txt"

    def test_rename_to_a_bare_traversal_token_is_rejected(self, client: Client, job: Job) -> None:
        file_obj = SimpleUploadedFile("keep.txt", b"body", content_type="text/plain")
        file_id = _upload(client, job, file_obj).json()["uploaded"][0]["id"]

        response = client.put(
            f"/api/job/jobs/{job.id}/files/{file_id}/",
            {"filename": ".."},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_rename_over_existing_file_is_rejected(self, client: Client, job: Job) -> None:
        first = SimpleUploadedFile("first.txt", b"1", content_type="text/plain")
        second = SimpleUploadedFile("second.txt", b"2", content_type="text/plain")
        ids = [item["id"] for item in _upload(client, job, first, second).json()["uploaded"]]

        response = client.put(
            f"/api/job/jobs/{job.id}/files/{ids[0]}/",
            {"filename": "second.txt"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_delete_removes_disk_file_and_row(
        self, client: Client, job: Job, _workflow_folder: Path
    ) -> None:
        file_obj = SimpleUploadedFile("todelete.txt", b"gone", content_type="text/plain")
        file_id = _upload(client, job, file_obj).json()["uploaded"][0]["id"]
        disk_path = _workflow_folder / f"Job-{job.job_number}" / "todelete.txt"
        assert disk_path.exists()

        response = client.delete(f"/api/job/jobs/{job.id}/files/{file_id}/")

        assert response.status_code == 204
        assert not disk_path.exists()
        assert not JobFile.objects.filter(id=file_id).exists()


class TestServingHardening:
    def test_traversal_file_path_is_never_served(
        self, client: Client, job: Job, tmp_path: Path
    ) -> None:
        """A JobFile row resolving outside the workflow root must not stream."""
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret")
        job_file = JobFile.objects.create(
            job=job,
            filename="secret.txt",
            file_path="../secret.txt",
            mime_type="text/plain",
        )

        response = client.get(f"/api/job/jobs/{job.id}/files/{job_file.id}/")

        assert response.status_code == 500
        assert b"top secret" not in response.content
        assert "escapes the workflow folder" in response.json()["detail"]

    def test_file_belonging_to_other_job_is_404(
        self, client: Client, job: Job, company: Company, office_staff: Staff
    ) -> None:
        other_job = make_job(company, office_staff, name="Other Job")
        file_obj = SimpleUploadedFile("mine.txt", b"mine", content_type="text/plain")
        file_id = _upload(client, job, file_obj).json()["uploaded"][0]["id"]

        response = client.get(f"/api/job/jobs/{other_job.id}/files/{file_id}/")

        assert response.status_code == 404

    def test_missing_file_on_disk_is_404(self, client: Client, job: Job) -> None:
        job_file = JobFile.objects.create(
            job=job,
            filename="ghost.txt",
            file_path=f"Job-{job.job_number}/ghost.txt",
            mime_type="text/plain",
        )

        response = client.get(f"/api/job/jobs/{job.id}/files/{job_file.id}/")

        assert response.status_code == 404

    def test_unknown_ids_are_404(self, client: Client, job: Job) -> None:
        assert client.get(f"/api/job/jobs/{job.id}/files/{uuid4()}/").status_code == 404
