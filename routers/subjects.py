"""
Subjects API endpoints
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.security import get_current_teacher, require_teacher
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


class SubjectCreate(BaseModel):
    """Subject creation model"""
    name: str
    description: str = ""
    class_id: Optional[str] = None
    # Additional fields accepted from frontend (stored if column exists)
    grade_level: Optional[str] = None
    subject_area: Optional[str] = None
    academic_year: Optional[str] = None


class SubjectResponse(BaseModel):
    """Subject response model"""
    id: str
    name: str
    description: str
    teacher_id: Optional[str] = None
    class_id: Optional[str] = None
    is_active: bool = True
    grade_level: Optional[str] = None
    subject_area: Optional[str] = None
    academic_year: Optional[str] = None
    created_at: str


@router.post("/", response_model=SubjectResponse)
async def create_subject(
    subject_data: SubjectCreate,
    current_user: dict = Depends(require_teacher())
):
    """Create a new subject"""
    try:
        db = await get_database()
        
        subject_data_dict = {
            "teacher_id": current_user["id"],
            "name": subject_data.name,
            "description": subject_data.description,
            "class_id": subject_data.class_id
        }
        
        subject = await db.create_subject(subject_data_dict)
        if not subject:
            raise HTTPException(status_code=500, detail="Failed to create subject")
        
        return SubjectResponse(
            id=str(subject["id"]),
            name=subject["name"],
            description=subject.get("description", ""),
            teacher_id=str(subject["teacher_id"]) if subject.get("teacher_id") else str(current_user["id"]),
            class_id=str(subject["class_id"]) if subject.get("class_id") else None,
            is_active=subject.get("is_active", True),
            grade_level=subject.get("grade_level"),
            subject_area=subject.get("subject_area"),
            academic_year=subject.get("academic_year"),
            created_at=str(subject["created_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating subject: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/", response_model=List[SubjectResponse])
async def list_subjects(current_user: dict = Depends(require_teacher())):
    """List user's subjects"""
    try:
        db = await get_database()
        subjects = await db.get_subjects(current_user["id"])
        
        return [
            SubjectResponse(
                id=str(subject["id"]),
                name=subject["name"],
                description=subject.get("description", ""),
                teacher_id=str(subject["teacher_id"]) if subject.get("teacher_id") else None,
                class_id=str(subject["class_id"]) if subject.get("class_id") else None,
                is_active=subject.get("is_active", True),
                grade_level=subject.get("grade_level"),
                subject_area=subject.get("subject_area"),
                academic_year=subject.get("academic_year"),
                created_at=str(subject["created_at"])
            )
            for subject in subjects
        ]
        
    except Exception as e:
        logger.error(f"Error listing subjects: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def _build_subject_response(subject: dict, teacher_id: Optional[str] = None) -> SubjectResponse:
    """Helper to build SubjectResponse from a DB row dict"""
    return SubjectResponse(
        id=str(subject["id"]),
        name=subject["name"],
        description=subject.get("description", ""),
        teacher_id=str(subject["teacher_id"]) if subject.get("teacher_id") else teacher_id,
        class_id=str(subject["class_id"]) if subject.get("class_id") else None,
        is_active=subject.get("is_active", True),
        grade_level=subject.get("grade_level"),
        subject_area=subject.get("subject_area"),
        academic_year=subject.get("academic_year"),
        created_at=str(subject["created_at"]),
    )


@router.get("/{subject_id}", response_model=SubjectResponse)
async def get_subject(
    subject_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Get a subject by ID"""
    try:
        db = await get_database()
        subject = await db.get_subject(subject_id)
        if not subject:
            raise HTTPException(status_code=404, detail="Subject not found")
        if str(subject["teacher_id"]) != str(current_user["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this subject")
        return _build_subject_response(subject)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting subject {subject_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: str,
    payload: SubjectCreate,
    current_user: dict = Depends(require_teacher())
):
    """Update a subject"""
    try:
        db = await get_database()
        subject = await db.get_subject(subject_id)
        if not subject:
            raise HTTPException(status_code=404, detail="Subject not found")
        if str(subject["teacher_id"]) != str(current_user["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this subject")

        import uuid
        async with db.connection() as conn:
            row = await conn.fetchrow(
                """
                UPDATE subjects
                SET name = $1, description = $2, class_id = $3, updated_at = NOW()
                WHERE id = $4
                RETURNING *
                """,
                payload.name,
                payload.description,
                uuid.UUID(payload.class_id) if payload.class_id else None,
                uuid.UUID(subject_id),
            )
            updated = dict(row) if row else None

        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update subject")
        return _build_subject_response(updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating subject {subject_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{subject_id}")
async def delete_subject(
    subject_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Delete a subject"""
    try:
        db = await get_database()
        subject = await db.get_subject(subject_id)
        if not subject:
            raise HTTPException(status_code=404, detail="Subject not found")
        if str(subject["teacher_id"]) != str(current_user["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this subject")

        import uuid
        async with db.connection() as conn:
            await conn.execute("DELETE FROM subjects WHERE id = $1", uuid.UUID(subject_id))

        return {"deleted": True, "subject_id": subject_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting subject {subject_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
