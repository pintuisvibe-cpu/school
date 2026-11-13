"""Storage backends for the school attendance app.

Two interchangeable implementations:

* ``SupabaseStore`` — talks to the Supabase REST (PostgREST) API with the
  service-role key. Used when ``SUPABASE_URL`` and ``SUPABASE_SERVICE_KEY`` are
  set, which is the recommended setup for deployment: the database survives
  restarts and is shared by every device.
* ``SqliteStore`` — a zero-config local fallback for development and demos.

Both expose the same small interface, so ``main.py`` does not care which one is
active. Errors are translated into a few storage-level exceptions.
"""
from __future__ import annotations

import json
import math
import os
import secrets
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

DHAKA = ZoneInfo("Asia/Dhaka")
MAX_DESCRIPTOR_COMPONENT = 10.0
DEFAULT_SCHOOL_SETTINGS = {
    "school_name": "স্কুল অ্যাটেনডেন্স",
    "school_name_en": "School Attendance",
    "eiin": "",
    "address": "",
    "phone": "",
    "email": "",
    "theme_color": "#1d4ed8",
    "principal_name": "",
    "session": "",
    "card_valid_until": "",
}


def normalize_descriptor(raw: Any) -> list[float]:
    """Parse browser / Supabase / SQLite faces; reject corrupt or unsafe data."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list) or len(raw) != 128:
        return []
    try:
        values = [float(value) for value in raw]
    except (ValueError, TypeError, OverflowError):
        return []
    # face-api components are small. Huge values could overflow when squared
    # during distance calculation, or produce a non-JSON Inf result.
    return values if all(math.isfinite(v) and abs(v) <= MAX_DESCRIPTOR_COMPONENT for v in values) else []


# PostgREST treats commas, dots, colons and parentheses as filter syntax, so
# values containing them must be double-quoted inside an ``eq.`` filter.
_FILTER_SPECIAL = set(',.:()')


def eq_filter(value: str) -> str:
    if any(char in _FILTER_SPECIAL for char in value) or '"' in value or "\\" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'eq."{escaped}"'
    return f"eq.{value}"


# Columns fetched for every student lookup. ``face_descriptor`` is a jsonb
# column in Supabase and a JSON string in SQLite.
STUDENT_FIELDS = (
    "student_id,name,class_name,section,roll_no,card_token,"
    "face_descriptor,active,valid_until,session"
)
PAGE_SIZE = 500  # Under the usual PostgREST max_rows limit (1,000).


class StorageError(RuntimeError):
    """Unrecoverable storage problem (network, permissions, bad response)."""


class DuplicateStudent(StorageError):
    """The Student ID is already registered."""


class DuplicateAttendance(StorageError):
    """Attendance for this student and date already exists."""


class StudentNotFound(StorageError):
    """No student matched the given ID or card token."""


def _pg_error_code(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("code") or "")
    return ""


class SupabaseStore:
    """Postgres-backed storage through Supabase's PostgREST endpoint."""

    name = "supabase"

    def __init__(self, url: str, service_key: str) -> None:
        if service_key.startswith("sb_publishable_"):
            raise ValueError("SUPABASE_SERVICE_KEY-তে publishable key নয়, sb_secret_ বা service_role key দিন।")
        self.rest_url = url.rstrip("/") + "/rest/v1"
        self.service_key = service_key

    # -- low level ---------------------------------------------------------
    def _request(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, str] | None = None,
        json_body: Any = None,
        prefer: str = "return=representation",
    ) -> list[dict[str, Any]]:
        headers = {
            "apikey": self.service_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": prefer,
        }
        # New sb_secret_ keys are NOT JWTs. Sending them in Authorization:
        # Bearer makes PostgREST reject the request; legacy service_role JWTs
        # still need the Bearer header for RLS bypass.
        if not self.service_key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.service_key}"
        try:
            response = requests.request(
                method,
                f"{self.rest_url}/{table}",
                params=params,
                json=json_body,
                headers=headers,
                timeout=20,
            )
        except requests.RequestException as exc:  # pragma: no cover - network only
            raise StorageError("Supabase-এ সংযোগ করা যায়নি। ইন্টারনেট সংযোগ দেখুন।") from exc

        if response.status_code >= 400:
            code = _pg_error_code(response)
            if code == "23505":
                raise DuplicateStudent("duplicate")
            if response.status_code in (401, 403):
                raise StorageError(
                    "Supabase key অনুমতি দিচ্ছে না। SUPABASE_SERVICE_KEY ঠিক আছে কিনা দেখুন।"
                )
            raise StorageError(f"Supabase error {response.status_code}: {response.text[:200]}")

        if not response.content:
            return []
        try:
            data = response.json()
        except ValueError as exc:
            raise StorageError("Supabase থেকে ভুল response পাওয়া গেছে।") from exc
        if isinstance(data, dict):  # pragma: no cover - defensive
            return [data]
        if not isinstance(data, list):
            raise StorageError("Supabase থেকে ভুল response পাওয়া গেছে।")
        return data

    def _all_rows(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """PostgREST caps result sets; fetch every page for reports and lists."""
        rows: list[dict[str, Any]] = []
        while True:
            page = self._request("GET", table, params={
                **params, "limit": str(PAGE_SIZE), "offset": str(len(rows)),
            })
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows

    # -- interface ---------------------------------------------------------
    def describe(self) -> str:
        return "supabase"

    def register_student(
        self,
        student_id: str,
        name: str,
        class_name: str,
        descriptor: list[float],
        card_token: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Always generate an opaque card token server-side (like SQLite does).
        # Relying on a DB default would silently fall back to the Student ID
        # as the QR payload, defeating the purpose of the opaque token.
        token = card_token or secrets.token_hex(9)
        payload = {
            "student_id": student_id,
            "name": name,
            "class_name": class_name,
            # Empty list means "no face yet"; enroll-face can add it later.
            "face_descriptor": descriptor or None,
            "card_token": token,
            "session": str(datetime.now(DHAKA).year),
        }
        # Used by the SQLite migration; do not overwrite the DB defaults
        # for fields that were not present in the source database.
        if metadata:
            payload.update({key: metadata[key] for key in (
                "section", "roll_no", "active", "valid_until", "session"
            ) if key in metadata})
        try:
            rows = self._request("POST", "students", json_body=payload)
        except DuplicateStudent:
            raise DuplicateStudent(student_id) from None
        if not rows:
            raise StorageError("শিক্ষার্থী সংরক্ষণ করা যায়নি।")
        row = rows[0]
        return {
            "student_id": row["student_id"],
            "student_name": row["name"],
            "card_token": row.get("card_token") or token,
        }

    def find_student(self, key: str) -> dict[str, Any] | None:
        for column in ("student_id", "card_token"):
            rows = self._request(
                "GET",
                "students",
                params={"select": STUDENT_FIELDS, column: eq_filter(key), "limit": "1"},
            )
            if rows:
                return rows[0]
        return None

    def list_students(self) -> list[dict[str, Any]]:
        rows = self._all_rows(
            "students",
            {"select": STUDENT_FIELDS, "order": "class_name.asc,name.asc,student_id.asc"},
        )
        return [self._public_row(row) for row in rows]

    def enroll_face(self, student_id: str, descriptor: list[float]) -> bool:
        rows = self._request(
            "PATCH",
            "students",
            params={"student_id": eq_filter(student_id)},
            json_body={"face_descriptor": descriptor},
        )
        return bool(rows)

    def record_attendance(
        self, student_id: str, name: str, day: str, clock: str,
        status: str = "Present", method: str = "face+qr",
    ) -> None:
        payload = {
            "student_id": student_id,
            "name": name,
            "date": day,
            "time": clock,
            "status": status,
            "method": method,
        }
        try:
            self._request("POST", "attendance", json_body=payload)
        except DuplicateStudent:
            raise DuplicateAttendance(student_id) from None

    def attendance_for(self, day: str) -> list[dict[str, Any]]:
        return self._all_rows(
            "attendance",
            {
                "select": "student_id,name,date,time,status,method",
                "date": f"eq.{day}",
                "order": "time.desc,student_id.asc",
            },
        )

    def school_settings(self) -> dict[str, Any]:
        defaults = {**DEFAULT_SCHOOL_SETTINGS, "session": str(datetime.now(DHAKA).year)}
        try:
            rows = self._request(
                "GET",
                "school_settings",
                params={
                    "select": (
                        "school_name,school_name_en,eiin,address,phone,email,"
                        "theme_color,principal_name,session,card_valid_until"
                    ),
                    "limit": "1",
                },
            )
        except StorageError:
            return defaults
        if not rows:
            return defaults
        row = rows[0]
        return {key: (row.get(key) or defaults[key]) for key in defaults}

    @staticmethod
    def _public_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "student_id": row["student_id"],
            "name": row["name"],
            "class_name": row["class_name"],
            "section": row.get("section") or "",
            "roll_no": row.get("roll_no") or "",
            "card_token": row.get("card_token") or "",
            "active": row.get("active", True),
            "valid_until": row.get("valid_until") or "",
            "session": row.get("session") or "",
            "has_face": bool(normalize_descriptor(row.get("face_descriptor"))),
        }


class SqliteStore:
    """Single-file SQLite storage, used when Supabase env vars are absent."""

    name = "sqlite"

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    section TEXT NOT NULL DEFAULT '',
                    roll_no TEXT NOT NULL DEFAULT '',
                    photo_path TEXT NOT NULL DEFAULT '',
                    face_descriptor TEXT,
                    card_token TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    valid_until TEXT NOT NULL DEFAULT '',
                    session TEXT NOT NULL DEFAULT ''
                )"""
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(students)")}
            if "face_descriptor" not in columns:
                conn.execute("ALTER TABLE students ADD COLUMN face_descriptor TEXT")
            if "photo_path" not in columns:
                conn.execute("ALTER TABLE students ADD COLUMN photo_path TEXT NOT NULL DEFAULT ''")
            if "card_token" not in columns:
                conn.execute("ALTER TABLE students ADD COLUMN card_token TEXT NOT NULL DEFAULT ''")
            # Keep SQLite in parity with Supabase so deactivation / expiry /
            # section / roll work the same in both backends.
            if "section" not in columns:
                conn.execute("ALTER TABLE students ADD COLUMN section TEXT NOT NULL DEFAULT ''")
            if "roll_no" not in columns:
                conn.execute("ALTER TABLE students ADD COLUMN roll_no TEXT NOT NULL DEFAULT ''")
            if "active" not in columns:
                conn.execute("ALTER TABLE students ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
            if "valid_until" not in columns:
                conn.execute("ALTER TABLE students ADD COLUMN valid_until TEXT NOT NULL DEFAULT ''")
            if "session" not in columns:
                conn.execute("ALTER TABLE students ADD COLUMN session TEXT NOT NULL DEFAULT ''")
            # Backfill tokens for rows created before cards were introduced.
            for row in conn.execute(
                "SELECT student_id FROM students WHERE card_token='' OR card_token IS NULL"
            ).fetchall():
                conn.execute(
                    "UPDATE students SET card_token=? WHERE student_id=?",
                    (secrets.token_hex(9), row["student_id"]),
                )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_card_token "
                "ON students(card_token)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Present',
                    method TEXT NOT NULL DEFAULT 'face+qr',
                    UNIQUE(student_id, date)
                )"""
            )
            attendance_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(attendance)")
            }
            if "method" not in attendance_columns:
                conn.execute(
                    "ALTER TABLE attendance ADD COLUMN method TEXT NOT NULL DEFAULT 'face+qr'"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)"
            )

    def describe(self) -> str:
        return "sqlite"

    def register_student(
        self,
        student_id: str,
        name: str,
        class_name: str,
        descriptor: list[float],
        card_token: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = card_token or secrets.token_hex(9)
        metadata = metadata or {}
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO students(student_id,name,class_name,section,roll_no,photo_path,"
                    "face_descriptor,card_token,active,valid_until,session) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        student_id,
                        name,
                        class_name,
                        metadata.get("section") or "",
                        metadata.get("roll_no") or "",
                        "",
                        json.dumps(descriptor, separators=(",", ":")) if descriptor else None,
                        token,
                        int(metadata.get("active", True)),
                        metadata.get("valid_until") or "",
                        metadata.get("session") or str(datetime.now(DHAKA).year),
                    ),
                )
            except sqlite3.IntegrityError:
                raise DuplicateStudent(student_id) from None
        return {"student_id": student_id, "student_name": name, "card_token": token}

    def find_student(self, key: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT student_id,name,class_name,section,roll_no,face_descriptor,card_token,"
                "active,valid_until,session FROM students "
                "WHERE student_id=? OR card_token=? "
                "ORDER BY CASE WHEN student_id=? THEN 0 ELSE 1 END LIMIT 1",
                (key, key, key),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        # SQLite stores booleans as 0/1; main.py checks `is False`, so convert.
        result["active"] = bool(result.get("active", 1))
        return result

    def list_students(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT student_id,name,class_name,section,roll_no,card_token,face_descriptor,"
                "active,valid_until,session FROM students "
                "ORDER BY class_name, name"
            ).fetchall()
        return [
            {
                "student_id": row["student_id"],
                "name": row["name"],
                "class_name": row["class_name"],
                "section": row["section"] or "",
                "roll_no": row["roll_no"] or "",
                "card_token": row["card_token"],
                "active": bool(row["active"]),
                "valid_until": row["valid_until"] or "",
                "session": row["session"] or "",
                "has_face": bool(normalize_descriptor(row["face_descriptor"])),
            }
            for row in rows
        ]

    def enroll_face(self, student_id: str, descriptor: list[float]) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE students SET face_descriptor=? WHERE student_id=?",
                (json.dumps(descriptor, separators=(",", ":")), student_id),
            )
        return cursor.rowcount > 0

    def record_attendance(
        self, student_id: str, name: str, day: str, clock: str,
        status: str = "Present", method: str = "face+qr",
    ) -> None:
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO attendance(student_id,name,date,time,status,method) "
                    "VALUES(?,?,?,?,?,?)",
                    (student_id, name, day, clock, status, method),
                )
            except sqlite3.IntegrityError:
                raise DuplicateAttendance(student_id) from None

    def attendance_for(self, day: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT student_id,name,date,time,status,method FROM attendance "
                "WHERE date=? ORDER BY time DESC",
                (day,),
            ).fetchall()
        return [dict(row) for row in rows]

    def school_settings(self) -> dict[str, Any]:
        return {**DEFAULT_SCHOOL_SETTINGS, "session": str(datetime.now(DHAKA).year)}


