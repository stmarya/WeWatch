import os
import tempfile
import unittest
from pathlib import Path

from utils.privacy import purge_old_files, retention_days


class PrivacyRetentionTests(unittest.TestCase):
    def test_retention_requires_non_negative_integer(self):
        previous = os.environ.get("WEBWATCH_TEST_RETENTION")
        try:
            os.environ["WEBWATCH_TEST_RETENTION"] = "14"
            self.assertEqual(retention_days("WEBWATCH_TEST_RETENTION"), 14)
            os.environ["WEBWATCH_TEST_RETENTION"] = "-1"
            with self.assertRaises(RuntimeError):
                retention_days("WEBWATCH_TEST_RETENTION")
            os.environ["WEBWATCH_TEST_RETENTION"] = "fourteen"
            with self.assertRaises(RuntimeError):
                retention_days("WEBWATCH_TEST_RETENTION")
        finally:
            if previous is None:
                os.environ.pop("WEBWATCH_TEST_RETENTION", None)
            else:
                os.environ["WEBWATCH_TEST_RETENTION"] = previous

    def test_expired_files_are_purged_only_when_retention_is_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            expired = Path(directory) / "old.jpg"
            fresh = Path(directory) / "new.jpg"
            ignored = Path(directory) / "old.txt"
            for path in (expired, fresh, ignored):
                path.write_text("test", encoding="utf-8")
            os.utime(expired, (1, 1))
            os.utime(ignored, (1, 1))

            self.assertEqual(purge_old_files(directory, {".jpg"}, 0), 0)
            self.assertTrue(expired.exists())
            self.assertEqual(
                purge_old_files(directory, {".jpg"}, 1, now=86400 * 10),
                1,
            )
            self.assertFalse(expired.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(ignored.exists())

    def test_expired_database_rows_are_removed(self):
        from services import database
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(database, "BASE_DIR", Path(directory)):
                database.init_db()
                database.init_attendance_db()
                with database._connect("mood.db") as conn:
                    conn.execute(
                        "INSERT INTO mood (waktu, emosi) VALUES (?, ?)",
                        ("2000-01-01 00:00:00", "Netral"),
                    )
                    conn.execute(
                        "INSERT INTO mood (waktu, emosi) VALUES (?, ?)",
                        ("2999-01-01 00:00:00", "Netral"),
                    )
                with database._connect("attendance.db") as conn:
                    conn.execute(
                        "INSERT INTO attendance (name, date, clock_in, total_seconds) "
                        "VALUES (?, ?, ?, ?)",
                        ("Test", "2000-01-01", "00:00:00", 0),
                    )
                    conn.execute(
                        "INSERT INTO attendance (name, date, clock_in, total_seconds) "
                        "VALUES (?, ?, ?, ?)",
                        ("Test", "2999-01-01", "00:00:00", 0),
                    )

                self.assertEqual(database.purge_expired_records(30, 30), (1, 1))
                with database._connect("mood.db") as conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM mood").fetchone()[0], 1)
                with database._connect("attendance.db") as conn:
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0],
                        1,
                    )


if __name__ == "__main__":
    unittest.main()