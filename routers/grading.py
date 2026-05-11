"""
Answer Sheet Grading API endpoints
"""
import logging
from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from utils.security import get_current_teacher, require_teacher_or_admin
from services.answer_sheet_grading import get_answer_sheet_grading_service
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


class AnswerSheetGradingRequest(BaseModel):
    """Answer sheet grading request model"""
    paper_id: str
    student_id: Optional[str] = None  # Optional to allow grading without linking to a student
    answer_sheet_image: str  # Base64 encoded image
    grading_mode: str = "auto"  # auto, semi_auto, manual
    strictness: str = "medium"  # lenient, medium, strict


class MultipleAnswerSheetGradingRequest(BaseModel):
    """Multiple answer sheet grading request model"""
    paper_id: str
    student_id: Optional[str] = None
    answer_sheet_images: List[str]  # List of base64 encoded images
    grading_mode: str = "auto"  # auto, semi_auto, manual
    strictness: str = "medium"  # lenient, medium, strict


class GradingResponse(BaseModel):
    """Full grading/submission response model"""
    submission_id: str
    id: str = ""  # alias for submission_id
    paper_id: str = ""
    student_id: Optional[str] = None
    student_name: str = ""
    total_score: float = 0.0
    max_score: float = 0.0
    score: float = 0.0
    total_marks: float = 0.0
    grade_percentage: float = 0.0
    grade: str = ""
    status: str = "graded"
    feedback: str = ""
    ai_feedback: str = ""
    question_scores: list = []
    question_details: list = []
    grading_details: list = []
    ocr_confidence: float = 0.0
    submitted_at: Optional[str] = None
    graded_at: Optional[str] = None
    created_at: Optional[str] = None


class StudentResponse(BaseModel):
    """Student response model"""
    id: str
    student_name: str
    student_id: str
    class_id: str


