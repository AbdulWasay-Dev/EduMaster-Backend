"""
Classes API endpoints
"""
import logging
import string
import random
import uuid
from typing import Dict, Optional
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
    subject_id: Optional[str] = None
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
    subject_id: Optional[str] = None
    subject_area: Optional[str] = None
    academic_year: Optional[str] = None
    is_active: Optional[bool] = True
    teacher_id: Optional[str] = None
    class_code: Optional[str] = None
    max_students: Optional[int] = 100
    allow_student_signup: Optional[bool] = True
    created_at: str


def _class_to_dict(r: dict, fallback_teacher_id: str = None, subject_id: str = None) -> dict:
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "description": r.get("description", ""),
        "grade_level": r.get("grade_level"),
        "subject_id": subject_id,
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


async def _get_subject_map_for_teacher(db, teacher_id: str) -> Dict[str, str]:
    async with db.connection() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (class_id) class_id, id
            FROM subjects
            WHERE teacher_id = $1 AND class_id IS NOT NULL
            ORDER BY class_id, created_at ASC, name ASC
            """,
            uuid.UUID(teacher_id),
        )
    return {str(row["class_id"]): str(row["id"]) for row in rows}


async def _validate_subject_owner(db, subject_id: Optional[str], teacher_id: str) -> Optional[str]:
    if not subject_id:
        return None
    try:
        subject_uuid = uuid.UUID(subject_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid subject_id")

    async with db.connection() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM subjects WHERE id = $1 AND teacher_id = $2",
            subject_uuid,
            uuid.UUID(teacher_id),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Subject not found")
    return str(row["id"])


async def _assign_subject_to_class(db, subject_id: str, class_id: str, teacher_id: str) -> None:
    async with db.connection() as conn:
        await conn.execute(
            """
            UPDATE subjects
            SET class_id = $1, updated_at = NOW()
            WHERE id = $2 AND teacher_id = $3
            """,
            uuid.UUID(class_id),
            uuid.UUID(subject_id),
            uuid.UUID(teacher_id),
        )


@router.post("/", response_model=ClassResponse)
async def create_class(
    class_data: ClassCreate,
    current_user: dict = Depends(require_teacher())
):
    """Create a new class"""
    try:
        db = await get_database()
        subject_id = await _validate_subject_owner(db, class_data.subject_id, current_user["id"])
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

        if subject_id:
            await _assign_subject_to_class(db, subject_id, str(created["id"]), current_user["id"])

        # Fire notification
        try:
            from services.notification_service import notify
            await notify(
                teacher_id=current_user["id"],
                title="Class created",
                message=f'Class "{class_data.name}" has been created and is ready for students.',
                notification_type="class_created",
                metadata={"class_id": str(created["id"]), "class_name": class_data.name},
            )
        except Exception:
            pass

        return _class_to_dict(created, current_user["id"], subject_id)
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
        subject_map = await _get_subject_map_for_teacher(db, current_user["id"])
        return {
            "classes": [_class_to_dict(r, current_user["id"], subject_map.get(str(r["id"]))) for r in rows]
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
        
        subject_map = await _get_subject_map_for_teacher(db, current_user["id"])
        return _class_to_dict(class_obj, current_user["id"], subject_map.get(str(class_obj["id"])))
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
        subject_id = await _validate_subject_owner(db, payload.subject_id, current_user["id"])
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

        if subject_id:
            await _assign_subject_to_class(db, subject_id, class_id, current_user["id"])

        subject_map = await _get_subject_map_for_teacher(db, current_user["id"])
        return _class_to_dict(updated, current_user["id"], subject_id or subject_map.get(str(updated["id"])))
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
