"""A restored PDF placeholder must be a PDF the app's own consumers can open.

Business risk covered: the workshop job sheet merges attachment PDFs with
pypdf and the file list thumbnails them, so a placeholder that is not a
parseable PDF breaks printing and browsing on every non-production restore.
"""

from pathlib import Path

from pypdf import PdfReader

from scripts.ops.recreate_jobfiles import create_dummy_file


def test_pdf_placeholder_is_a_readable_pdf_naming_the_job(tmp_path: Path) -> None:
    filepath = tmp_path / "Job-4711" / "drawing.pdf"

    create_dummy_file(filepath, "Stainless bench", "4711", "drawing.pdf")

    reader = PdfReader(filepath)
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Stainless bench" in text
    assert "4711" in text
    assert "drawing.pdf" in text
