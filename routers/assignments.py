"""
Assignments API endpoints
Teacher CRUD + publish/close + submissions + AI grading
"""
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from utils.security import require_teacher
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    title: str
    subject_id: str
    class_id: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    total_marks: int = 10
    due_date: Optional[str] = None  # ISO datetime string
    grading_rubric: Optional[str] = None
    auto_grade: bool = True
    status: str = "draft"


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    total_marks: Optional[int] = None
    due_date: Optional[str] = None
    grading_rubric: Optional[str] = None
    auto_grade: Optional[bool] = None


class OverrideRequest(BaseModel):
    teacher_override_marks: Optional[float] = None
    teacher_remarks: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _serialize_assignment(a: dict) -> dict:
    return {
        "id": str(a["id"]),
        "teacher_id": str(a["teacher_id"]),
        "subject_id": str(a["subject_id"]),
        "class_id": str(a["class_id"]),
        "title": a.get("title", ""),
        "description": a.get("description"),
        "instructions": a.get("instructions"),
        "total_marks": a.get("total_marks", 10),
        "due_date": str(a["due_date"]) if a.get("due_date") else None,
        "attachment_url": a.get("attachment_url"),
        "attachment_filename": a.get("attachment_filename"),
        "grading_rubric": a.get("grading_rubric"),
        "auto_grade": a.get("auto_grade", True),
        "status": a.get("status", "draft"),
        "created_at": str(a["created_at"]),
        "updated_at": str(a["updated_at"]) if a.get("updated_at") else None,
    }


def _serialize_submission(s: dict) -> dict:
    import json
    files = s.get("submission_files", [])
    if isinstance(files, str):
        try:
            files = json.loads(files)
        except Exception:
            files = []
    rubric = s.get("ai_rubric_breakdown")
    if isinstance(rubric, str):
        try:
            rubric = json.loads(rubric)
        except Exception:
            rubric = None

    return {
        "id": str(s["id"]),
        "assignment_id": str(s["assignment_id"]),
        "student_account_id": str(s["student_account_id"]),
        "student_name": s.get("student_name", ""),
        "student_email": s.get("student_email", ""),
        "roll_number": s.get("roll_number"),
        "class_id": str(s["class_id"]),
        "submission_text": s.get("submission_text"),
        "submission_files": files,
        "marks_obtained": float(s["marks_obtained"]) if s.get("marks_obtained") is not None else None,
        "max_marks": s.get("max_marks"),
        "percentage": float(s["percentage"]) if s.get("percentage") is not None else None,
        "grade": s.get("grade"),
        "ai_feedback": s.get("ai_feedback"),
        "ai_rubric_breakdown": rubric,
        "teacher_remarks": s.get("teacher_remarks"),
        "teacher_override_marks": float(s["teacher_override_marks"]) if s.get("teacher_override_marks") is not None else None,
        "status": s.get("status", "pending"),
        "submitted_at": str(s["submitted_at"]) if s.get("submitted_at") else None,
        "graded_at": str(s["graded_at"]) if s.get("graded_at") else None,
        "created_at": str(s["created_at"]),
    }


async def _verify_teacher_class(db, current_user, class_id):
    classes = await db.get_classes(current_user["id"])
    class_ids = [str(c["id"]) for c in classes]
    if class_id not in class_ids:
        raise HTTPException(status_code=403, detail="Access denied to this class")


# ─── Teacher Endpoints ────────────────────────────────────────────────────────

@router.post("/")
async def create_assignment(
    data: AssignmentCreate,
    current_user: dict = Depends(require_teacher()),
):
    """Create a new assignment (draft by default)"""
    try:
        db = await get_database()
        await _verify_teacher_class(db, current_user, data.class_id)

        due_date = None
        if data.due_date:
            try:
                due_date = datetime.fromisoformat(data.due_date.replace("Z", "+00:00"))
            except Exception:
                due_date = None

        payload = {
            "teacher_id": current_user["id"],
            "subject_id": data.subject_id,
            "class_id": data.class_id,
            "title": data.title,
            "description": data.description,
            "instructions": data.instructions,
            "total_marks": data.total_marks,
            "due_date": due_date,
            "grading_rubric": data.grading_rubric,
            "auto_grade": data.auto_grade,
            "status": data.status,
        }
        created = await db.create_assignment(payload)
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create assignment")
        return _serialize_assignment(created)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/")
