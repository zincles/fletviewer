import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.sqlite_recovery import run_with_corruption_recovery


class SQLiteRecoveryTests(unittest.TestCase):
    def test_locked_database_is_not_quarantined(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "data.db"
            db_path.write_bytes(b"existing")

            def fail():
                raise sqlite3.OperationalError("database is locked")

            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                run_with_corruption_recovery(db_path, fail)

            self.assertEqual(db_path.read_bytes(), b"existing")
            self.assertEqual(list(db_path.parent.glob("*.corrupt-*")), [])


if __name__ == "__main__":
    unittest.main()
