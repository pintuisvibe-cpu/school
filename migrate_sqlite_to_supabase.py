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

import os
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

from storage import (
    DuplicateAttendance,
    StorageError,
    SupabaseStore,
    normalize_descriptor,
)


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def descriptor(raw: Any) -> list[float]:
    """Bad legacy face data should be enrolled later, not abort migration."""
    return normalize_descriptor(raw)


def valid_date_or_none(raw: Any) -> str | None:
    if not raw:
        return None
    value = str(raw)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("valid_until must be YYYY-MM-DD")
    return value


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
        conn.close()
        return 2

    student_columns = columns(conn, "students")
    has_face = "face_descriptor" in student_columns
    has_token = "card_token" in student_columns
    optional_columns = ("section", "roll_no", "active", "valid_until", "session")
    select = "student_id,name,class_name"
    select += ",face_descriptor" if has_face else ""
    select += ",card_token" if has_token else ""
    select += "".join(f",{col}" for col in optional_columns if col in student_columns)

    added = skipped = failed = 0
    for row in conn.execute(f"SELECT {select} FROM students ORDER BY student_id"):
        token = (row["card_token"] if has_token else "") or None
        face = descriptor(row["face_descriptor"] if has_face else None)
        metadata = {col: row[col] for col in optional_columns if col in student_columns}
        if "active" in metadata:
            metadata["active"] = bool(metadata["active"])
        if "valid_until" in metadata:
            try:
                metadata["valid_until"] = valid_date_or_none(metadata["valid_until"])
            except ValueError:
                print(f"  ব্যর্থ: {row['student_id']} — valid_until তারিখ YYYY-MM-DD নয়।")
                failed += 1
                continue
        if "session" in metadata and not metadata["session"]:
            del metadata["session"]
        try:
            existing = store.find_student(row["student_id"])
            if existing and existing.get("student_id") != row["student_id"]:
                # The lookup also accepts card tokens; this collision would
                # shadow the existing student's printed QR. Report it.
                raise StorageError("Student ID অন্য শিক্ষার্থীর কার্ড টোকেনের সাথে মিলে গেছে।")
        except StorageError as exc:
            print(f"  ব্যর্থ: {row['student_id']} — {exc}")
            failed += 1
            continue
        if existing:
            # Do not silently invalidate already printed SQLite QR cards when
            # the target project has the same ID but a different card token.
            if token and existing.get("card_token") != token:
                print(f"  ব্যর্থ: {row['student_id']} — Supabase-এ card_token ভিন্ন; কার্ড যাচাই করুন।")
                failed += 1
                continue
            # Student already in Supabase; only top up missing face data.
            if face and not normalize_descriptor(existing.get("face_descriptor")):
                try:
                    if not store.enroll_face(row["student_id"], face):
                        raise StorageError("face যোগ করা যায়নি।")
                    print(f"  face যোগ হয়েছে: {row['student_id']}")
                except StorageError as exc:
                    print(f"  ব্যর্থ: {row['student_id']} — {exc}")
                    failed += 1
                    continue
            skipped += 1
            continue
        # Insert even without face data: the admin "Face যোগ" flow needs the
        # student row to exist in Supabase first, otherwise enroll-face 404s.
        try:
            store.register_student(
                row["student_id"], row["name"], row["class_name"], face,
                card_token=token, metadata=metadata,
            )
            if not face:
                print(f"  যোগ হয়েছে (face নেই, পরে enroll-face করুন): {row['student_id']}")
            added += 1
        except StorageError as exc:
            print(f"  ব্যর্থ: {row['student_id']} — {exc}")
            failed += 1

    attendance_added = attendance_skipped = attendance_failed = 0
    if "attendance" in tables:
        attendance_columns = columns(conn, "attendance")
        has_status = "status" in attendance_columns
        has_method = "method" in attendance_columns
        select = "student_id,name,date,time"
        select += ",status" if has_status else ""
        select += ",method" if has_method else ""
        for row in conn.execute(f"SELECT {select} FROM attendance ORDER BY date,time"):
            try:
                store.record_attendance(
                    row["student_id"], row["name"], row["date"], row["time"],
                    status=(row["status"] if has_status else None) or "Present",
                    method=(row["method"] if has_method else None) or "face+qr",
                )
                attendance_added += 1
            except DuplicateAttendance:
                attendance_skipped += 1
            except StorageError as exc:
                print(f"  উপস্থিতি ব্যর্থ: {row['student_id']} ({row['date']}) — {exc}")
                attendance_failed += 1

    conn.close()
    print(
        f"শিক্ষার্থী: {added} যোগ হয়েছে, {skipped} আগেই ছিল, {failed} ব্যর্থ। "
        f"উপস্থিতি: {attendance_added} যোগ হয়েছে, {attendance_skipped} আগেই ছিল, "
        f"{attendance_failed} ব্যর্থ।"
    )
    return 1 if failed or attendance_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
