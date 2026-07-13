import tempfile
import unittest
from pathlib import Path

from core.storage_browser import list_entries, resolve_under_root


class StorageBrowserTests(unittest.TestCase):
    def test_resolve_under_root_blocks_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Data"
            root.mkdir()
            inside = root / "nested"
            inside.mkdir()
            self.assertEqual(resolve_under_root(root, inside), inside.resolve())
            with self.assertRaises(ValueError):
                resolve_under_root(root, root.parent)

    def test_list_entries_sorted_dirs_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "b.txt").write_text("x", encoding="utf-8")
            (root / "a-dir").mkdir()
            (root / "c-dir").mkdir()
            entries = list_entries(root, root)
            self.assertEqual([item.name for item in entries], ["a-dir", "c-dir", "b.txt"])
            self.assertTrue(entries[0].is_dir)
            self.assertFalse(entries[-1].is_dir)


if __name__ == "__main__":
    unittest.main()
