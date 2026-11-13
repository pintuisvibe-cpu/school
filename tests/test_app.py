"""API regression tests on both storage backends (Supabase uses a fake REST API)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from storage import SqliteStore, SupabaseStore
from fake_supabase import FakePostgrest

DAY = "2026-11-12"
FACE = [0.1] * 128


def reg(student_id="STU-1", name="Student"):
    return {"student_id": student_id, "name": name, "class_name": "Class 5", "face_descriptor": FACE}


def check(code, face=FACE):
    return {"student_id": code, "face_descriptor": face}


class ApiSqliteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "attendance.db")
        self.store = SqliteStore(self.db_path)
        self.env = patch.dict(os.environ, {"API_ACCESS_TOKEN": ""})
        self.env.start()
        self.storage_patch = patch.object(main, "store", self.store)
        self.storage_patch.start()
        self.clock = patch.object(
            main, "today_dhaka", return_value=datetime(2026, 11, 12, 15, 30, tzinfo=main.DST)
        )
        self.clock.start()
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self.clock.stop()
        self.storage_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_registration_verification_report_and_pages(self):
        for path in ("/", "/admin", "/admin.html", "/scanner", "/scanner.html"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/health").json()["storage"], "sqlite")

        created = self.client.post("/api/register", json=reg()).json()
        self.assertEqual(created["status"], "success")
        token = created["card_token"]
        self.assertEqual(len(token), 18)
        self.assertNotEqual(token, "STU-1")
        self.assertEqual(self.client.post("/api/register", json=reg()).status_code, 409)
        self.assertEqual(self.store.find_student(token)["student_id"], "STU-1")

        mismatch = self.client.post("/api/verify-attendance", json=check(token, [1.5] * 128))
        self.assertEqual(mismatch.status_code, 200)
        self.assertEqual(mismatch.json()["reason"], "Face Mismatch!")
        self.assertEqual(self.client.get("/api/attendance").json(), [])

        result = self.client.post("/api/verify-attendance", json=check("STU-1"))
        self.assertEqual(result.json()["status"], "success")
        self.assertEqual((result.json()["date"], result.json()["time"]), (DAY, "15:30:00"))
        again = self.client.post("/api/verify-attendance", json=check(token)).json()
        self.assertEqual(again["status"], "failed")
        self.assertIn("ইতিমধ্যে", again["reason"])

        report = self.client.get("/api/attendance").json()
        self.assertEqual(len(report), 1)
        self.assertEqual((report[0]["student_id"], report[0]["date"]), ("STU-1", DAY))
        self.assertEqual(self.client.get("/api/attendance?day=2026-11-11").json(), [])
        students = self.client.get("/api/students").json()
        self.assertEqual(len(students), 1)
        self.assertTrue(students[0]["has_face"])
        self.assertEqual(students[0]["card_token"], token)
        self.assertTrue(students[0]["active"])

    def test_enroll_by_token_and_expired_or_inactive_cards(self):
        self.store.register_student("OLD", "Old student", "Class 6", [], "old-card-token")
        self.assertFalse(self.client.get("/api/students").json()[0]["has_face"])
        no_face = self.client.post("/api/verify-attendance", json=check("OLD")).json()
        self.assertIn("face data নেই", no_face["reason"])
        enrolled = self.client.post("/api/enroll-face", json=check("old-card-token"))
        self.assertEqual(enrolled.status_code, 200)
        self.assertEqual(enrolled.json()["student_id"], "OLD")
        self.assertTrue(self.client.get("/api/students").json()[0]["has_face"])

        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE students SET valid_until='2026-11-11' WHERE student_id='OLD'")
        expired = self.client.post("/api/verify-attendance", json=check("old-card-token")).json()
        self.assertIn("মেয়াদ শেষ", expired["reason"])
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE students SET active=0,valid_until='' WHERE student_id='OLD'")
        disabled = self.client.post("/api/verify-attendance", json=check("OLD")).json()
        self.assertIn("নিষ্ক্রিয়", disabled["reason"])
        self.assertFalse(self.client.get("/api/students").json()[0]["active"])
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE students SET active=1 WHERE student_id='OLD'")
        self.assertEqual(
            self.client.post("/api/verify-attendance", json=check("old-card-token")).json()["status"],
            "success",
        )

    def test_invalid_input_and_corrupt_stored_face_cannot_500(self):
        self.assertEqual(self.client.post("/api/register", json=reg("   ")).status_code, 422)
        for face in ([0.1] * 10, [1e308] * 128, ["bad"] * 128):
            self.assertEqual(
                self.client.post("/api/register", json={**reg(), "face_descriptor": face}).status_code,
                422,
            )
        nan = '{"student_id":"NaN","name":"Bad","class_name":"5","face_descriptor":['
        nan += ','.join(["NaN"] * 128) + "]}"
        self.assertEqual(
            self.client.post("/api/register", content=nan, headers={"content-type": "application/json"}).status_code,
            422,
        )
        for day in ("not-a-date", "2026-13-01", "2026-W46-4"):
            self.assertEqual(self.client.get(f"/api/attendance?day={day}").status_code, 422)
        self.assertEqual(self.client.post("/api/enroll-face", json=check("  ")).status_code, 422)
        self.assertEqual(self.client.post("/api/verify-attendance", json=check("  ")).status_code, 422)
        self.assertEqual(self.client.post("/api/enroll-face", json=check("missing")).status_code, 404)
        self.assertEqual(self.client.post("/api/verify-attendance", json=check("missing")).json()["status"], "failed")
        self.store.register_student("BAD", "Bad face", "Class 6", FACE)
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE students SET face_descriptor=? WHERE student_id='BAD'", ('[1, "x"]',))
        bad = self.client.post("/api/verify-attendance", json=check("BAD"))
        self.assertEqual(bad.status_code, 200)
        self.assertIn("face data নেই", bad.json()["reason"])
        self.assertFalse(self.client.get("/api/students").json()[0]["has_face"])
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE students SET face_descriptor=? WHERE student_id='BAD'", ('[' + '9'*5000 + ']',))
        self.assertEqual(self.client.post("/api/verify-attendance", json=check("BAD")).status_code, 200)

    def test_optional_api_auth_applies_to_all_api_routes(self):
        with patch.dict(os.environ, {"API_ACCESS_TOKEN": "test-only-secret"}):
            self.assertTrue(self.client.get("/health").json()["auth_required"])
            self.assertEqual(self.client.get("/admin").status_code, 200)
            self.assertEqual(self.client.get("/scanner").status_code, 200)
            self.assertEqual(self.client.post("/api/register", json=reg()).status_code, 401)
            self.assertEqual(self.client.post("/api/enroll-face", json=check("OLD")).status_code, 401)
            self.assertEqual(self.client.post("/api/verify-attendance", json=check("OLD")).status_code, 401)
            for path in ("/api/attendance", "/api/students"):
                self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get("/api/students", headers={"Authorization": "Bearer wrong"}).status_code, 401)
            headers = {"Authorization": "Bearer test-only-secret"}
            self.assertEqual(self.client.post("/api/register", json=reg(), headers=headers).status_code, 200)
            self.assertEqual(len(self.client.get("/api/students", headers=headers).json()), 1)

    def test_student_id_preferred_over_colliding_card_token(self):
        self.store.register_student("first", "First", "1", FACE, "second")
        self.store.register_student("second", "Second", "1", FACE, "another-token")
        self.assertEqual(self.store.find_student("second")["name"], "Second")
        self.assertEqual(self.client.post("/api/verify-attendance", json=check("second")).json()["student_name"], "Second")


class ApiSupabaseTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakePostgrest()
        self.http_patch = patch("storage.requests.request", side_effect=self.fake.request)
        self.http_patch.start()
        self.storage_patch = patch.object(main, "store", SupabaseStore("https://fake.supabase.co", "sb_secret_test"))
        self.storage_patch.start()
        self.env = patch.dict(os.environ, {"API_ACCESS_TOKEN": ""})
        self.env.start()
        self.clock = patch.object(
            main, "today_dhaka", return_value=datetime(2026, 11, 12, 15, 30, tzinfo=main.DST)
        )
        self.clock.start()
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self.clock.stop()
        self.env.stop()
        self.storage_patch.stop()
        self.http_patch.stop()

    def test_register_verify_enroll_report_and_health(self):
        self.assertEqual(self.client.get("/health").json()["storage"], "supabase")
        made = self.client.post("/api/register", json=reg()).json()
        self.assertEqual(made["status"], "success")
        token = made["card_token"]
        self.assertEqual(len(token), 18)
        self.assertEqual(self.fake.students["STU-1"]["card_token"], token)
        self.assertNotEqual(token, "STU-1")
        self.assertEqual(self.client.post("/api/register", json=reg()).status_code, 409)
        self.assertEqual(self.client.post("/api/verify-attendance", json=check(token)).json()["status"], "success")
        self.assertIn(
            "ইতিমধ্যে", self.client.post("/api/verify-attendance", json=check("STU-1")).json()["reason"]
        )
        self.assertEqual(self.client.get("/api/attendance").json()[0]["student_id"], "STU-1")
        self.assertEqual(self.client.get("/api/students").json()[0]["card_token"], token)
        self.fake.students["LEGACY"] = {
            "student_id": "LEGACY", "name": "Legacy", "class_name": "7", "section": "A", "roll_no": "9",
            "card_token": "legacy-token", "face_descriptor": None, "active": True,
            "valid_until": None, "session": "2025",
        }
        enrolled = self.client.post("/api/enroll-face", json=check("legacy-token"))
        self.assertEqual(enrolled.status_code, 200)
        self.assertEqual(enrolled.json()["student_id"], "LEGACY")
        self.assertEqual(self.fake.students["LEGACY"]["face_descriptor"], FACE)
        self.assertTrue(any(call["method"] == "PATCH" and call["params"]["student_id"] == "eq.LEGACY"
                            for call in self.fake.calls))
        self.assertEqual(self.client.post("/api/verify-attendance", json=check("legacy-token")).json()["status"], "success")
        self.fake.students["LEGACY"]["face_descriptor"] = ["bad"] * 128
        rows = self.client.get("/api/students").json()
        self.assertFalse(next(row for row in rows if row["student_id"] == "LEGACY")["has_face"])
        self.assertIn("face data নেই", self.client.post("/api/verify-attendance", json=check("legacy-token")).json()["reason"])

    def test_special_student_ids_and_db_failure(self):
        special = 'STU,(1):"\\'
        self.assertEqual(self.client.post("/api/register", json=reg(special)).status_code, 200)
        self.assertEqual(self.client.post("/api/verify-attendance", json=check(special)).json()["status"], "success")
        self.fake.fail = True
        self.assertEqual(self.client.get("/api/students").status_code, 503)
        self.assertEqual(self.client.get("/api/attendance").status_code, 503)
        self.assertEqual(self.client.post("/api/register", json=reg("OTHER")).status_code, 503)
        self.assertEqual(self.client.post("/api/verify-attendance", json=check("OTHER")).status_code, 503)
        self.assertEqual(self.client.post("/api/enroll-face", json=check("OTHER")).status_code, 503)

    def test_large_supabase_results_are_paged(self):
        for n in range(1002):
            student_id = f"STU-{n:04d}"
            self.fake.students[student_id] = {
                "student_id": student_id, "name": "Same", "class_name": "5", "section": "",
                "roll_no": "", "card_token": f"TOKEN-{n:04d}", "face_descriptor": None,
                "active": True, "valid_until": None, "session": "2026",
            }
            self.fake.attendance[(student_id, DAY)] = {
                "student_id": student_id, "name": "Same", "date": DAY, "time": "15:30:00",
                "status": "Present", "method": "face+qr",
            }
        ids = [r["student_id"] for r in self.client.get("/api/students").json()]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), 1002)
        report = self.client.get("/api/attendance").json()
        self.assertEqual(len(report), 1002)
        self.assertEqual([r["student_id"] for r in report], sorted(ids))
        for table in ("students", "attendance"):
            offsets = [c["params"]["offset"] for c in self.fake.calls
                       if c["method"] == "GET" and c["table"] == table]
            self.assertEqual(offsets, ["0", "500", "1000"])


if __name__ == "__main__":
    unittest.main()
