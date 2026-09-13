#!/usr/bin/env python
"""Create dummy files for JobFile records after production restore.

Part of the first-hour post-restore steps: a scrubbed prod dump carries
JobFile rows pointing at files that were never copied (only their metadata is
restored), so anything that lists or opens a job's files 404s until this runs.
"""

import logging
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from scripts.bootstrap import setup_django

# No os.chdir: `-m` only resolves from the repo root, so that already IS the
# working directory by the time this runs.
setup_django()

from apps.job.models import JobFile  # noqa: E402
from apps.job.services.file_service import job_file_full_path  # noqa: E402

logger = logging.getLogger(__name__)


def _run_pandoc(args: list[str], content: str, label: str) -> None:
    """Run pandoc in a writable scratch cwd.

    pandoc writes intermediate temp files into the process working directory.
    At runtime that cwd is the immutable, read-only release dir, so pandoc
    must be given a writable cwd of its own. The final output is unaffected —
    it is written to the absolute path passed via ``-o``.
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
        # Fable: pandoc with wkhtmltopdf was rejected because each call starts
        # a QtWebKit process (~0.27 s, ~23 min over a restore) and the engine
        # was never a declared prerequisite; reportlab is the renderer every
        # production PDF already uses and writes the page in ~1 ms. The page
        # must be a real PDF, not a text placeholder: the workshop job sheet
        # merges attachments with pypdf and the file list thumbnails them.
        document = canvas.Canvas(str(filepath), pagesize=A4)
        document.setTitle(f"Job {job_number}")
        document.setFont("Helvetica-Bold", 18)
        document.drawString(72, 780, f"Job: {job_name}")
        document.setFont("Helvetica", 12)
        document.drawString(72, 755, f"Number: {job_number}")
        document.drawString(72, 735, f"Dummy PDF for {filename}")
        document.save()

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
    job_files = JobFile.objects.exclude(file_path="").select_related("job")

    total = job_files.count()
    created = 0
    skipped = 0

    for job_file in job_files:
        # The same resolver the view serves from, so a placeholder lands
        # exactly where a download will look, and a restored row whose path
        # escapes the workflow root fails the run instead of writing outside it.
        file_path = job_file_full_path(job_file)

        if file_path.exists():
            skipped += 1
            continue

        create_dummy_file(
            file_path, job_file.job.name, str(job_file.job.job_number), job_file.filename
        )
        created += 1

        if created % 100 == 0:
            logger.info("Created %d dummy files...", created)

    logger.info("Created %d, skipped %d (total %d)", created, skipped, total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()  # Let exceptions propagate - fail early principle
