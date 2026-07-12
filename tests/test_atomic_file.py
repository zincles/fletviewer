import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.atomic_file import atomic_write_json, atomic_write_text


class AtomicFileTests(unittest.TestCase):
    def test_atomic_write_creates_parent_and_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Data" / "value.json"

            atomic_write_json(path, {"value": 1})

            self.assertIn('"value": 1', path.read_text(encoding="utf-8"))

    def test_replace_failure_preserves_existing_file_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("old", encoding="utf-8")
            original_replace = Path.replace

            def fail_target_replace(source, target):
                if Path(target) == path:
                    raise PermissionError("replace denied")
                return original_replace(source, target)

            with patch.object(Path, "replace", autospec=True, side_effect=fail_target_replace):
                with self.assertRaises(PermissionError):
                    atomic_write_text(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(path.parent.glob(".config.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
