"""SQLite to Supabase migration is complete, safe to rerun, and reports failures."""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import migrate_sqlite_to_supabase as migrate
from fake_supabase import FakePostgrest
from storage import SqliteStore

FACE = [0.1] * 128


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "attendance.db")
        self.fake = FakePostgrest()
        self.env = patch.dict(os.environ, {
            "SUPABASE_URL": "https://fake.supabase.co", "SUPABASE_SERVICE_KEY": "sb_secret_test",
        })
        self.env.start()
        self.http = patch("storage.requests.request", side_effect=self.fake.request)
        self.http.start()

    def tearDown(self):
        self.http.stop()
        self.env.stop()
        self.temp.cleanup()

    def run_migration(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["migrate_sqlite_to_supabase.py", self.path]), redirect_stdout(output):
            result = migrate.main()
        return result, output.getvalue()

    def test_faceless_metadata_attendance_corruption_and_idempotence(self):
        sqlite = SqliteStore(self.path)
        sqlite.register_student("NOFACE", "No face", "5", [], "card-old", metadata={"valid_until": ""})
        sqlite.register_student("FACE", "Has face", "6", FACE, "card-face", metadata={
            "section": "B", "roll_no": "42", "active": False,
            "valid_until": "2027-12-31", "session": "2025",
        })
        sqlite.register_student("CORRUPT", "Broken face", "4", FACE, "card-broken")
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE students SET face_descriptor='[garbage' WHERE student_id='CORRUPT'")
        sqlite.record_attendance("FACE", "Has face", "2026-11-11", "08:45:00", "Late", "manual")

        result, output = self.run_migration()
        self.assertEqual(result, 0, output)
        self.assertEqual(set(self.fake.students), {"NOFACE", "FACE", "CORRUPT"})
        self.assertIsNone(self.fake.students["NOFACE"]["face_descriptor"])
        self.assertIsNone(self.fake.students["CORRUPT"]["face_descriptor"])
        self.assertEqual(self.fake.students["NOFACE"]["card_token"], "card-old")
        self.assertIsNone(self.fake.students["NOFACE"]["valid_until"])
        self.assertEqual(self.fake.students["FACE"]["face_descriptor"], FACE)
        self.assertEqual(self.fake.students["FACE"]["card_token"], "card-face")
        self.assertEqual(self.fake.students["FACE"]["section"], "B")
        self.assertEqual(self.fake.students["FACE"]["roll_no"], "42")
        self.assertIs(self.fake.students["FACE"]["active"], False)
        self.assertEqual(self.fake.students["FACE"]["valid_until"], "2027-12-31")
        self.assertEqual(self.fake.students["FACE"]["session"], "2025")
        self.assertEqual(self.fake.attendance[("FACE", "2026-11-11")]["status"], "Late")
        self.assertEqual(self.fake.attendance[("FACE", "2026-11-11")]["method"], "manual")
        self.assertIn("face নেই", output)

        result, output = self.run_migration()
        self.assertEqual(result, 0, output)
        self.assertEqual(len(self.fake.students), 3)
        self.assertEqual(len(self.fake.attendance), 1)
        self.assertIn("3 আগেই ছিল", output)
        self.fake.students["FACE"]["face_descriptor"] = None
        result, output = self.run_migration()
        self.assertEqual(result, 0, output)
        self.assertEqual(self.fake.students["FACE"]["face_descriptor"], FACE)
        self.assertIn("face যোগ হয়েছে", output)

    def test_legacy_schema_missing_face_token_and_attendance_fields(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE students(student_id TEXT PRIMARY KEY, name TEXT, class_name TEXT)")
            conn.execute("INSERT INTO students VALUES ('LEGACY','Student','3')")
            conn.execute("CREATE TABLE attendance(student_id TEXT, name TEXT, date TEXT, time TEXT)")
            conn.execute("INSERT INTO attendance VALUES ('LEGACY','Student','2026-11-11','09:30:00')")
        result, output = self.run_migration()
        self.assertEqual(result, 0, output)
        self.assertIsNone(self.fake.students["LEGACY"]["face_descriptor"])
        self.assertEqual(len(self.fake.students["LEGACY"]["card_token"]), 18)
        self.assertEqual(self.fake.attendance[("LEGACY", "2026-11-11")]["status"], "Present")
        self.assertEqual(self.fake.attendance[("LEGACY", "2026-11-11")]["method"], "face+qr")
        self.assertIn("1 যোগ হয়েছে", output)

    def test_network_failure_is_not_silently_reported_as_success(self):
        SqliteStore(self.path).register_student("S1", "Student", "5", FACE)
        self.fake.fail = True
        result, output = self.run_migration()
        self.assertEqual(result, 1)
        self.assertIn("1 ব্যর্থ", output)

    def test_invalid_expiry_is_not_silently_changed_to_unlimited(self):
        SqliteStore(self.path).register_student("BAD-DATE", "Student", "5", FACE)
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE students SET valid_until='not-a-date' WHERE student_id='BAD-DATE'")
        result, output = self.run_migration()
        self.assertEqual(result, 1)
        self.assertNotIn("BAD-DATE", self.fake.students)
        self.assertIn("valid_until", output)

    def test_existing_different_token_is_reported_instead_of_invalidating_cards(self):
        SqliteStore(self.path).register_student("S1", "Student", "5", FACE, "sqlite-token")
        self.fake.students["S1"] = {
            "student_id": "S1", "name": "Student", "class_name": "5",
            "card_token": "supabase-token", "face_descriptor": None,
        }
        result, output = self.run_migration()
        self.assertEqual(result, 1)
        self.assertIn("card_token ভিন্ন", output)
        self.assertIsNone(self.fake.students["S1"]["face_descriptor"])


if __name__ == "__main__":
    unittest.main()
