#!/usr/bin/env python
"""
Create dummy files for JobFile records after production restore.
Part of Step 14 in the backup/restore process.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
django.setup()

from django.conf import settings

from apps.job.models import JobFile

logger = logging.getLogger(__name__)


def create_dummy_file(filepath, job_name, job_number, filename):
    """Create a dummy file of the appropriate type."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        # Create PDF using pandoc with wkhtmltopdf engine
        content = (
            f"# Job: {job_name}\n\n**Number:** {job_number}\n\nDummy PDF for {filename}"
        )
        process = subprocess.run(
            [
                "pandoc",
                "-o",
                filepath,
                "--pdf-engine=wkhtmltopdf",
                "--metadata",
                f"pagetitle=Job {job_number}",
            ],
            input=content,
            text=True,
            capture_output=True,
        )
        if process.returncode != 0:
            raise Exception(f"Failed to create PDF: {process.stderr}")

    elif ext in [".png", ".jpg", ".jpeg"]:
        # Create image using ImageMagick convert
        subprocess.run(
            [
                "convert",
                "-size",
                "400x200",
                "xc:white",
                "-pointsize",
                "20",
                "-draw",
                f'text 10,30 "Job: {job_name}"',
                "-draw",
                f'text 10,60 "Number: {job_number}"',
                filepath,
            ],
            check=True,
        )

    elif ext in [".docx", ".doc"]:
        # Create Word document using pandoc
        content = f"# Job: {job_name}\n\n**Number:** {job_number}\n\nDummy document for {filename}"
        process = subprocess.run(
            ["pandoc", "-o", filepath], input=content, text=True, capture_output=True
        )
        if process.returncode != 0:
            raise Exception(f"Failed to create DOCX: {process.stderr}")

    elif ext == ".eml":
        # Create email file (RFC 822 format)
        with open(filepath, "w") as f:
            f.write(
                f"From: dummy@example.com\n"
                f"To: user@example.com\n"
                f"Subject: Job {job_number} - {job_name}\n"
                f"Date: Thu, 1 Jan 1970 00:00:00 +0000\n"
                f"\n"
                f"Job: {job_name}\nNumber: {job_number}\nFile: {filename}\n"
            )

    elif ext == ".txt":
        # Create text file
        with open(filepath, "w") as f:
            f.write(f"Job: {job_name}\nNumber: {job_number}\nFile: {filename}\n")

    elif ext == ".zip":
        # Create minimal zip file
        import zipfile

        with zipfile.ZipFile(filepath, "w") as zf:
            zf.writestr(
                "readme.txt",
                f"Job: {job_name}\nNumber: {job_number}\nFile: {filename}\n",
            )

    elif ext in [".xlsx", ".xlsm"]:
        # Create Excel file using pandas
        import pandas as pd

        df = pd.DataFrame(
            {"Job": [job_name], "Number": [job_number], "File": [filename]}
        )
        df.to_excel(filepath, index=False)

    else:
        # For all other extensions (.dxf, .step, .py, .conf, etc), create text file
        logger.info(f"Creating text placeholder for: {filename} (extension: {ext})")
        with open(filepath, "w") as f:
            f.write(f"Job: {job_name}\nNumber: {job_number}\nFile: {filename}\n")


def main():
    job_files = JobFile.objects.filter(file_path__isnull=False).exclude(file_path="")

    total = job_files.count()
    created = 0
    skipped = 0

    for job_file in job_files:
        # Use DROPBOX_WORKFLOW_FOLDER to match where the view serves files from
        file_path = os.path.join(
            settings.DROPBOX_WORKFLOW_FOLDER, str(job_file.file_path)
        )

        if os.path.exists(file_path):
            skipped += 1
            continue

        job_name = job_file.job.name if job_file.job else "No Job"
        job_number = job_file.job.job_number if job_file.job else "N/A"

        # Fail early - no try/except, let errors propagate
        create_dummy_file(file_path, job_name, job_number, job_file.filename)
        created += 1

        if created % 100 == 0:
            logger.info(f"Created {created} dummy files...")

    logger.info(f"Created {created}, skipped {skipped} (total {total})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()  # Let exceptions propagate - fail early principle