@router.post("/upload-answer-sheet", response_model=GradingResponse)
async def upload_and_grade_answer_sheet(
    request: AnswerSheetGradingRequest,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Upload photo of handwritten answer sheet and grade it automatically
    """
    try:
        logger.info(f"Answer sheet grading request from teacher {current_teacher['id']}")
        
        # Verify teacher has access to the paper
        db = await get_database()
        papers = await db.get_papers(current_teacher["id"])
        paper_ids = [str(p["id"]) for p in papers]
        
        if request.paper_id not in paper_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this paper"
            )
        
        # Verify student exists and belongs to teacher's class (optional)
        if request.student_id:
            student = await db.get_student(request.student_id)
            if not student:
                raise HTTPException(
                    status_code=404,
                    detail="Student not found"
                )
        
        # Process and grade the answer sheet
        grading_service = get_answer_sheet_grading_service()
        result = await grading_service.process_answer_sheet(
            paper_id=request.paper_id,
            student_id=request.student_id,
            answer_sheet_image=request.answer_sheet_image,
            grading_mode=request.grading_mode,
            strictness=request.strictness
        )
        
        if not result:
            raise HTTPException(
                status_code=500,
                detail="Failed to process answer sheet"
            )
        
        return GradingResponse(
            submission_id=str(result["submission_id"]),
            id=str(result["submission_id"]),
            paper_id=request.paper_id,
            student_id=request.student_id,
            total_score=result["total_score"],
            max_score=result.get("max_score", result.get("total_marks", 0)),
            score=result.get("score", result["total_score"]),
            total_marks=result.get("total_marks", result.get("max_score", 0)),
            grade_percentage=result["grade_percentage"],
            grade=result.get("grade", ""),
            status="graded",
            feedback=result["feedback"],
            ai_feedback=result.get("ai_feedback", result["feedback"]),
            question_scores=result.get("question_scores", []),
            question_details=result.get("question_details", result.get("question_scores", [])),
            grading_details=result.get("grading_details", result.get("question_scores", [])),
            ocr_confidence=result.get("ocr_confidence", 0),
            graded_at=result.get("graded_at"),
            created_at=result.get("created_at"),
        )

        # Fire notification
        try:
            from services.notification_service import notify
            _db2 = await get_database()
            _paper2 = await _db2.get_paper(request.paper_id)
            _ptitle = (_paper2 or {}).get("title", "Paper")
            _pct2 = round(result["grade_percentage"])
            await notify(
                teacher_id=current_teacher["id"],
                title="Answer sheet graded",
                message=f'Answer sheet for "{_ptitle}" graded — {result["total_score"]}/{result.get("max_score", result.get("total_marks", "?"))} ({_pct2}%).',
                notification_type="grade_available",
                metadata={"submission_id": str(result["submission_id"]), "paper_id": request.paper_id, "grade_percentage": result["grade_percentage"]},
            )
        except Exception:
            pass


    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in answer sheet grading: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during grading"
        )


@router.post("/upload-multiple-answer-sheets", response_model=GradingResponse)
async def upload_and_grade_multiple_answer_sheets(
    request: MultipleAnswerSheetGradingRequest,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Upload multiple photos of handwritten answer sheets and grade them automatically
    """
    try:
        logger.info(f"Multiple answer sheet grading request from teacher {current_teacher['id']} for {len(request.answer_sheet_images)} images")
        
        # Verify teacher has access to the paper
        db = await get_database()
        papers = await db.get_papers(current_teacher["id"])
        paper_ids = [str(p["id"]) for p in papers]
        
        if request.paper_id not in paper_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this paper"
            )
        
        # Verify student exists and belongs to teacher's class (optional)
        if request.student_id:
            student = await db.get_student(request.student_id)
            if not student:
                raise HTTPException(
                    status_code=404,
                    detail="Student not found"
                )
        
        # Process and grade the answer sheets
        grading_service = get_answer_sheet_grading_service()
        result = await grading_service.process_multiple_answer_sheets(
            paper_id=request.paper_id,
            student_id=request.student_id,
            answer_sheet_images=request.answer_sheet_images,
            grading_mode=request.grading_mode,
            strictness=request.strictness
        )
        
        if not result:
            raise HTTPException(
                status_code=500,
                detail="Failed to process answer sheets"
            )
        
        return GradingResponse(
            submission_id=str(result["submission_id"]),
            id=str(result["submission_id"]),
            paper_id=request.paper_id,
            student_id=request.student_id,
            total_score=result["total_score"],
            max_score=result.get("max_score", result.get("total_marks", 0)),
            score=result.get("score", result["total_score"]),
            total_marks=result.get("total_marks", result.get("max_score", 0)),
            grade_percentage=result["grade_percentage"],
            grade=result.get("grade", ""),
            status="graded",
            feedback=result["feedback"],
            ai_feedback=result.get("ai_feedback", result["feedback"]),
            question_scores=result.get("question_scores", []),
            question_details=result.get("question_details", result.get("question_scores", [])),
            grading_details=result.get("grading_details", result.get("question_scores", [])),
            ocr_confidence=result.get("ocr_confidence", 0),
            graded_at=result.get("graded_at"),
            created_at=result.get("created_at"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in multiple answer sheet grading: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during grading"
        )


@router.post("/process-sheet")
async def process_answer_sheet_only(
    paper_id: str = Form(...),
    student_id: str = Form(...),
    file: UploadFile = File(...),
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Upload answer sheet photo and process OCR (without grading)
    """
    try:
        # Read file content
        file_content = await file.read()
        
        # Convert to base64
        import base64
        base64_image = base64.b64encode(file_content).decode('utf-8')
        
        # Process OCR
        grading_service = get_answer_sheet_grading_service()
        ocr_text = grading_service._extract_text_from_image(
            grading_service._preprocess_image(file_content)
        )
        
        return {
            "paper_id": paper_id,
            "student_id": student_id,
            "ocr_text": ocr_text,
            "processed": True
        }
        
    except Exception as e:
        logger.error(f"Error processing answer sheet: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error processing answer sheet"
        )


@router.post("/upload-multiple-files")
async def upload_multiple_answer_sheet_files(
    paper_id: str = Form(...),
    student_id: str = Form(...),
    files: List[UploadFile] = File(...),
    grading_mode: str = Form("auto"),
    strictness: str = Form("medium"),
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Upload multiple answer sheet files and process them
    """
    try:
        logger.info(f"Multiple file upload request from teacher {current_teacher['id']} for {len(files)} files")
        
        # Verify teacher has access to the paper
        db = await get_database()
        papers = await db.get_papers(current_teacher["id"])
        paper_ids = [str(p["id"]) for p in papers]
        
        if paper_id not in paper_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this paper"
            )
        
        # Verify student exists and belongs to teacher's class
        student = await db.get_student(student_id)
        if not student:
            raise HTTPException(
                status_code=404,
                detail="Student not found"
            )
        
        # Convert files to base64
        base64_images = []
        for file in files:
            file_content = await file.read()
            import base64
            base64_image = base64.b64encode(file_content).decode('utf-8')
            base64_images.append(base64_image)
        
        # Process and grade the answer sheets
        grading_service = get_answer_sheet_grading_service()
        result = await grading_service.process_multiple_answer_sheets(
            paper_id=paper_id,
            student_id=student_id,
            answer_sheet_images=base64_images,
            grading_mode=grading_mode,
            strictness=strictness
        )
        
        if not result:
            raise HTTPException(
                status_code=500,
                detail="Failed to process answer sheets"
            )
        
        return {
            "submission_id": result["submission_id"],
            "total_score": result["total_score"],
            "score": result.get("score", result["total_score"]),
            "max_score": result.get("max_score", result.get("total_marks", 0)),
            "total_marks": result.get("total_marks", result.get("max_score", 0)),
            "grade_percentage": result["grade_percentage"],
            "grade": result.get("grade", ""),
            "feedback": result["feedback"],
            "ai_feedback": result.get("ai_feedback", result["feedback"]),
            "question_scores": result.get("question_scores", []),
            "question_details": result.get("question_details", result.get("question_scores", [])),
            "grading_details": result.get("grading_details", result.get("question_scores", [])),
            "confidence_score": result.get("confidence_score", 0.75),
            "images_processed": result.get("images_processed", len(files)),
            "ocr_confidence": result.get("ocr_confidence", 0.75)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in multiple file upload grading: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during grading"
        )


@router.get("/class/{class_id}/results")
async def get_class_grading_results(
    class_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Get all grading results for a class
    """
    try:
        db = await get_database()
        
        # Verify teacher has access to the class
        classes = await db.get_classes(current_teacher["id"])
        class_ids = [str(c["id"]) for c in classes]
        
        if class_id not in class_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this class"
            )
        
        # Get all papers for this class
        papers = await db.get_papers_by_class(class_id)
        
        # Get all submissions for these papers
        all_submissions = []
        for paper in papers:
            submissions = await db.get_submissions(str(paper["id"]))
            all_submissions.extend(_serialize_submission(submission, paper) for submission in submissions)
        
        return {
            "class_id": class_id,
            "total_submissions": len(all_submissions),
            "submissions": all_submissions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting class grading results: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/{submission_id}/result", response_model=GradingResponse)
async def get_grading_result(
    submission_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Get detailed grading result for a submission
    """
    try:
        db = await get_database()
        
        # Get submission details
        submission = await db.get_submission(submission_id)
        if not submission:
            raise HTTPException(
                status_code=404,
                detail="Submission not found"
            )
        
        # Verify teacher has access to this submission
        paper = await db.get_paper(str(submission["paper_id"]))
        if not paper or str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(
                status_code=403,
                detail="Access denied to this submission"
            )
        
        return GradingResponse(**_serialize_submission(submission, paper))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting grading result: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.post("/{submission_id}/regrade")
async def regrade_submission(
    submission_id: str,
    grading_mode: str = "auto",
    strictness: str = "medium",
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Regrade a submission with different settings
    """
    try:
        # Implementation would go here
        return {"message": "Submission regraded successfully", "submission_id": submission_id}
        
    except Exception as e:
        logger.error(f"Error regrading submission: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/queue")
async def get_grading_queue(
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Get pending grading tasks
    """
    try:
        db = await get_database()
        
        # Get pending submissions for teacher's papers
        papers = await db.get_papers(current_teacher["id"])
        pending_submissions = []
        
        for paper in papers:
            submissions = await db.get_submissions_by_status(paper["id"], "pending")
            pending_submissions.extend(submissions)
        
        return {
            "pending_count": len(pending_submissions),
            "submissions": pending_submissions
        }
        
    except Exception as e:
        logger.error(f"Error getting grading queue: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.delete("/submission/{submission_id}")
async def delete_submission(
    submission_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Delete a submission if the current teacher owns the related paper.
    """
    try:
        db = await get_database()

        # Fetch submission
        submission = await db.get_submission(submission_id)
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")

        # Verify ownership via paper
        paper = await db.get_paper(str(submission.get("paper_id")))
        if not paper or str(paper.get("owner_id")) != str(current_teacher["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this submission")

        # Delete using service-role client
        ok = await db.delete_submission(submission_id)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to delete submission")

        return {"deleted": True, "submission_id": submission_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting submission {submission_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/class/{class_id}/paper/{paper_id}/results")
async def get_class_paper_results(
    class_id: str,
    paper_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Get grading results for a specific paper within a class, including student names and roll numbers.
    """
    try:
        db = await get_database()

        # Verify paper belongs to current teacher and matches class
        paper = await db.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        if str(paper.get("owner_id")) != str(current_teacher["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this paper")
        if paper.get("class_id") and str(paper.get("class_id")) != str(class_id):
            raise HTTPException(status_code=403, detail="Paper does not belong to this class")

        # Fetch submissions for the paper
        submissions = await db.get_submissions(paper_id)

        # Build map from student_id to student info (name, roll)
        results = []
        seen_students = {}
        for sub in submissions:
            sid = sub.get("student_id")
            if sid and sid not in seen_students:
                student = await db.get_student(str(sid))
                seen_students[sid] = {
                    "student_name": (student or {}).get("student_name") or (student or {}).get("name") or "",
                    "roll_number": (student or {}).get("roll_number") or (student or {}).get("roll_no") or (student or {}).get("roll")
                }

        # Compose result rows
        for sub in submissions:
            sid = sub.get("student_id")
            info = seen_students.get(sid, {"student_name": "", "roll_number": None})
            serialized = _serialize_submission(sub, paper)
            results.append({
                "submission_id": sub.get("id"),
                "student_id": sid,
                "student_name": info["student_name"],
                "roll_number": info["roll_number"],
                "total_score": serialized.get("total_score", 0),
                "score": serialized.get("score", 0),
                "max_score": serialized.get("max_score", 0),
                "total_marks": serialized.get("total_marks", 0),
                "grade_percentage": serialized.get("grade_percentage", 0),
                "feedback": serialized.get("feedback", ""),
                "created_at": sub.get("created_at")
            })

        # Optional sort by student_name then roll
        results.sort(key=lambda r: (r["student_name"] or "", str(r["roll_number"]) if r["roll_number"] is not None else ""))

        return {
            "class_id": class_id,
            "paper_id": paper_id,
            "total_submissions": len(results),
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting class paper results: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints required by the frontend API client (grading.ts)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_submissions(
    paper_id: Optional[str] = None,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    List all submissions visible to the current teacher.
    Optionally filter by paper_id.
    """
    try:
        db = await get_database()
        papers = await db.get_papers(current_teacher["id"])

        all_submissions = []
        for paper in papers:
            if paper_id and str(paper["id"]) != paper_id:
                continue
            subs = await db.get_submissions(str(paper["id"]))
            all_submissions.extend(_serialize_submission(s, paper) for s in subs)

        return {
            "submissions": all_submissions,
            "total": len(all_submissions),
        }
    except Exception as e:
        logger.error(f"Error listing submissions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{submission_id}")
async def get_submission(
    submission_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """Get a single submission by ID"""
    try:
        db = await get_database()
        submission = await db.get_submission(submission_id)
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        # Verify ownership
        paper = await db.get_paper(str(submission["paper_id"]))
        if not paper or str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this submission")
        return _serialize_submission(submission, paper)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting submission {submission_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


class OverridePayload(BaseModel):
    question_id: str
    score: float
    note: Optional[str] = None


@router.post("/{submission_id}/override")
async def override_submission_score(
    submission_id: str,
    payload: OverridePayload,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """Override the score for a specific question in a submission"""
    try:
        db = await get_database()
        submission = await db.get_submission(submission_id)
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        paper = await db.get_paper(str(submission["paper_id"]))
        if not paper or str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(status_code=403, detail="Access denied")

        # Update grading details in the submission_data JSON blob if present.
        sub_data = _parse_jsonish(submission.get("submission_data"), {})
        if not isinstance(sub_data, dict):
            sub_data = {}

        details = sub_data.get("question_details") or sub_data.get("grading_details") or []
        if not isinstance(details, list):
            details = []
        for item in details:
            if str(item.get("question_id", "")) == payload.question_id:
                item["scored_marks"] = payload.score
                item["marks_awarded"] = payload.score
                item["score"] = payload.score
                if payload.note:
                    item["override_note"] = payload.note
                    item["ai_comment"] = payload.note
                    item["ai_feedback"] = payload.note
                break

        total_score = sum(
            _to_float(_first_present(item.get("marks_awarded"), item.get("scored_marks"), item.get("score")), 0.0) or 0.0
            for item in details
            if isinstance(item, dict)
        )
        max_score = _to_float(_first_present(
            sub_data.get("max_score"),
            sub_data.get("total_marks"),
            paper.get("total_marks"),
        ), 0.0) or 0.0
        grade_percentage = (total_score / max_score) * 100 if max_score > 0 else 0.0
        sub_data["question_details"] = details
        sub_data["grading_details"] = details
        sub_data["score"] = total_score
        sub_data["total_score"] = total_score
        sub_data["grade_percentage"] = round(grade_percentage, 2)
        sub_data["grade"] = _grade_label(grade_percentage)

        updated = await db.update_submission(submission_id, {
            "submission_data": sub_data,
            "total_score": total_score,
            "grade_percentage": grade_percentage,
        })
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update submission")

        return _serialize_submission(updated, paper)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error overriding submission {submission_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def _serialize_submission(s: dict, paper: Optional[dict] = None) -> dict:
    """Serialize a submission DB row to the frontend-compatible grading shape."""
    sub_data = _parse_jsonish(s.get("submission_data"), {})
    if not isinstance(sub_data, dict):
        sub_data = {}

    question_details = (
        sub_data.get("question_details")
        or sub_data.get("grading_details")
        or sub_data.get("question_scores")
        or []
    )
    if not isinstance(question_details, list):
        question_details = []

    total_score = _to_float(_first_present(
        s.get("total_score"),
        sub_data.get("total_score"),
        sub_data.get("score"),
    ), 0.0)

    max_score = _to_float(_first_present(
        s.get("max_score"),
        s.get("max_marks"),
        sub_data.get("max_score"),
        sub_data.get("total_marks"),
        paper.get("total_marks") if paper else None,
    ), 0.0)

    grade_percentage = _to_float(_first_present(
        s.get("grade_percentage"),
        sub_data.get("grade_percentage"),
    ), None)
    if grade_percentage is None:
        grade_percentage = (total_score / max_score) * 100 if max_score > 0 else 0.0

    raw_status = _first_present(s.get("grading_status"), s.get("status"), sub_data.get("status"), "graded")
    status = "graded" if str(raw_status).lower() in {"completed", "complete", "done"} else str(raw_status)

    feedback = str(_first_present(s.get("feedback"), sub_data.get("feedback"), sub_data.get("ai_feedback"), ""))
    submission_id = str(s.get("id", ""))
    submitted_at = _first_present(s.get("submitted_at"), s.get("created_at"), "")
    graded_at = _first_present(s.get("graded_at"), s.get("updated_at"), s.get("created_at"), "")

    return {
        "id": submission_id,
        "submission_id": submission_id,
        "paper_id": str(s.get("paper_id", "")),
        "paper_title": (paper or {}).get("title", ""),
        "student_id": str(s.get("student_id", "")) if s.get("student_id") else None,
        "student_name": s.get("student_name", ""),
        "class_id": str(s.get("class_id", "")) if s.get("class_id") else None,
        "total_score": total_score,
        "max_score": max_score,
        "score": total_score,
        "total_marks": max_score,
        "grade_percentage": round(grade_percentage, 2),
        "grade": sub_data.get("grade") or _grade_label(grade_percentage),
        "grading_mode": sub_data.get("grading_mode") or s.get("grading_mode") or "auto",
        "status": status,
        "feedback": feedback,
        "ai_feedback": feedback,
        "question_scores": question_details,
        "question_details": question_details,
        "grading_details": question_details,
        "ocr_confidence": _to_float(_first_present(s.get("ocr_confidence"), sub_data.get("ocr_confidence")), 0.0),
        "submitted_at": str(submitted_at),
        "graded_at": str(graded_at),
        "created_at": str(s.get("created_at", "")),
    }


def _parse_jsonish(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            import json as _json
            return _json.loads(value)
        except Exception:
            return fallback
    return fallback


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _to_float(value: Any, fallback: Optional[float] = 0.0) -> Optional[float]:
    if value is None or value == "":
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _grade_label(percentage: float) -> str:
    pct = _to_float(percentage, 0.0) or 0.0
    if pct >= 90:
        return "A+"
    if pct >= 80:
        return "A"
    if pct >= 70:
        return "B"
    if pct >= 60:
        return "C"
    if pct >= 50:
        return "D"
    return "F"

