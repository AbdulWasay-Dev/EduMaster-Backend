"""
Classes API endpoints
"""
import logging
import string
import random
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


class ClassSettingsUpdate(BaseModel):
    """Class settings update"""
    max_students: Optional[int] = None
    allow_student_signup: Optional[bool] = None
    is_active: Optional[bool] = None


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
    class_code: Optional[str] = None
    max_students: Optional[int] = 100
    allow_student_signup: Optional[bool] = True
    created_at: str


def _class_to_dict(r: dict, fallback_teacher_id: str = None) -> dict:
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "description": r.get("description", ""),
        "grade_level": r.get("grade_level"),
        "subject_area": r.get("subject_area"),
        "academic_year": r.get("academic_year"),
        "is_active": r.get("is_active", True),
        "teacher_id": str(r["teacher_id"]) if r.get("teacher_id") else (fallback_teacher_id or ""),
        "class_code": r.get("class_code"),
        "max_students": r.get("max_students", 100),
        "allow_student_signup": r.get("allow_student_signup", True),
        "created_at": str(r["created_at"]),
    }


def _generate_class_code(name: str) -> str:
    prefix = "".join(c for c in name.upper().replace(" ", "") if c.isalnum())[:6]
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{suffix}"


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
            "classes": [_class_to_dict(r, current_user["id"]) for r in rows]
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
        
        return _class_to_dict(class_obj, current_user["id"])
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


# ==================== Phase 2 — Class Code & Overview ====================

@router.post("/{class_id}/generate-code")
async def generate_class_code(
    class_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Generate or regenerate a class join code"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")

        cls = await db.get_class(class_id)
        if not cls:
            raise HTTPException(status_code=404, detail="Class not found")

        # Generate unique code, retry on collision
        for _ in range(10):
            code = _generate_class_code(cls["name"])
            existing = await db.get_class_by_code(code)
            if not existing:
                break
        else:
            raise HTTPException(status_code=500, detail="Failed to generate unique code")

        updated = await db.set_class_code(class_id, code)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to set class code")

        return {"class_id": class_id, "class_code": code}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating class code: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{class_id}/code")
async def get_class_code(
    class_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Get current class code"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")

        cls = await db.get_class(class_id)
        if not cls:
            raise HTTPException(status_code=404, detail="Class not found")

        return {
            "class_id": class_id,
            "class_code": cls.get("class_code"),
            "allow_student_signup": cls.get("allow_student_signup", True),
            "max_students": cls.get("max_students", 100),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting class code: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/{class_id}/settings")
async def update_class_settings(
    class_id: str,
    settings_data: ClassSettingsUpdate,
    current_user: dict = Depends(require_teacher()),
):
    """Update class settings (max_students, allow_student_signup, is_active)"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")

        update_data = {}
        if settings_data.max_students is not None:
            update_data["max_students"] = settings_data.max_students
        if settings_data.allow_student_signup is not None:
            update_data["allow_student_signup"] = settings_data.allow_student_signup
        if settings_data.is_active is not None:
            update_data["is_active"] = settings_data.is_active

        if not update_data:
            cls = await db.get_class(class_id)
            return _class_to_dict(cls, current_user["id"])

        updated = await db.update_class(class_id, update_data)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update class settings")
        return _class_to_dict(updated, current_user["id"])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating class settings: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{class_id}/overview")
async def get_class_overview(
    class_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Full class overview: subjects, students, assignments, papers counts"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")

        cls = await db.get_class(class_id)
        if not cls:
            raise HTTPException(status_code=404, detail="Class not found")

        overview = await db.get_class_overview(class_id)
        return {
            **_class_to_dict(cls, current_user["id"]),
            **overview,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting class overview: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{class_id}/pending-students")
async def get_pending_students(
    class_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """List student accounts pending verification"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")

        pending = await db.get_pending_student_accounts(class_id)
        return [
            {
                "id": str(s["id"]),
                "full_name": s.get("full_name", ""),
                "email": s.get("email", ""),
                "roll_number": s.get("roll_number"),
                "phone": s.get("phone"),
                "joined_at": str(s["joined_at"]) if s.get("joined_at") else None,
                "is_verified": s.get("is_verified", False),
            }
            for s in pending
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pending students: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