async def list_assignments(
    class_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(require_teacher()),
):
    """List assignments with optional filters"""
    try:
        db = await get_database()
        rows = await db.get_assignments(
            current_user["id"],
            class_id=class_id,
            subject_id=subject_id,
            status=status,
        )
        return [_serialize_assignment(r) for r in rows]
    except Exception as e:
        logger.error(f"Error listing assignments: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{assignment_id}")
async def get_assignment(
    assignment_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Get assignment detail"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        return _serialize_assignment(a)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/{assignment_id}")
async def update_assignment(
    assignment_id: str,
    data: AssignmentUpdate,
    current_user: dict = Depends(require_teacher()),
):
    """Update assignment"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        update_data = {}
        for field in ["title", "description", "instructions", "total_marks", "grading_rubric", "auto_grade"]:
            val = getattr(data, field, None)
            if val is not None:
                update_data[field] = val
        if data.due_date is not None:
            try:
                update_data["due_date"] = datetime.fromisoformat(data.due_date.replace("Z", "+00:00"))
            except Exception:
                pass

        updated = await db.update_assignment(assignment_id, update_data)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update assignment")
        return _serialize_assignment(updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{assignment_id}")
async def delete_assignment(
    assignment_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Delete assignment"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        await db.delete_assignment(assignment_id)
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{assignment_id}/publish")
async def publish_assignment(
    assignment_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Publish assignment to students"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        updated = await db.update_assignment(assignment_id, {"status": "published"})
        return _serialize_assignment(updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error publishing assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{assignment_id}/close")
async def close_assignment(
    assignment_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Close submissions for assignment"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        updated = await db.update_assignment(assignment_id, {"status": "closed"})
        return _serialize_assignment(updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error closing assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{assignment_id}/upload-attachment")
async def upload_assignment_attachment(
    assignment_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_teacher()),
):
    """Upload assignment attachment file"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        # Store file
        upload_dir = os.path.join("uploads", "assignments", assignment_id)
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, file.filename)
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        updated = await db.update_assignment(assignment_id, {
            "attachment_url": f"/static/uploads/assignments/{assignment_id}/{file.filename}",
            "attachment_filename": file.filename,
        })
        return _serialize_assignment(updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading attachment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ─── Submission Endpoints ─────────────────────────────────────────────────────

@router.get("/{assignment_id}/submissions")
async def list_submissions(
    assignment_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """List all submissions for an assignment"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        submissions = await db.get_assignment_submissions(assignment_id)
        return [_serialize_submission(s) for s in submissions]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing submissions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{assignment_id}/submissions/{submission_id}")
async def get_submission_detail(
    assignment_id: str,
    submission_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Get one submission detail"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        sub = await db.get_assignment_submission(submission_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")
        return _serialize_submission(sub)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting submission: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{assignment_id}/submissions/{submission_id}/grade")
async def grade_single_submission(
    assignment_id: str,
    submission_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Trigger AI grading for a single submission"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        sub = await db.get_assignment_submission(submission_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        # Mark as grading
        await db.update_assignment_submission(submission_id, {"status": "grading"})

        # Run AI grading
        from services.assignment_grader import grade_assignment_submission
        result = await grade_assignment_submission(a, sub)

        # Update submission with grading results
        update_data = {
            "marks_obtained": result["marks_obtained"],
            "max_marks": a.get("total_marks", 10),
            "percentage": result["percentage"],
            "grade": result["grade"],
            "ai_feedback": result["ai_feedback"],
            "ai_rubric_breakdown": result.get("rubric_breakdown", []),
            "status": "graded",
            "graded_at": datetime.utcnow(),
        }
        updated = await db.update_assignment_submission(submission_id, update_data)

        # Record score in ledger
        await db.create_student_score({
            "student_account_id": str(sub["student_account_id"]),
            "class_id": str(a["class_id"]),
            "subject_id": str(a["subject_id"]),
            "score_type": "assignment",
            "reference_id": str(a["id"]),
            "title": a["title"],
            "marks_obtained": result["marks_obtained"],
            "max_marks": a.get("total_marks", 10),
            "percentage": result["percentage"],
            "grade": result["grade"],
        })

        return _serialize_submission(updated) if updated else {"status": "graded"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error grading submission: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/{assignment_id}/submissions/{submission_id}/override")
async def override_submission(
    assignment_id: str,
    submission_id: str,
    data: OverrideRequest,
    current_user: dict = Depends(require_teacher()),
):
    """Teacher overrides marks/remarks for a submission"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        update_data = {}
        if data.teacher_override_marks is not None:
            update_data["teacher_override_marks"] = data.teacher_override_marks
        if data.teacher_remarks is not None:
            update_data["teacher_remarks"] = data.teacher_remarks
        update_data["status"] = "returned"

        updated = await db.update_assignment_submission(submission_id, update_data)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update submission")
        return _serialize_submission(updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error overriding submission: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{assignment_id}/grade-all")
async def grade_all_submissions(
    assignment_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Batch AI-grade all ungraded submitted submissions"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        submissions = await db.get_assignment_submissions(assignment_id)
        to_grade = [s for s in submissions if s.get("status") == "submitted"]

        if not to_grade:
            return {"graded_count": 0, "message": "No ungraded submissions found"}

        from services.assignment_grader import grade_assignment_submission
        graded_count = 0

        for sub in to_grade:
            try:
                await db.update_assignment_submission(str(sub["id"]), {"status": "grading"})
                result = await grade_assignment_submission(a, sub)
                update_data = {
                    "marks_obtained": result["marks_obtained"],
                    "max_marks": a.get("total_marks", 10),
                    "percentage": result["percentage"],
                    "grade": result["grade"],
                    "ai_feedback": result["ai_feedback"],
                    "ai_rubric_breakdown": result.get("rubric_breakdown", []),
                    "status": "graded",
                    "graded_at": datetime.utcnow(),
                }
                await db.update_assignment_submission(str(sub["id"]), update_data)

                await db.create_student_score({
                    "student_account_id": str(sub["student_account_id"]),
                    "class_id": str(a["class_id"]),
                    "subject_id": str(a["subject_id"]),
                    "score_type": "assignment",
                    "reference_id": str(a["id"]),
                    "title": a["title"],
                    "marks_obtained": result["marks_obtained"],
                    "max_marks": a.get("total_marks", 10),
                    "percentage": result["percentage"],
                    "grade": result["grade"],
                })
                graded_count += 1
            except Exception as ge:
                logger.error(f"Error grading submission {sub['id']}: {ge}")
                await db.update_assignment_submission(str(sub["id"]), {"status": "submitted"})

        return {"graded_count": graded_count, "total": len(to_grade)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error batch grading: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{assignment_id}/analytics")
async def get_assignment_analytics(
    assignment_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """Get assignment analytics: avg score, grade distribution, submission rate"""
    try:
        db = await get_database()
        a = await db.get_assignment(assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(a["teacher_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        submissions = await db.get_assignment_submissions(assignment_id)
        total_students = len(await db.get_student_accounts_by_class(str(a["class_id"]), verified_only=True))
        submitted = [s for s in submissions if s.get("status") not in ("pending",)]
        graded = [s for s in submissions if s.get("status") in ("graded", "returned")]

        avg_score = 0
        grade_dist = {}
        if graded:
            scores = [float(s["marks_obtained"]) for s in graded if s.get("marks_obtained") is not None]
            avg_score = sum(scores) / len(scores) if scores else 0
            for s in graded:
                g = s.get("grade", "N/A")
                grade_dist[g] = grade_dist.get(g, 0) + 1

        pass_count = len([s for s in graded if s.get("percentage") and float(s["percentage"]) >= 50])

        return {
            "total_students": total_students,
            "submitted_count": len(submitted),
            "graded_count": len(graded),
            "submission_rate": round(len(submitted) / max(total_students, 1) * 100, 1),
            "avg_score": round(avg_score, 2),
            "pass_rate": round(pass_count / max(len(graded), 1) * 100, 1),
            "grade_distribution": grade_dist,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting assignment analytics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
