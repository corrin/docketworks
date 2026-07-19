import importlib.util
import tempfile
import types
from pathlib import Path

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
