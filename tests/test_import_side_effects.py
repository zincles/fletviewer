import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ImportSideEffectTests(unittest.TestCase):
    def test_importing_image_fetcher_does_not_create_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "FletViewer"
            env = os.environ.copy()
            env["FLETVIEWER_HOME"] = str(home)
            env.pop("FLET_APP_STORAGE_DATA", None)
            env.pop("FLET_APP_STORAGE_TEMP", None)
            subprocess.run(
                [sys.executable, "-c", "import app.image_fetcher"],
                cwd=Path(__file__).resolve().parent.parent,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse(home.exists())


if __name__ == "__main__":
    unittest.main()
