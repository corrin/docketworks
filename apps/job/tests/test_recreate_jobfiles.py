import importlib.util
import os
import tempfile
import types
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "recreate_jobfiles.py"


def load_recreate_jobfiles() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("recreate_jobfiles", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load recreate_jobfiles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecreateJobFilesTests(SimpleTestCase):
    def test_image_placeholder_accepts_quotes_in_job_name(self) -> None:
        recreate_jobfiles = load_recreate_jobfiles()

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "placeholder.png"
            recreate_jobfiles.create_dummy_file(
                str(output),
                'COLOURSTEEL "CLOUD" POWDERCOATING',
                97380,
                "placeholder.png",
            )

            with Image.open(output) as image:
                self.assertEqual(image.size, (400, 200))

    def test_pdf_runs_pandoc_in_a_writable_cwd(self) -> None:
        """pandoc must never run in the inherited cwd (the read-only release dir).

        Guards the UAT regression where pandoc's intermediate temp write hit
        `openTempFile: permission denied` on the immutable release dir.
        """
        recreate_jobfiles = load_recreate_jobfiles()

        captured_cwd: str | None = None
        cwd_was_writable = False

        def fake_run(cmd: list[str], **kwargs: object) -> types.SimpleNamespace:
            nonlocal captured_cwd, cwd_was_writable
            cwd = kwargs.get("cwd")
            assert isinstance(cwd, str)
            captured_cwd = cwd
            # The tempdir is deleted after the call, so check writability now.
            cwd_was_writable = os.access(cwd, os.W_OK)
            return types.SimpleNamespace(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "placeholder.pdf"
            with mock.patch.object(
                recreate_jobfiles.subprocess, "run", side_effect=fake_run
            ):
                recreate_jobfiles.create_dummy_file(
                    str(output), "Job Name", 97380, "placeholder.pdf"
                )

        self.assertIsNotNone(captured_cwd)
        self.assertTrue(cwd_was_writable)
        assert captured_cwd is not None
        self.assertNotEqual(Path(captured_cwd).resolve(), Path.cwd().resolve())