def build_store() -> SupabaseStore | SqliteStore:
    """Pick Supabase when configured, otherwise fall back to SQLite."""
    url = os.getenv("SUPABASE_URL", "").strip()
    key = (
        os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )
    if url and key:
        return SupabaseStore(url, key)
    if url and not key:
        raise RuntimeError(
            "SUPABASE_URL দেওয়া আছে কিন্তু SUPABASE_SERVICE_KEY নেই। "
            "অথবা দুটোই বাদ দিন, তাহলে লোকাল SQLite ব্যবহার হবে।"
        )
    if key and not url:
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY দেওয়া আছে কিন্তু SUPABASE_URL নেই। "
            "অথবা দুটোই বাদ দিন, তাহলে লোকাল SQLite ব্যবহার হবে।"
        )
    if os.getenv("RENDER", "").lower() == "true":
        raise RuntimeError(
            "Render-এ SQLite অস্থায়ী; SUPABASE_URL এবং SUPABASE_SERVICE_KEY "
            "Environment-এ সেট করুন, তারপর deploy করুন।"
        )
    base_dir = Path(__file__).resolve().parent
    data_dir = Path(os.getenv("DATA_DIR", str(base_dir))).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = os.getenv("SQLITE_PATH") or str(data_dir / "attendance.db")
    return SqliteStore(db_path)


def descriptor_has_expired(valid_until: str, today: date) -> bool:
    if not valid_until:
        return False
    try:
        parsed = date.fromisoformat(valid_until)
        return parsed.isoformat() != valid_until or parsed < today
    except ValueError:
        # Corrupt expiry dates must not grant a card unlimited validity.
        return True
