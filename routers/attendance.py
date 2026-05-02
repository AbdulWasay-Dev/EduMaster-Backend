from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.security import get_current_user
from services.database import get_database, DatabaseService

router = APIRouter()

# Models
class AttendanceEntry(BaseModel):
    student_id: str
    status: str # 'present', 'absent', 'late', 'excused'
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

@router.get("/", response_model=List[dict])
async def get_attendance(
    class_id: str,
    subject_id: str,
    date: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Get attendance for a specific class, subject, and date"""
    records = await db.get_attendance_records(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        date=date
    )
    
    # Format response dates
    for r in records:
        if r.get("date"):
            r["date"] = str(r["date"])
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
        if r.get("updated_at"):
            r["updated_at"] = str(r["updated_at"])
            
    return records

@router.post("/", response_model=dict)
async def submit_attendance(
    batch: AttendanceBatch,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Submit or update attendance for a batch of students"""
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
            "remarks": entry.remarks
        }
        res = await db.upsert_attendance_record(data)
        if res:
            success_count += 1
        else:
            failed_count += 1
            
    return {
        "status": "success",
        "message": f"Successfully updated {success_count} records.",
        "failed": failed_count
    }
