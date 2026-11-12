"""School attendance API with browser-side face matching (no paid face API/key).

Faces are processed in the browser. Only a 128-number face descriptor is sent to
this server; original face images are not uploaded or saved. Descriptors are still
biometric data and must be protected and used only with appropriate consent.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR))).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("SQLITE_PATH", str(DATA_DIR / "attendance.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DISTANCE_THRESHOLD = float(os.getenv("FACE_DISTANCE_THRESHOLD", "0.50"))

app = FastAPI(title="School Attendance", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            photo_path TEXT NOT NULL DEFAULT '',
            face_descriptor TEXT
        )""")
        # Migrate an older SQLite DB created by the earlier API-backed version.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(students)")}
        if "face_descriptor" not in columns:
            conn.execute("ALTER TABLE students ADD COLUMN face_descriptor TEXT")
        if "photo_path" not in columns:
            conn.execute("ALTER TABLE students ADD COLUMN photo_path TEXT NOT NULL DEFAULT ''")
        conn.execute("""CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Present',
            UNIQUE(student_id, date)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)")


init_db()


def auth(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Optional bearer-token gate; unset by default so no API key is needed."""
    expected = os.getenv("API_ACCESS_TOKEN", "").strip()
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")


class StudentRegistration(BaseModel):
    student_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    class_name: str = Field(min_length=1, max_length=80)
    face_descriptor: list[float]


class AttendanceCheck(BaseModel):
    student_id: str = Field(min_length=1, max_length=64)
    face_descriptor: list[float]


def checked_descriptor(values: list[float]) -> list[float]:
    if len(values) != 128 or not all(math.isfinite(float(v)) for v in values):
        raise HTTPException(status_code=422, detail="মুখের descriptor সঠিক নয়। ছবি আবার তুলুন।")
    return [float(v) for v in values]


def today_dhaka() -> datetime:
    return datetime.now(ZoneInfo("Asia/Dhaka"))


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "admin.html")


@app.get("/admin")
def admin_page():
    return FileResponse(BASE_DIR / "admin.html")


@app.get("/admin.html")
def admin_html():
    return FileResponse(BASE_DIR / "admin.html")


@app.get("/scanner")
def scanner_page():
    return FileResponse(BASE_DIR / "scanner.html")


@app.get("/scanner.html")
def scanner_html():
    return FileResponse(BASE_DIR / "scanner.html")


@app.get("/health")
def health():
    return {"status": "ok", "face_matching": "browser-local"}


@app.post("/api/register", dependencies=[Depends(auth)])
def register_student(payload: StudentRegistration):
    student_id = payload.student_id.strip()
    name = payload.name.strip()
    class_name = payload.class_name.strip()
    if not student_id or not name or not class_name:
        raise HTTPException(status_code=422, detail="Student ID, নাম ও শ্রেণি পূরণ করুন।")
    descriptor = checked_descriptor(payload.face_descriptor)
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO students(student_id,name,class_name,photo_path,face_descriptor) VALUES(?,?,?,?,?)",
                (student_id, name, class_name, "", json.dumps(descriptor, separators=(",", ":"))),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="এই Student ID আগে থেকেই নিবন্ধিত।")
    return {"status": "success", "student_id": student_id, "student_name": name}


@app.post("/api/verify-attendance", dependencies=[Depends(auth)])
def verify_attendance(payload: AttendanceCheck):
    student_id = payload.student_id.strip()
    probe = checked_descriptor(payload.face_descriptor)
    with get_db() as conn:
        student = conn.execute(
            "SELECT student_id,name,face_descriptor FROM students WHERE student_id=?", (student_id,)
        ).fetchone()
    if not student:
        return {"status": "failed", "reason": "Student ID পাওয়া যায়নি।"}
    if not student["face_descriptor"]:
        return {"status": "failed", "reason": "এই শিক্ষার্থীর face data নেই; আবার নিবন্ধন করুন।"}
    try:
        reference = checked_descriptor(json.loads(student["face_descriptor"]))
    except (ValueError, TypeError, json.JSONDecodeError):
        return {"status": "failed", "reason": "রেজিস্ট্রেশনের face data পড়া যাচ্ছে না।"}
    distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(probe, reference)))
    if distance > DISTANCE_THRESHOLD:
        return {"status": "failed", "reason": "Face Mismatch!", "distance": round(distance, 4)}
    now = today_dhaka()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO attendance(student_id,name,date,time,status) VALUES(?,?,?,?,?)",
                (student["student_id"], student["name"], now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), "Present"),
            )
    except sqlite3.IntegrityError:
        return {"status": "failed", "reason": "আজকের উপস্থিতি ইতিমধ্যে রেকর্ড করা হয়েছে।"}
    return {"status": "success", "student_name": student["name"], "distance": round(distance, 4)}


@app.get("/api/attendance", dependencies=[Depends(auth)])
def get_attendance():
    today = today_dhaka().strftime("%Y-%m-%d")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT student_id,name,date,time,status FROM attendance WHERE date=? ORDER BY time DESC", (today,)
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/students", dependencies=[Depends(auth)])
def get_students():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT student_id,name,class_name FROM students ORDER BY class_name,name"
        ).fetchall()
    return [dict(row) for row in rows]
