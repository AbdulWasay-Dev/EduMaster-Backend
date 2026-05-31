"""
Student Portal API endpoints
All endpoints require student authentication (role == "student").
"""
import logging
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from utils.security import require_student
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Response Models ───────────────────────────────────────────────
class StudentDashboard(BaseModel):
    student_name: str
    class_name: str
    class_id: str
    pending_assignments: int
    completed_assignments: int
    average_score: Optional[float] = None


class AssignmentListItem(BaseModel):
    id: str
    title: str
    subject_name: str
    due_date: Optional[str] = None
    total_marks: int
    status: str  # published, closed
    submission_status: str  # not_submitted, submitted, graded


class AssignmentDetail(BaseModel):
    id: str
    title: str
    instructions: Optional[str] = None
    subject_name: str
    due_date: Optional[str] = None
    total_marks: int
    status: str
    attachment_url: Optional[str] = None
    submission: Optional[dict] = None


class SubmissionCreate(BaseModel):
    submission_text: str


class SubmissionResponse(BaseModel):
    id: str
    assignment_id: str
    status: str
    submitted_at: Optional[str] = None
    marks_obtained: Optional[float] = None
    percentage: Optional[float] = None
    grade: Optional[str] = None
    ai_feedback: Optional[str] = None


class ScoreItem(BaseModel):
    id: str
    assignment_title: str
    subject_name: str
    marks_obtained: float
    total_marks: int
    percentage: float
    grade: str
    graded_at: Optional[str] = None


