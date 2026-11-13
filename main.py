"""School attendance API with browser-side face extraction (no paid face API).

Face images are processed in the browser. Only a 128-number descriptor is sent
to the server, which compares it against the stored descriptor. Original face
images are not uploaded or saved. Descriptors are still biometric data and
must be protected and used only with appropriate consent.

Storage: Supabase Postgres when SUPABASE_URL + SUPABASE_SERVICE_KEY are set,
otherwise a local SQLite file (see storage.py).
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from storage import (
    DuplicateAttendance,
    DuplicateStudent,
    StorageError,
    build_store,
    descriptor_has_expired,
    normalize_descriptor,
)

BASE_DIR = Path(__file__).resolve().parent
DISTANCE_THRESHOLD = float(os.getenv("FACE_DISTANCE_THRESHOLD", "0.50"))
if not math.isfinite(DISTANCE_THRESHOLD) or DISTANCE_THRESHOLD <= 0:
    raise ValueError("FACE_DISTANCE_THRESHOLD must be a finite positive number")
DST = ZoneInfo("Asia/Dhaka")

store = build_store()
if os.getenv("RENDER", "").lower() == "true" and not os.getenv("API_ACCESS_TOKEN", "").strip():
    raise RuntimeError(
        "Render-এ API_ACCESS_TOKEN দরকার। Render Environment-এ একটি শক্তিশালী "
        "টোকেন দিন বা Blueprint-এর generateValue ব্যবহার করুন।"
    )

app = FastAPI(title="School Attendance", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    # Accepts either a Student ID or the QR card token, so old ID-based QR
    # codes keep working after the switch to opaque card tokens.
    student_id: str = Field(min_length=1, max_length=128)
    face_descriptor: list[float]


class FaceEnrollment(BaseModel):
    student_id: str = Field(min_length=1, max_length=64)
    face_descriptor: list[float]


def checked_descriptor(values: list[float]) -> list[float]:
    descriptor = normalize_descriptor(values)
    if not descriptor:
        raise HTTPException(status_code=422, detail="মুখের descriptor সঠিক নয়। ছবি আবার তুলুন।")
    return descriptor


def today_dhaka() -> datetime:
    return datetime.now(DST)


def parse_descriptor(raw: object) -> list[float]:
    """Supabase returns jsonb; SQLite stores JSON text. Both may be corrupt."""
    return normalize_descriptor(raw)


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
    return {
        "status": "ok",
        "face_extraction": "browser-local",
        "face_matching": "server-descriptor-distance",
        "storage": store.describe(),
        "timezone": "Asia/Dhaka",
        "auth_required": bool(os.getenv("API_ACCESS_TOKEN", "").strip()),
    }


@app.post("/api/register", dependencies=[Depends(auth)])
def register_student(payload: StudentRegistration):
    student_id = payload.student_id.strip()
    name = payload.name.strip()
    class_name = payload.class_name.strip()
    if not student_id or not name or not class_name:
        raise HTTPException(status_code=422, detail="Student ID, নাম ও শ্রেণি পূরণ করুন।")
    descriptor = checked_descriptor(payload.face_descriptor)
    try:
        return {"status": "success", **store.register_student(student_id, name, class_name, descriptor)}
    except DuplicateStudent:
        raise HTTPException(status_code=409, detail="এই Student ID আগে থেকেই নিবন্ধিত।") from None
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/enroll-face", dependencies=[Depends(auth)])
def enroll_face(payload: FaceEnrollment):
    """Attach a face descriptor to a student who was registered without one."""
    code = payload.student_id.strip()
    if not code:
        raise HTTPException(status_code=422, detail="Student ID বা কার্ড দিন।")
    descriptor = checked_descriptor(payload.face_descriptor)
    try:
        # find_student matches Student ID or card token; enroll by the real ID
        # so passing a card token works too.
        student = store.find_student(code)
        if not student:
            raise HTTPException(status_code=404, detail="Student ID পাওয়া যায়নি।")
        student_id = student["student_id"]
        if not store.enroll_face(student_id, descriptor):
            raise HTTPException(status_code=404, detail="Student ID পাওয়া যায়নি।")
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "success", "student_id": student_id}


@app.post("/api/verify-attendance", dependencies=[Depends(auth)])
def verify_attendance(payload: AttendanceCheck):
    code = payload.student_id.strip()
    if not code:
        raise HTTPException(status_code=422, detail="Student ID বা কার্ড দিন।")
    probe = checked_descriptor(payload.face_descriptor)
    try:
        student = store.find_student(code)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not student:
        return {"status": "failed", "reason": "Student ID বা কার্ড পাওয়া যায়নি।"}
    if student.get("active") is False:
        return {"status": "failed", "reason": "এই শিক্ষার্থীর কার্ড নিষ্ক্রিয় করা হয়েছে।"}
    reference = parse_descriptor(student.get("face_descriptor"))
    if not reference:
        return {
            "status": "failed",
            "reason": "এই শিক্ষার্থীর face data নেই; অ্যাডমিন প্যানেল থেকে Face যোগ করুন।",
        }
    if descriptor_has_expired(str(student.get("valid_until") or ""), today_dhaka().date()):
        return {"status": "failed", "reason": "কার্ডের মেয়াদ শেষ হয়েছে। অফিসে যোগাযোগ করুন।"}
    distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(probe, reference)))
    if distance > DISTANCE_THRESHOLD:
        return {"status": "failed", "reason": "Face Mismatch!", "distance": round(distance, 4)}
    now = today_dhaka()
    try:
        store.record_attendance(
            student["student_id"],
            student["name"],
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
        )
    except DuplicateAttendance:
        return {"status": "failed", "reason": "আজকের উপস্থিতি ইতিমধ্যে রেকর্ড করা হয়েছে।"}
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "success",
        "student_name": student["name"],
        "distance": round(distance, 4),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
    }


@app.get("/api/attendance", dependencies=[Depends(auth)])
def get_attendance(day: str | None = None):
    target = day or today_dhaka().strftime("%Y-%m-%d")
    try:
        if date.fromisoformat(target).isoformat() != target:
            raise ValueError("not YYYY-MM-DD")
    except ValueError:
        raise HTTPException(status_code=422, detail="তারিখ YYYY-MM-DD ফরম্যাটে দিন।") from None
    try:
        rows = store.attendance_for(target)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return rows


@app.get("/api/students", dependencies=[Depends(auth)])
def get_students():
    try:
        return store.list_students()
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
