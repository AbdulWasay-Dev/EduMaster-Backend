"""
Classes API endpoints
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.security import get_current_teacher, require_teacher
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


class ClassCreate(BaseModel):
    """Class creation model"""
    name: str
    description: str = ""
    grade_level: Optional[str] = None
    subject_area: Optional[str] = None
    academic_year: Optional[str] = None


class ClassResponse(BaseModel):
    """Class response model"""
    id: str
    name: str
    description: str
    grade_level: Optional[str] = None
    subject_area: Optional[str] = None
    academic_year: Optional[str] = None
    is_active: Optional[bool] = True
    teacher_id: Optional[str] = None
    created_at: str


@router.post("/", response_model=ClassResponse)
async def create_class(
    class_data: ClassCreate,
    current_user: dict = Depends(require_teacher())
):
    """Create a new class"""
    try:
        db = await get_database()
        payload = {
            "teacher_id": current_user["id"],
            "name": class_data.name,
            "description": class_data.description,
            "grade_level": class_data.grade_level,
            "subject_area": class_data.subject_area,
            "academic_year": class_data.academic_year,
            "is_active": True,
        }
        created = await db.create_class(payload)
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create class")
        return ClassResponse(
            id=str(created["id"]),
            name=created["name"],
            description=created.get("description", ""),
            grade_level=created.get("grade_level"),
            subject_area=created.get("subject_area"),
            academic_year=created.get("academic_year"),
            is_active=created.get("is_active", True),
            teacher_id=str(created["teacher_id"]) if created.get("teacher_id") else str(current_user["id"]),
            created_at=str(created["created_at"]),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating class: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/")
async def list_classes(current_user: dict = Depends(require_teacher())):
    """List teacher's classes"""
    try:
        db = await get_database()
        rows = await db.get_classes(current_user["id"])
        return {
            "classes": [
                {
                    "id": str(r["id"]),
                    "name": r["name"],
                    "description": r.get("description", ""),
                    "grade_level": r.get("grade_level"),
                    "subject_area": r.get("subject_area"),
                    "academic_year": r.get("academic_year"),
                    "is_active": r.get("is_active", True),
                    "teacher_id": str(r["teacher_id"]) if r.get("teacher_id") else str(current_user["id"]),
                    "created_at": str(r["created_at"]),
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error(f"Error listing classes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{class_id}")
async def get_class(
    class_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Get class by ID"""
    try:
        db = await get_database()
        
        # Verify teacher has access to the class
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")
        
        class_obj = await db.get_class(class_id)
        if not class_obj:
            raise HTTPException(status_code=404, detail="Class not found")
        
        return {
            "id": str(class_obj["id"]),
            "name": class_obj["name"],
            "description": class_obj.get("description", ""),
            "grade_level": class_obj.get("grade_level"),
            "subject_area": class_obj.get("subject_area"),
            "academic_year": class_obj.get("academic_year"),
            "is_active": class_obj.get("is_active", True),
            "teacher_id": str(class_obj["teacher_id"]) if class_obj.get("teacher_id") else str(current_user["id"]),
            "created_at": str(class_obj["created_at"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting class {class_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{class_id}", response_model=ClassResponse)
async def update_class(
    class_id: str,
    payload: ClassCreate,
    current_user: dict = Depends(require_teacher())
):
    """Update a class"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")

        import uuid
        async with db.connection() as conn:
            row = await conn.fetchrow(
                """
                UPDATE classes
                SET name = $1, description = $2, grade_level = $3, subject_area = $4, academic_year = $5, updated_at = NOW()
                WHERE id = $6
                RETURNING *
                """,
                payload.name,
                payload.description,
                payload.grade_level,
                payload.subject_area,
                payload.academic_year,
                uuid.UUID(class_id),
            )
            updated = dict(row) if row else None
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update class")
        return ClassResponse(
            id=str(updated["id"]),
            name=updated["name"],
            description=updated.get("description", ""),
            grade_level=updated.get("grade_level"),
            subject_area=updated.get("subject_area"),
            academic_year=updated.get("academic_year"),
            is_active=updated.get("is_active", True),
            teacher_id=str(updated["teacher_id"]) if updated.get("teacher_id") else str(current_user["id"]),
            created_at=str(updated["created_at"]),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating class {class_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{class_id}")
async def delete_class(
    class_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Delete a class"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")

        import uuid
        async with db.connection() as conn:
            await conn.execute("DELETE FROM classes WHERE id = $1", uuid.UUID(class_id))
        return {"deleted": True, "class_id": class_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting class {class_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
