#!/usr/bin/env python
"""Create dummy files for JobFile records after production restore.

Part of the first-hour post-restore steps: a scrubbed prod dump carries
JobFile rows pointing at files that were never copied (only their metadata is
restored), so anything that lists or opens a job's files 404s until this runs.
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# scripts/ops/ is two levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402 -- sys.path must be set up first
from PIL import Image, ImageDraw  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402 -- Django must be configured first

from apps.job.models import JobFile  # noqa: E402

logger = logging.getLogger(__name__)


def _run_pandoc(args: list[str], content: str, label: str) -> None:
    """Run pandoc in a writable scratch cwd.

    pandoc (and the pdf-engine it spawns) writes intermediate temp files into
    the process working directory. At runtime that cwd is the immutable,
    read-only release dir, so pandoc must be given a writable cwd of its own.
    The final output is unaffected — it is written to the absolute path
    passed via ``-o``.
    """
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        raise RuntimeError("pandoc is not installed or not on PATH")
    with tempfile.TemporaryDirectory() as workdir:
        process = subprocess.run(  # noqa: S603 -- fixed argv; executable resolved via shutil.which
            [pandoc, *args],
            input=content,
            text=True,
            capture_output=True,
            cwd=workdir,
            check=False,
        )
    if process.returncode != 0:
        raise RuntimeError(f"Failed to create {label}: {process.stderr}")


def create_dummy_file(filepath: Path, job_name: str, job_number: str, filename: str) -> None:
    """Create a dummy file of the appropriate type."""
    filepath.parent.mkdir(parents=True, exist_ok=True)

    ext = filepath.suffix.lower()

    if ext == ".pdf":
        # Create PDF using pandoc with wkhtmltopdf engine
        content = f"# Job: {job_name}\n\n**Number:** {job_number}\n\nDummy PDF for {filename}"
        _run_pandoc(
            [
                "-o",
                str(filepath),
                "--pdf-engine=wkhtmltopdf",
                "--metadata",
                f"pagetitle=Job {job_number}",
            ],
            content,
            "PDF",
        )

    elif ext in (".png", ".jpg", ".jpeg"):
        image = Image.new("RGB", (400, 200), "white")
        ImageDraw.Draw(image).multiline_text(
            (10, 10),
            f"Job: {job_name}\nNumber: {job_number}",
            fill="black",
        )
        image.save(filepath)

    elif ext == ".docx":
        # .docx only — pandoc infers the writer from the extension and has no
        # legacy "doc" writer, so a .doc path here fails the whole run; .doc
        # falls through to the text-placeholder branch instead.
        content = f"# Job: {job_name}\n\n**Number:** {job_number}\n\nDummy document for {filename}"
        _run_pandoc(["-o", str(filepath)], content, "DOCX")

    elif ext == ".eml":
        # Create email file (RFC 822 format)
        filepath.write_text(
            f"From: dummy@example.com\n"
            f"To: user@example.com\n"
            f"Subject: Job {job_number} - {job_name}\n"
            f"Date: Thu, 1 Jan 1970 00:00:00 +0000\n"
            f"\n"
            f"Job: {job_name}\nNumber: {job_number}\nFile: {filename}\n"
        )

    elif ext == ".txt":
        filepath.write_text(f"Job: {job_name}\nNumber: {job_number}\nFile: {filename}\n")

    elif ext == ".zip":
        with zipfile.ZipFile(filepath, "w") as zf:
            zf.writestr(
                "readme.txt",
                f"Job: {job_name}\nNumber: {job_number}\nFile: {filename}\n",
            )

    else:
        # For all other extensions (.dxf, .step, .py, .conf, .xlsx, etc),
        # create a text placeholder. .xlsx/.xlsm fall through to this branch
        # rather than the v1 pandas.DataFrame.to_excel() route: v2 depends on
        # neither pandas nor openpyxl (ADR 0032 — no library import to
        # reintroduce just for a dummy-file stand-in), and a placeholder file
        # satisfies the same purpose as every other unhandled extension —
        # something exists at the expected path.
        logger.info("Creating text placeholder for: %s (extension: %s)", filename, ext)
        filepath.write_text(f"Job: {job_name}\nNumber: {job_number}\nFile: {filename}\n")


def main() -> None:
    job_files = JobFile.objects.filter(file_path__isnull=False).exclude(file_path="")

    total = job_files.count()
    created = 0
    skipped = 0

    workflow_root = Path(settings.DROPBOX_WORKFLOW_FOLDER).resolve()
    for job_file in job_files:
        # Use DROPBOX_WORKFLOW_FOLDER to match where the view serves files from
        file_path = (workflow_root / str(job_file.file_path)).resolve()
        # A restored file_path is data, not a trusted path: an absolute value
        # or a ".." segment would land the dummy file outside the workflow
        # root. Refuse the row loudly rather than write it.
        if not file_path.is_relative_to(workflow_root):
            raise ValueError(
                f"JobFile {job_file.pk} file_path escapes DROPBOX_WORKFLOW_FOLDER: "
                f"{job_file.file_path!r} resolves to {file_path}"
            )

        if file_path.exists():
            skipped += 1
            continue

        job_name = job_file.job.name if job_file.job else "No Job"
        job_number = str(job_file.job.job_number) if job_file.job else "N/A"

        # Fail early - no try/except, let errors propagate
        create_dummy_file(file_path, job_name, job_number, job_file.filename)
        created += 1

        if created % 100 == 0:
            logger.info("Created %d dummy files...", created)

    logger.info("Created %d, skipped %d (total %d)", created, skipped, total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()  # Let exceptions propagate - fail early principle
