from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, date, timedelta

from utils.security import get_current_user
from services.database import get_database, DatabaseService

router = APIRouter()

# ─── Models ───────────────────────────────────────────────────────────────────

class AttendanceEntry(BaseModel):
    student_id: str
    status: str  # 'present', 'absent', 'late', 'excused'
    remarks: Optional[str] = None

class AttendanceBatch(BaseModel):
    class_id: str
    subject_id: str
    date: str
    entries: List[AttendanceEntry]

class AttendanceRecordResponse(BaseModel):
    id: str
    student_id: str
    status: str
    remarks: Optional[str] = None
    date: str

# ─── Helper ───────────────────────────────────────────────────────────────────

def _fmt(records: List[dict]) -> List[dict]:
    """Stringify date/timestamp fields so JSON serialisation never fails."""
    for r in records:
        for key in ("date", "created_at", "updated_at"):
            if r.get(key) is not None:
                r[key] = str(r[key])
    return records


# ─── Basic CRUD ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def get_attendance(
    class_id: str,
    subject_id: str,
    date: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Get attendance for a specific class, subject, and date."""
    records = await db.get_attendance_records(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        date=date
    )
    return _fmt(records)


@router.post("/", response_model=dict)
async def submit_attendance(
    batch: AttendanceBatch,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Submit or update attendance for a batch of students."""
    teacher_id = current_user["id"]
    success_count = 0
    failed_count = 0

    for entry in batch.entries:
        data = {
            "teacher_id": teacher_id,
            "class_id": batch.class_id,
            "subject_id": batch.subject_id,
            "student_id": entry.student_id,
            "date": batch.date,
            "status": entry.status,
            "remarks": entry.remarks,
        }
        res = await db.upsert_attendance_record(data)
        if res:
            success_count += 1
        else:
            failed_count += 1

    return {
        "status": "success",
        "message": f"Successfully updated {success_count} records.",
        "failed": failed_count,
    }


# ─── Range / History Queries ──────────────────────────────────────────────────

@router.get("/range", response_model=List[dict])
async def get_attendance_range(
    class_id: str,
    subject_id: str,
    start_date: str,
    end_date: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Get all attendance records for a date range."""
    records = await db.get_attendance_range(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    return _fmt(records)


@router.get("/history", response_model=List[dict])
async def get_attendance_history(
    class_id: str,
    subject_id: str,
    limit: int = Query(default=30, le=90),
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    Return the last *limit* distinct session dates that have attendance records,
    together with the per-date summary (present/absent/late/excused counts).
    """
    data = await db.get_attendance_history(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        limit=limit,
    )
    return data


# ─── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics/class", response_model=dict)
async def get_class_analytics(
    class_id: str,
    subject_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    Full analytics for a class/subject:
    - Overall totals (present / absent / late / excused)
    - Attendance rate per session (for trend charts)
    - Status distribution
    - Students with attendance < 75%
    - Most-absent students
    """
    # Default to the last 30 days if no range provided
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()

    analytics = await db.get_class_attendance_analytics(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    return analytics


@router.get("/analytics/student/{student_id}", response_model=dict)
async def get_student_analytics(
    student_id: str,
    class_id: str,
    subject_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    Detailed attendance analytics for a single student:
    - Total sessions, present/absent/late/excused counts
    - Attendance percentage
    - Full record list for the range
    - Monthly breakdown
    """
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=90)).isoformat()

    analytics = await db.get_student_attendance_analytics(
        teacher_id=current_user["id"],
        student_id=student_id,
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    return analytics


@router.get("/analytics/overview", response_model=dict)
async def get_attendance_overview(
    class_id: str,
    subject_id: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    High-level overview: total sessions taken, overall attendance %, 
    students below threshold, heatmap data for last 12 weeks.
    """
    overview = await db.get_attendance_overview(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
    )
    return overview


@router.get("/students/summary", response_model=List[dict])
async def get_students_summary(
    class_id: str,
    subject_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    Per-student attendance summary for a class/subject:
    returns each student's present/absent/late/excused count and attendance %.
    """
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=90)).isoformat()

    summary = await db.get_students_attendance_summary(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    return summary
