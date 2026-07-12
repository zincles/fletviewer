import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DebugLogInitializationTests(unittest.TestCase):
    def _run_python(self, code: str, storage_temp: Path) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["FLET_APP_STORAGE_TEMP"] = str(storage_temp)
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_import_does_not_create_log_file_or_temp_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_temp = Path(temp_dir) / "Temp"
            self._run_python("import app.debug_log", storage_temp)
            self.assertFalse(storage_temp.exists())

    def test_explicit_configuration_creates_log_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_temp = Path(temp_dir) / "Temp"
            self._run_python(
                "from app.debug_log import configure_logging; configure_logging()",
                storage_temp,
            )
            log_path = storage_temp / "debug_log.md"
            self.assertTrue(log_path.is_file())
            self.assertIn("# FletViewer 调试日志", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
