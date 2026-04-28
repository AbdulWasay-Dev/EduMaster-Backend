"""
Students API endpoints
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.security import get_current_teacher, require_teacher
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


class StudentCreate(BaseModel):
    """Student creation model"""
    student_name: str
    student_id: Optional[str] = None  # School student ID
    email: Optional[str] = None
    phone: Optional[str] = None
    class_id: str


class StudentUpdate(BaseModel):
    """Student update model"""
    student_name: Optional[str] = None
    student_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class StudentResponse(BaseModel):
    """Student response model"""
    id: str
    name: str = ""  # Frontend primary field
    student_name: str = ""
    student_id: Optional[str] = None
    roll_number: Optional[str] = None  # alias for student_id
    email: Optional[str] = None
    phone: Optional[str] = None
    class_id: str
    created_at: str
    updated_at: str = ""


class StudentEnrollment(BaseModel):
    """Student enrollment model"""
    class_code: str


@router.post("/", response_model=StudentResponse)
async def create_student(
    student_data: StudentCreate,
    current_user: dict = Depends(require_teacher())
):
    """Create a new student"""
    try:
        logger.info(f"Creating student: {student_data.student_name}")
        
        db = await get_database()
        
        # Verify teacher has access to the class
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        
        if student_data.class_id not in class_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this class"
            )
        
        # Create student
        payload = {
            "student_name": student_data.student_name,
            "student_id": student_data.student_id,
            "email": student_data.email,
            "phone": student_data.phone,
            "class_id": student_data.class_id,
        }
        
        created = await db.create_student(payload)
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create student")
        
        return StudentResponse(
            id=str(created["id"]),
            name=created["student_name"],
            student_name=created["student_name"],
            student_id=created.get("student_id"),
            roll_number=created.get("student_id"),
            email=created.get("email"),
            phone=created.get("phone"),
            class_id=str(created["class_id"]),
            created_at=str(created["created_at"]),
            updated_at=str(created.get("updated_at", created["created_at"]))
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating student: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/")
async def list_students(
    class_id: Optional[str] = None,
    current_user: dict = Depends(require_teacher())
):
    """List students, optionally filtered by class_id query parameter"""
    try:
        db = await get_database()

        if class_id:
            # Verify access to the class
            classes = await db.get_classes(current_user["id"])
            class_ids = [str(c["id"]) for c in classes]
            if class_id not in class_ids:
                raise HTTPException(status_code=403, detail="Access denied to this class")
            students = await db.get_students(class_id)
        else:
            # Return all students across all teacher's classes
            classes = await db.get_classes(current_user["id"])
            students = []
            for cls in classes:
                cls_students = await db.get_students(str(cls["id"]))
                students.extend(cls_students)

        return [
            StudentResponse(
                id=str(s["id"]),
                name=s["student_name"],
                student_name=s["student_name"],
                student_id=s.get("student_id"),
                roll_number=s.get("student_id"),
                email=s.get("email"),
                phone=s.get("phone"),
                class_id=str(s["class_id"]),
                created_at=str(s["created_at"]),
                updated_at=str(s.get("updated_at", s["created_at"]))
            )
            for s in students
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing students: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/class/{class_id}", response_model=List[StudentResponse])
async def get_students_by_class(
    class_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Get all students in a class"""
    try:
        db = await get_database()
        
        # Verify teacher has access to the class
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        
        if class_id not in class_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this class"
            )
        
        students = await db.get_students(class_id)
        
        return [
            StudentResponse(
                id=str(student["id"]),
                name=student["student_name"],
                student_name=student["student_name"],
                student_id=student.get("student_id"),
                roll_number=student.get("student_id"),
                email=student.get("email"),
                phone=student.get("phone"),
                class_id=str(student["class_id"]),
                created_at=str(student["created_at"]),
                updated_at=str(student.get("updated_at", student["created_at"]))
            )
            for student in students
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting students for class {class_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Get student by ID"""
    try:
        db = await get_database()
        
        student = await db.get_student(student_id)
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")
        
        # Verify teacher has access to the student's class
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        
        if str(student["class_id"]) not in class_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this student"
            )
        
        return StudentResponse(
            id=str(student["id"]),
            name=student["student_name"],
            student_name=student["student_name"],
            student_id=student.get("student_id"),
            roll_number=student.get("student_id"),
            email=student.get("email"),
            phone=student.get("phone"),
            class_id=str(student["class_id"]),
            created_at=str(student["created_at"]),
            updated_at=str(student.get("updated_at", student["created_at"]))
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting student {student_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    student_data: StudentUpdate,
    current_user: dict = Depends(require_teacher())
):
    """Update student information"""
    try:
        db = await get_database()
        
        # Get existing student
        existing_student = await db.get_student(student_id)
        if not existing_student:
            raise HTTPException(status_code=404, detail="Student not found")
        
        # Verify teacher has access to the student's class
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        
        if str(existing_student["class_id"]) not in class_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this student"
            )
        
        # Prepare update data
        update_data = {}
        if student_data.student_name is not None:
            update_data["student_name"] = student_data.student_name
        if student_data.student_id is not None:
            update_data["student_id"] = student_data.student_id
        if student_data.email is not None:
            update_data["email"] = student_data.email
        if student_data.phone is not None:
            update_data["phone"] = student_data.phone
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No data to update")
        
        # Update student
        updated = await db.update_student(student_id, update_data)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update student")
        
        return StudentResponse(
            id=str(updated["id"]),
            name=updated["student_name"],
            student_name=updated["student_name"],
            student_id=updated.get("student_id"),
            roll_number=updated.get("student_id"),
            email=updated.get("email"),
            phone=updated.get("phone"),
            class_id=str(updated["class_id"]),
            created_at=str(updated["created_at"]),
            updated_at=str(updated.get("updated_at", updated["created_at"]))
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating student {student_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{student_id}")
async def delete_student(
    student_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Delete a student"""
    try:
        db = await get_database()
        
        # Get existing student
        existing_student = await db.get_student(student_id)
        if not existing_student:
            raise HTTPException(status_code=404, detail="Student not found")
        
        # Verify teacher has access to the student's class
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        
        if str(existing_student["class_id"]) not in class_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this student"
            )
        
        # Delete student
        success = await db.delete_student(student_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete student")
        
        return {"message": "Student deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting student {student_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ─── Student Account Management (Teacher) ────────────────────────

class BulkStudentItem(BaseModel):
    student_name: str
    email: str
    student_id: Optional[str] = None


class BulkImportRequest(BaseModel):
    class_id: str
    students: List[BulkStudentItem]


@router.patch("/accounts/{account_id}/verify")
async def verify_student_account(
    account_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Verify (approve) a pending student account"""
    try:
        db = await get_database()
        account = await db.get_student_account(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Student account not found")

        # Verify teacher owns the class
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if str(account.get("class_id")) not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied")

        updated = await db.update_student_account(account_id, {"is_verified": True})
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to verify student")

        return {"message": "Student account verified", "id": account_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying student account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/accounts/{account_id}/reject")
async def reject_student_account(
    account_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Reject (deactivate) a pending student account"""
    try:
        db = await get_database()
        account = await db.get_student_account(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Student account not found")

        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if str(account.get("class_id")) not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied")

        updated = await db.update_student_account(account_id, {"is_active": False})
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to reject student")

        return {"message": "Student account rejected", "id": account_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting student account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/accounts/class/{class_id}")
async def list_student_accounts(
    class_id: str,
    verified_only: bool = False,
    current_user: dict = Depends(require_teacher()),
):
    """List student accounts for a class"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied")

        accounts = await db.get_student_accounts_by_class(class_id, verified_only=verified_only)
        return [
            {
                "id": str(a["id"]),
                "full_name": a.get("full_name", ""),
                "email": a.get("email", ""),
                "is_verified": a.get("is_verified", False),
                "is_active": a.get("is_active", True),
                "created_at": str(a.get("created_at", "")),
            }
            for a in accounts
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing student accounts: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/bulk-import")
async def bulk_import_students(
    data: BulkImportRequest,
    current_user: dict = Depends(require_teacher()),
):
    """Bulk import students into a class (creates student records)"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if data.class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied")

        created = []
        errors = []
        for item in data.students:
            try:
                student = await db.create_student({
                    "student_name": item.student_name,
                    "email": item.email,
                    "student_id": item.student_id,
                    "class_id": data.class_id,
                })
                if student:
                    created.append(str(student["id"]))
                else:
                    errors.append({"name": item.student_name, "error": "Failed to create"})
            except Exception as inner_e:
                errors.append({"name": item.student_name, "error": str(inner_e)})

        return {
            "imported": len(created),
            "failed": len(errors),
            "errors": errors[:20],  # cap to 20
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk import error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{student_id}/scores")
async def get_student_scores(
    student_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Get all graded scores for a student (teacher view)"""
    try:
        db = await get_database()
        student = await db.get_student(student_id)
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if str(student["class_id"]) not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied")

        scores = await db.get_student_scores(student_id)
        return scores or []
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting student scores: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{student_id}/submissions")
async def get_student_submissions(
    student_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Get all submissions for a student (teacher view)"""
    try:
        db = await get_database()
        student = await db.get_student(student_id)
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if str(student["class_id"]) not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied")

        submissions = await db.get_student_submissions(student_id)
        return [
            {
                "id": str(s["id"]),
                "assignment_id": str(s.get("assignment_id", "")),
                "assignment_title": s.get("title", ""),
                "status": s.get("status", ""),
                "submitted_at": str(s["submitted_at"]) if s.get("submitted_at") else None,
                "marks_obtained": s.get("marks_obtained"),
                "percentage": s.get("percentage"),
                "grade": s.get("grade"),
            }
            for s in submissions
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting student submissions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
