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


@router.post("/enroll")
async def enroll_student(
    enrollment_data: StudentEnrollment,
    current_user: dict = Depends(get_current_teacher)
):
    """Enroll student in a class (for student self-enrollment)"""
    try:
        # This endpoint is for students to self-enroll using a class code
        # Implementation would require class codes and student authentication
        # For now, return a placeholder response
        return {"message": "Student enrollment functionality coming soon"}
        
    except Exception as e:
        logger.error(f"Error in student enrollment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/classes")
async def get_student_classes(current_user: dict = Depends(get_current_teacher)):
    """Get student's enrolled classes (for student view)"""
    try:
        # This endpoint is for students to view their enrolled classes
        # Implementation would require student authentication
        # For now, return a placeholder response
        return {"classes": []}
        
    except Exception as e:
        logger.error(f"Error getting student classes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