class SubjectItem(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    document_count: int = 0


# ─── Helpers ───────────────────────────────────────────────────────
async def _verify_student_class(db, student: dict) -> dict:
    """Get and verify the student's class exists"""
    class_id = str(student.get("class_id", ""))
    if not class_id:
        raise HTTPException(status_code=400, detail="Student not assigned to a class")
    cls = await db.get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    return cls


# ─── Dashboard ─────────────────────────────────────────────────────
@router.get("/dashboard", response_model=StudentDashboard)
async def student_dashboard(current_student: dict = Depends(require_student())):
    """Get student dashboard summary"""
    try:
        db = await get_database()
        cls = await _verify_student_class(db, current_student)
        class_id = str(cls["id"])
        student_id = str(current_student["id"])

        # Get all published/closed assignments for this class
        assignments = await db.get_assignments_by_class(class_id)
        active_assignments = [a for a in assignments if a.get("status") in ("published", "closed")]

        # Get student's submissions
        submissions = await db.get_student_submissions(student_id)
        submitted_ids = {str(s.get("assignment_id")) for s in submissions}
        graded = [s for s in submissions if s.get("status") == "graded"]

        pending = len([a for a in active_assignments if str(a["id"]) not in submitted_ids and a.get("status") == "published"])
        completed = len(submitted_ids)

        avg = None
        if graded:
            percents = [s.get("percentage", 0) for s in graded if s.get("percentage") is not None]
            if percents:
                avg = round(sum(percents) / len(percents), 2)

        return StudentDashboard(
            student_name=current_student.get("full_name", "Student"),
            class_name=cls.get("name", ""),
            class_id=class_id,
            pending_assignments=pending,
            completed_assignments=completed,
            average_score=avg,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Student dashboard error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ─── Assignments ───────────────────────────────────────────────────
@router.get("/assignments", response_model=List[AssignmentListItem])
async def list_student_assignments(current_student: dict = Depends(require_student())):
    """List all assignments visible to the student"""
    try:
        db = await get_database()
        cls = await _verify_student_class(db, current_student)
        class_id = str(cls["id"])
        student_id = str(current_student["id"])

        assignments = await db.get_assignments_by_class(class_id)
        visible = [a for a in assignments if a.get("status") in ("published", "closed")]

        # Preload submissions
        submissions = await db.get_student_submissions(student_id)
        sub_map = {str(s.get("assignment_id")): s for s in submissions}

        # Get subjects for names
        subjects = await db.get_subjects_by_class(class_id)
        subj_map = {str(s["id"]): s.get("name", "") for s in subjects}

        result = []
        for a in visible:
            aid = str(a["id"])
            sub = sub_map.get(aid)
            if sub:
                submission_status = sub.get("status", "submitted")
            else:
                submission_status = "not_submitted"

            result.append(AssignmentListItem(
                id=aid,
                title=a.get("title", ""),
                subject_name=subj_map.get(str(a.get("subject_id", "")), ""),
                due_date=str(a["due_date"]) if a.get("due_date") else None,
                total_marks=a.get("total_marks", 0),
                status=a.get("status", "draft"),
                submission_status=submission_status,
            ))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List student assignments error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/assignments/{assignment_id}", response_model=AssignmentDetail)
async def get_student_assignment(
    assignment_id: str,
    current_student: dict = Depends(require_student()),
):
    """Get assignment details (student view)"""
    try:
        db = await get_database()
        cls = await _verify_student_class(db, current_student)
        student_id = str(current_student["id"])

        assignment = await db.get_assignment(assignment_id)
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        # Verify assignment belongs to student's class
        if str(assignment.get("class_id")) != str(cls["id"]):
            raise HTTPException(status_code=403, detail="Not your class assignment")

        if assignment.get("status") not in ("published", "closed"):
            raise HTTPException(status_code=404, detail="Assignment not available")

        # Get subject name
        subjects = await db.get_subjects_by_class(str(cls["id"]))
        subj_map = {str(s["id"]): s.get("name", "") for s in subjects}
        subject_name = subj_map.get(str(assignment.get("subject_id", "")), "")

        # Get student's submission if any
        sub = await db.get_assignment_submission_by_student(assignment_id, student_id)
        submission_dict = None
        if sub:
            submission_dict = {
                "id": str(sub["id"]),
                "status": sub.get("status", "submitted"),
                "submitted_at": str(sub["submitted_at"]) if sub.get("submitted_at") else None,
                "submission_text": sub.get("submission_text", ""),
                "marks_obtained": sub.get("marks_obtained"),
                "percentage": sub.get("percentage"),
                "grade": sub.get("grade"),
                "ai_feedback": sub.get("ai_feedback"),
            }

        return AssignmentDetail(
            id=str(assignment["id"]),
            title=assignment.get("title", ""),
            instructions=assignment.get("instructions"),
            subject_name=subject_name,
            due_date=str(assignment["due_date"]) if assignment.get("due_date") else None,
            total_marks=assignment.get("total_marks", 0),
            status=assignment.get("status", "draft"),
            attachment_url=assignment.get("attachment_url"),
            submission=submission_dict,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get student assignment error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/assignments/{assignment_id}/submit", response_model=SubmissionResponse)
async def submit_assignment(
    assignment_id: str,
    body: SubmissionCreate,
    current_student: dict = Depends(require_student()),
):
    """Submit an assignment (creates or updates submission)"""
    try:
        db = await get_database()
        cls = await _verify_student_class(db, current_student)
        student_id = str(current_student["id"])

        assignment = await db.get_assignment(assignment_id)
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        if str(assignment.get("class_id")) != str(cls["id"]):
            raise HTTPException(status_code=403, detail="Not your class assignment")

        if assignment.get("status") != "published":
            raise HTTPException(status_code=400, detail="Assignment is not accepting submissions")

        # Check due date
        if assignment.get("due_date"):
            from datetime import timezone
            due = assignment["due_date"]
            if hasattr(due, "tzinfo") and due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now > due:
                raise HTTPException(status_code=400, detail="Submission deadline has passed")

        # Create / update submission (upsert)
        submission = await db.create_assignment_submission({
            "assignment_id": assignment_id,
            "student_account_id": student_id,
            "submission_text": body.submission_text,
            "status": "submitted",
            "submitted_at": datetime.utcnow().isoformat(),
        })

        if not submission:
            raise HTTPException(status_code=500, detail="Failed to create submission")

        return SubmissionResponse(
            id=str(submission["id"]),
            assignment_id=str(submission.get("assignment_id", assignment_id)),
            status=submission.get("status", "submitted"),
            submitted_at=str(submission["submitted_at"]) if submission.get("submitted_at") else None,
            marks_obtained=submission.get("marks_obtained"),
            percentage=submission.get("percentage"),
            grade=submission.get("grade"),
            ai_feedback=submission.get("ai_feedback"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Submit assignment error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/assignments/{assignment_id}/submission", response_model=SubmissionResponse)
async def get_my_submission(
    assignment_id: str,
    current_student: dict = Depends(require_student()),
):
    """Get the current student's submission for a given assignment"""
    try:
        db = await get_database()
        student_id = str(current_student["id"])

        sub = await db.get_assignment_submission_by_student(assignment_id, student_id)
        if not sub:
            raise HTTPException(status_code=404, detail="No submission found")

        return SubmissionResponse(
            id=str(sub["id"]),
            assignment_id=str(sub.get("assignment_id", assignment_id)),
            status=sub.get("status", "submitted"),
            submitted_at=str(sub["submitted_at"]) if sub.get("submitted_at") else None,
            marks_obtained=sub.get("marks_obtained"),
            percentage=sub.get("percentage"),
            grade=sub.get("grade"),
            ai_feedback=sub.get("ai_feedback"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get my submission error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ─── Scores ────────────────────────────────────────────────────────
@router.get("/scores", response_model=List[ScoreItem])
async def get_my_scores(current_student: dict = Depends(require_student())):
    """Get all graded scores for the current student"""
    try:
        db = await get_database()
        student_id = str(current_student["id"])

        submissions = await db.get_student_submissions(student_id)
        graded = [s for s in submissions if s.get("status") == "graded"]

        # Get assignment info for names
        assignment_ids = list(set(str(s.get("assignment_id")) for s in graded))
        assignment_map = {}
        for aid in assignment_ids:
            a = await db.get_assignment(aid)
            if a:
                assignment_map[aid] = a

        # Get subjects
        cls = await _verify_student_class(db, current_student)
        subjects = await db.get_subjects_by_class(str(cls["id"]))
        subj_map = {str(s["id"]): s.get("name", "") for s in subjects}

        result = []
        for s in graded:
            aid = str(s.get("assignment_id"))
            a = assignment_map.get(aid, {})
            result.append(ScoreItem(
                id=str(s["id"]),
                assignment_title=a.get("title", "Unknown"),
                subject_name=subj_map.get(str(a.get("subject_id", "")), ""),
                marks_obtained=s.get("marks_obtained", 0),
                total_marks=a.get("total_marks", 0),
                percentage=s.get("percentage", 0),
                grade=s.get("grade", "N/A"),
                graded_at=str(s["graded_at"]) if s.get("graded_at") else None,
            ))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get my scores error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ─── Subjects & Documents ─────────────────────────────────────────
@router.get("/subjects", response_model=List[SubjectItem])
async def get_my_subjects(current_student: dict = Depends(require_student())):
    """Get subjects in the student's class"""
    try:
        db = await get_database()
        cls = await _verify_student_class(db, current_student)
        subjects = await db.get_subjects_by_class(str(cls["id"]))

        result = []
        for s in subjects:
            # Count documents
            docs = await db.get_documents(str(s["id"]))
            result.append(SubjectItem(
                id=str(s["id"]),
                name=s.get("name", ""),
                description=s.get("description"),
                document_count=len(docs) if docs else 0,
            ))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get my subjects error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/subjects/{subject_id}/documents")
async def get_subject_documents(
    subject_id: str,
    current_student: dict = Depends(require_student()),
):
    """Get documents in a subject (student can see titles/metadata, not download)"""
    try:
        db = await get_database()
        cls = await _verify_student_class(db, current_student)

        # Verify subject belongs to the class
        subjects = await db.get_subjects_by_class(str(cls["id"]))
        subj_ids = [str(s["id"]) for s in subjects]
        if subject_id not in subj_ids:
            raise HTTPException(status_code=403, detail="Subject not in your class")

        docs = await db.get_documents(subject_id)
        return [
            {
                "id": str(d["id"]),
                "file_name": d.get("original_filename") or d.get("filename", ""),
                "filename": d.get("original_filename") or d.get("filename", ""),
                "original_filename": d.get("original_filename") or d.get("filename", ""),
                "file_type": d.get("file_type", ""),
                "status": d.get("processing_status", d.get("status", "")),
                "created_at": str(d.get("created_at", "")),
            }
            for d in (docs or [])
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get subject documents error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ─── RAG Query (Student) ──────────────────────────────────────────
class StudentRAGQuery(BaseModel):
    question: str
    subject_id: str


@router.post("/rag/query")
async def student_rag_query(
    body: StudentRAGQuery,
    current_student: dict = Depends(require_student()),
):
    """Student can ask questions against their class subjects via RAG"""
    try:
        db = await get_database()
        cls = await _verify_student_class(db, current_student)

        # Verify subject belongs to class
        subjects = await db.get_subjects_by_class(str(cls["id"]))
        subj_ids = [str(s["id"]) for s in subjects]
        if body.subject_id not in subj_ids:
            raise HTTPException(status_code=403, detail="Subject not in your class")

        # Use existing RAG pipeline
        from services.embedding_service import EmbeddingService
        from services.llm_service import LLMService

        emb = EmbeddingService()
        llm = LLMService()

        embedding = await emb.generate_embedding(body.question)
        if not embedding:
            raise HTTPException(status_code=500, detail="Failed to generate embedding")

        chunks = await db.search_similar_chunks(embedding, body.subject_id, limit=5)
        context = "\n\n".join(c.get("text", "") for c in (chunks or []))

        answer = await llm.generate_answer(body.question, context)

        return {
            "question": body.question,
            "answer": answer,
            "sources": len(chunks or []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Student RAG query error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
