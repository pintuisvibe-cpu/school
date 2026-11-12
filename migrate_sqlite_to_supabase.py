"""Copy existing SQLite data (attendance.db) into the Supabase project.

Usage:
    export SUPABASE_URL="https://<project-ref>.supabase.co"
    export SUPABASE_SERVICE_KEY="<service_role key>"
    python migrate_sqlite_to_supabase.py attendance.db

What it does:
* reads students + attendance from the local SQLite file
* inserts missing students into Supabase, keeping their card tokens so already
  printed QR cards keep working
* copies attendance rows day by day, skipping duplicates

It is safe to run more than once: existing students/days are skipped.
Raw face images were never stored, only the 128-number descriptors.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from storage import (
    DuplicateAttendance,
    DuplicateStudent,
    StorageError,
    SupabaseStore,
)


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def descriptor(raw: Any) -> list[float]:
    if not raw:
        return []
    value = json.loads(raw) if isinstance(raw, str) else raw
    return [float(v) for v in value] if isinstance(value, list) else []


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python migrate_sqlite_to_supabase.py <attendance.db>")
        return 2

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        print("SUPABASE_URL এবং SUPABASE_SERVICE_KEY environment variable সেট করুন।")
        return 2

    db_path = Path(sys.argv[1]).expanduser()
    if not db_path.exists():
        print(f"SQLite ফাইল পাওয়া যায়নি: {db_path}")
        return 2

    store = SupabaseStore(url, key)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "students" not in tables:
        print("এই ফাইলে students টেবিল নেই।")
        return 2

    student_columns = columns(conn, "students")
    has_face = "face_descriptor" in student_columns
    has_token = "card_token" in student_columns
    select = "student_id,name,class_name"
    select += ",face_descriptor" if has_face else ""
    select += ",card_token" if has_token else ""

    added = skipped = 0
    for row in conn.execute(f"SELECT {select} FROM students ORDER BY student_id"):
        token = (row["card_token"] if has_token else "") or None
        face = descriptor(row["face_descriptor"] if has_face else None)
        if store.find_student(row["student_id"]):
            # Student already in Supabase; only top up missing face data.
            if face:
                existing = store.find_student(row["student_id"])
                if existing and not existing.get("face_descriptor"):
                    store.enroll_face(row["student_id"], face)
                    print(f"  face যোগ হয়েছে: {row['student_id']}")
            skipped += 1
            continue
        if not face:
            print(f"  বাদ: {row['student_id']} (face data নেই, পরে enroll-face করুন)")
            skipped += 1
            continue
        try:
            store.register_student(
                row["student_id"], row["name"], row["class_name"], face, card_token=token
            )
            added += 1
        except DuplicateStudent:
            skipped += 1
        except StorageError as exc:
            print(f"  ব্যর্থ: {row['student_id']} — {exc}")
            skipped += 1

    attendance_added = attendance_skipped = 0
    if "attendance" in tables:
        for row in conn.execute(
            "SELECT student_id,name,date,time FROM attendance ORDER BY date,time"
        ):
            try:
                store.record_attendance(
                    row["student_id"], row["name"], row["date"], row["time"]
                )
                attendance_added += 1
            except (DuplicateAttendance, StorageError):
                attendance_skipped += 1

    print(
        f"শিক্ষার্থী: {added} যোগ হয়েছে, {skipped} বাদ/আগেই ছিল। "
        f"উপস্থিতি: {attendance_added} যোগ হয়েছে, {attendance_skipped} বাদ/আগেই ছিল।"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
