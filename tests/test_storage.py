"""SQLite upgrades and Supabase authentication/validation regressions."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fake_supabase import FakePostgrest
from storage import SqliteStore, SupabaseStore, build_store, descriptor_has_expired

FACE = [0.1] * 128


class StorageTests(unittest.TestCase):
    def test_legacy_sqlite_schema_upgrades_without_losing_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "legacy.db")
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE students (student_id TEXT PRIMARY KEY, name TEXT NOT NULL, class_name TEXT NOT NULL)")
                conn.execute("INSERT INTO students VALUES('OLD','Legacy','5')")
                conn.execute("CREATE TABLE attendance (student_id TEXT, name TEXT, date TEXT, time TEXT, status TEXT, UNIQUE(student_id,date))")
            store = SqliteStore(path)
            old = store.find_student("OLD")
            self.assertEqual(old["name"], "Legacy")
            self.assertEqual(len(old["card_token"]), 18)
            self.assertIs(old["active"], True)
            self.assertEqual(old["valid_until"], "")
            self.assertFalse(store.list_students()[0]["has_face"])
            columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(students)")}
            self.assertTrue({"section", "roll_no", "active", "valid_until", "session", "card_token", "face_descriptor"} <= columns)
            self.assertEqual(SqliteStore(path).find_student("OLD")["card_token"], old["card_token"])
            self.assertTrue(store.enroll_face("OLD", FACE))
            store.record_attendance("OLD", "Legacy", "2026-11-12", "09:00:00", "Late", "manual")
            self.assertEqual(store.attendance_for("2026-11-12")[0]["status"], "Late")
            self.assertEqual(store.attendance_for("2026-11-12")[0]["method"], "manual")

    def test_metadata_and_expiry_parity(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SqliteStore(str(Path(temp) / "school.db"))
            store.register_student("S1", "A", "5", FACE, metadata={
                "section": "B", "roll_no": "10", "active": False,
                "valid_until": "2026-11-12", "session": "2025",
            })
            row = store.find_student("S1")
            self.assertEqual((row["section"], row["roll_no"], row["session"]), ("B", "10", "2025"))
            self.assertIs(row["active"], False)
            self.assertEqual(row["valid_until"], "2026-11-12")
            listing = store.list_students()[0]
            self.assertIs(listing["active"], False)
            self.assertEqual(listing["section"], "B")
            today = date(2026, 11, 12)
            self.assertFalse(descriptor_has_expired("", today))
            self.assertFalse(descriptor_has_expired("2026-11-12", today))
            self.assertTrue(descriptor_has_expired("2026-11-11", today))
            self.assertTrue(descriptor_has_expired("not-a-date", today))
            self.assertTrue(descriptor_has_expired("2026-W46-4", today))

    def test_supabase_key_headers_and_missing_configuration(self):
        fake = FakePostgrest()
        with patch("storage.requests.request", side_effect=fake.request):
            for key in ("sb_secret_example", "legacy.jwt.signature"):
                store = SupabaseStore("https://fake.supabase.co/", key)
                self.assertEqual(store.list_students(), [])
                self.assertTrue(store.rest_url.endswith("/rest/v1"))
        self.assertNotIn("Authorization", fake.calls[0]["headers"])
        self.assertEqual(fake.calls[1]["headers"]["Authorization"], "Bearer legacy.jwt.signature")
        with self.assertRaises(ValueError):
            SupabaseStore("https://fake.supabase.co", "sb_publishable_not_privileged")
        with tempfile.TemporaryDirectory() as temp:
            env = {"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": "", "SUPABASE_SECRET_KEY": "", "SUPABASE_KEY": "",
                   "SQLITE_PATH": str(Path(temp) / "local.db")}
            with patch.dict(os.environ, env):
                self.assertIsInstance(build_store(), SqliteStore)
                with patch.dict(os.environ, {"SUPABASE_URL": "https://fake.supabase.co"}):
                    with self.assertRaises(RuntimeError):
                        build_store()
                with patch.dict(os.environ, {"SUPABASE_SERVICE_KEY": "sb_secret_example"}):
                    with self.assertRaises(RuntimeError):
                        build_store()


if __name__ == "__main__":
    unittest.main()
