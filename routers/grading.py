"""
Answer Sheet Grading API endpoints
"""
import csv
import io
import logging
import re
from datetime import datetime
from typing import Optional, List, Any, Dict
from xml.sax.saxutils import escape
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
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

@router.get("/reports/paper/{paper_id}")
async def export_paper_class_report(
    paper_id: str,
    format: str = Query("pdf", pattern="^(pdf|csv)$"),
    class_id: Optional[str] = Query(None),
    current_teacher: dict = Depends(require_teacher_or_admin()),
):
    """
    Export a class report for one selected paper only.
    Includes roster coverage, class/subject/paper header, and per-question marks.
    """
    try:
        db = await get_database()
        report = await _build_paper_class_report_data(db, paper_id, current_teacher, class_id_override=class_id)
        if format.lower() == "csv":
            return _build_report_csv_response(report)
        return _build_report_pdf_response(report)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting paper class report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error while generating report")


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


async def _build_paper_class_report_data(
    db,
    paper_id: str,
    current_teacher: dict,
    class_id_override: Optional[str] = None,
) -> Dict[str, Any]:
    paper = await db.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if str(paper.get("owner_id")) != str(current_teacher["id"]):
        raise HTTPException(status_code=403, detail="Access denied to this paper")

    subject_info = await db.get_subject(str(paper.get("subject_id"))) if paper.get("subject_id") else None
    raw_submissions = await db.get_submissions(paper_id)
    candidate_class_ids = _report_candidate_class_ids(class_id_override, paper, subject_info, raw_submissions)

    class_id = ""
    class_info = None
    for candidate in candidate_class_ids:
        class_info = await db.get_class(candidate)
        if class_info and str(class_info.get("teacher_id")) == str(current_teacher["id"]):
            class_id = candidate
            break

    if not class_id or not class_info:
        raise HTTPException(
            status_code=400,
            detail="Could not determine the class for this paper. Select the class on the grading page, then export the report again.",
        )

    students = await db.get_students(class_id)
    questions = _report_questions(paper)
    student_map = {str(s.get("id")): s for s in students}
    submissions = [
        submission
        for submission in raw_submissions
        if _submission_belongs_to_report_class(submission, class_id, student_map)
    ]

    latest_by_student: Dict[str, Dict[str, Any]] = {}
    unmatched_submissions: List[Dict[str, Any]] = []
    duplicate_count = 0
    for submission in submissions:
        serialized = _serialize_submission(submission, paper)
        sid = serialized.get("student_id")
        if sid and sid in student_map:
            if sid in latest_by_student:
                duplicate_count += 1
                continue
            latest_by_student[sid] = serialized
        else:
            unmatched_submissions.append(serialized)

    rows: List[Dict[str, Any]] = []
    for student in students:
        sid = str(student.get("id"))
        rows.append(_build_report_student_row(student, latest_by_student.get(sid), questions))

    for index, submission in enumerate(unmatched_submissions, start=1):
        rows.append(_build_report_unmatched_row(submission, questions, index))

    rows.sort(key=lambda row: (
        1 if row.get("unmatched") else 0,
        str(row.get("roll_number") or "").lower(),
        str(row.get("student_name") or "").lower(),
    ))

    submitted_rows = [r for r in rows if r.get("submitted")]
    graded_rows = [r for r in submitted_rows if str(r.get("status", "")).lower() in {"graded", "completed", "complete", "done"}]
    score_rows = [r for r in submitted_rows if r.get("percentage") is not None]
    percentages = [float(r["percentage"]) for r in score_rows]
    total_marks = _to_float(paper.get("total_marks"), 0.0) or sum(q["max_marks"] for q in questions)
    avg_pct = round(sum(percentages) / len(percentages), 2) if percentages else 0.0
    pass_rows = [r for r in score_rows if float(r["percentage"]) >= 50]
    grade_distribution: Dict[str, int] = {}
    for row in score_rows:
        grade = row.get("grade") or _grade_label(float(row.get("percentage") or 0))
        grade_distribution[grade] = grade_distribution.get(grade, 0) + 1

    question_analysis = _build_question_analysis(rows, questions)
    summary = {
        "roster_students": len(students),
        "submitted_count": len(submitted_rows),
        "graded_count": len(graded_rows),
        "not_submitted_count": max(len(students) - len(latest_by_student), 0),
        "unmatched_submission_count": len(unmatched_submissions),
        "duplicate_submission_count": duplicate_count,
        "average_percentage": avg_pct,
        "highest_percentage": round(max(percentages), 2) if percentages else 0.0,
        "lowest_percentage": round(min(percentages), 2) if percentages else 0.0,
        "pass_rate": round((len(pass_rows) / len(score_rows)) * 100, 2) if score_rows else 0.0,
        "total_marks": total_marks,
        "grade_distribution": grade_distribution,
    }

    return {
        "paper": {
            "id": str(paper.get("id")),
            "title": paper.get("title") or "Paper",
            "total_marks": total_marks,
            "created_at": str(paper.get("created_at") or ""),
            "published_at": str(paper.get("published_at") or ""),
        },
        "class": {
            "id": class_id,
            "name": class_info.get("name") or "Class",
            "grade_level": class_info.get("grade_level") or "",
            "academic_year": class_info.get("academic_year") or "",
        },
        "subject": {
            "id": str((subject_info or {}).get("id") or paper.get("subject_id") or ""),
            "name": (subject_info or {}).get("name") or "Subject",
        },
        "teacher": {
            "name": current_teacher.get("name") or current_teacher.get("full_name") or current_teacher.get("email") or "Teacher",
            "email": current_teacher.get("email") or "",
        },
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "questions": questions,
        "rows": rows,
        "question_analysis": question_analysis,
        "summary": summary,
    }


def _report_questions(paper: dict) -> List[Dict[str, Any]]:
    questions = _parse_jsonish(paper.get("questions"), [])
    if not isinstance(questions, list):
        questions = []
    normalized = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        qid = str(_first_present(question.get("id"), question.get("question_id"), f"q{index}"))
        max_marks = _to_float(_first_present(question.get("marks"), question.get("max_marks"), question.get("max_score")), 0.0) or 0.0
        normalized.append({
            "id": qid,
            "label": f"Q{question.get('question_number') or index}",
            "index": index,
            "question_text": str(question.get("question_text") or question.get("text") or ""),
            "question_type": str(question.get("question_type") or question.get("type") or "question").replace("_", " "),
            "max_marks": max_marks,
        })
    return normalized


def _report_candidate_class_ids(
    class_id_override: Optional[str],
    paper: dict,
    subject_info: Optional[dict],
    submissions: List[dict],
) -> List[str]:
    candidates: List[str] = []
    for value in (
        class_id_override,
        paper.get("class_id"),
        (subject_info or {}).get("class_id"),
    ):
        if value:
            candidate = str(value)
            if candidate not in candidates:
                candidates.append(candidate)

    submission_class_ids = []
    for submission in submissions:
        if submission.get("class_id"):
            candidate = str(submission["class_id"])
            if candidate not in submission_class_ids:
                submission_class_ids.append(candidate)

    if len(submission_class_ids) == 1 and submission_class_ids[0] not in candidates:
        candidates.append(submission_class_ids[0])
    elif class_id_override:
        for candidate in submission_class_ids:
            if candidate not in candidates:
                candidates.append(candidate)

    return candidates


def _submission_belongs_to_report_class(submission: dict, class_id: str, student_map: Dict[str, dict]) -> bool:
    if submission.get("class_id") and str(submission["class_id"]) == class_id:
        return True
    student_id = str(submission.get("student_id") or "")
    if student_id and student_id in student_map:
        return True
    return not submission.get("class_id") and not student_id


def _build_report_student_row(student: dict, submission: Optional[dict], questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    row = {
        "student_id": str(student.get("id") or ""),
        "student_name": student.get("student_name") or student.get("name") or "Student",
        "roll_number": student.get("student_id") or student.get("roll_number") or "",
        "email": student.get("email") or "",
        "submitted": bool(submission),
        "status": "graded" if submission else "not_submitted",
        "total_score": None,
        "max_score": None,
        "percentage": None,
        "grade": "",
        "submitted_at": "",
        "graded_at": "",
        "question_scores": _empty_question_scores(questions),
        "unmatched": False,
    }
    if submission:
        _merge_submission_into_report_row(row, submission, questions)
    return row


def _build_report_unmatched_row(submission: dict, questions: List[Dict[str, Any]], index: int) -> Dict[str, Any]:
    row = {
        "student_id": submission.get("student_id") or f"unmatched-{index}",
        "student_name": submission.get("student_name") or f"Unmatched submission {index}",
        "roll_number": "Unmatched",
        "email": "",
        "submitted": True,
        "status": submission.get("status") or "graded",
        "total_score": None,
        "max_score": None,
        "percentage": None,
        "grade": "",
        "submitted_at": submission.get("submitted_at") or "",
        "graded_at": submission.get("graded_at") or "",
        "question_scores": _empty_question_scores(questions),
        "unmatched": True,
    }
    _merge_submission_into_report_row(row, submission, questions)
    return row


def _merge_submission_into_report_row(row: Dict[str, Any], submission: dict, questions: List[Dict[str, Any]]) -> None:
    total_score = _to_float(_first_present(submission.get("total_score"), submission.get("score")), None)
    max_score = _to_float(_first_present(submission.get("max_score"), submission.get("total_marks")), None)
    pct = _to_float(submission.get("grade_percentage"), None)
    if pct is None and total_score is not None and max_score:
        pct = (total_score / max_score) * 100

    row.update({
        "submitted": True,
        "status": submission.get("status") or "graded",
        "total_score": total_score,
        "max_score": max_score,
        "percentage": round(pct, 2) if pct is not None else None,
        "grade": submission.get("grade") or (_grade_label(pct or 0) if pct is not None else ""),
        "submitted_at": submission.get("submitted_at") or "",
        "graded_at": submission.get("graded_at") or "",
        "question_scores": _question_scores_for_submission(submission, questions),
    })


def _empty_question_scores(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "question_id": q["id"],
            "label": q["label"],
            "score": None,
            "max_marks": q["max_marks"],
            "attempted": False,
            "is_correct": False,
            "comment": "",
        }
        for q in questions
    ]


def _question_scores_for_submission(submission: dict, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    details = submission.get("question_details") or submission.get("grading_details") or submission.get("question_scores") or []
    if not isinstance(details, list):
        details = []
    detail_by_id = {
        str(detail.get("question_id")): detail
        for detail in details
        if isinstance(detail, dict) and detail.get("question_id") is not None
    }

    scores = []
    for index, question in enumerate(questions):
        detail = detail_by_id.get(question["id"])
        if detail is None and index < len(details) and isinstance(details[index], dict):
            detail = details[index]
        if not detail:
            scores.append({
                "question_id": question["id"],
                "label": question["label"],
                "score": None,
                "max_marks": question["max_marks"],
                "attempted": False,
                "is_correct": False,
                "comment": "",
            })
            continue
        score = _to_float(_first_present(detail.get("marks_awarded"), detail.get("scored_marks"), detail.get("score")), None)
        max_marks = _to_float(_first_present(detail.get("max_marks"), detail.get("max_score"), question.get("max_marks")), question["max_marks"]) or 0.0
        answer = _first_present(detail.get("student_answer"), detail.get("student_answer_text"), "")
        attempted = detail.get("attempted")
        if attempted is None:
            attempted = bool(answer) or (score is not None and score > 0)
        scores.append({
            "question_id": question["id"],
            "label": question["label"],
            "score": score,
            "max_marks": max_marks,
            "attempted": bool(attempted),
            "is_correct": bool(detail.get("is_correct")) or (score is not None and max_marks > 0 and score >= max_marks),
            "comment": _first_present(detail.get("ai_comment"), detail.get("ai_feedback"), detail.get("feedback"), ""),
        })
    return scores


def _build_question_analysis(rows: List[Dict[str, Any]], questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    submitted_rows = [row for row in rows if row.get("submitted")]
    analysis = []
    for index, question in enumerate(questions):
        scores = []
        attempted_count = 0
        for row in submitted_rows:
            q_scores = row.get("question_scores") or []
            if index >= len(q_scores):
                continue
            item = q_scores[index]
            if item.get("attempted"):
                attempted_count += 1
            if item.get("score") is not None:
                scores.append(float(item["score"]))
        max_marks = question["max_marks"]
        average = round(sum(scores) / len(scores), 2) if scores else 0.0
        average_pct = round((average / max_marks) * 100, 2) if max_marks else 0.0
        attempt_rate = round((attempted_count / len(submitted_rows)) * 100, 2) if submitted_rows else 0.0
        analysis.append({
            **question,
            "average_score": average,
            "average_percentage": average_pct,
            "highest_score": round(max(scores), 2) if scores else 0.0,
            "lowest_score": round(min(scores), 2) if scores else 0.0,
            "attempt_rate": attempt_rate,
            "needs_review": average_pct < 50 or attempt_rate < 70,
        })
    return analysis


def _build_report_csv_response(report: Dict[str, Any]) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Class Result Report"])
    writer.writerow(["Class", report["class"]["name"], "Subject", report["subject"]["name"], "Paper", report["paper"]["title"]])
    writer.writerow(["Teacher", report["teacher"]["name"], "Generated", report["generated_at"], "Total Marks", _fmt_num(report["summary"]["total_marks"])])
    writer.writerow([])
    writer.writerow(["Summary"])
    for key, value in report["summary"].items():
        if key == "grade_distribution":
            writer.writerow(["grade_distribution", "; ".join(f"{grade}: {count}" for grade, count in value.items())])
        else:
            writer.writerow([key, value])
    writer.writerow([])

    question_labels = [q["label"] for q in report["questions"]]
    writer.writerow(["Roll No", "Student Name", "Email", "Status", "Total Score", "Max Score", "Percentage", "Grade", *question_labels])
    for row in report["rows"]:
        writer.writerow([
            row.get("roll_number") or "",
            row.get("student_name") or "",
            row.get("email") or "",
            _status_label(row.get("status")),
            _fmt_num(row.get("total_score")),
            _fmt_num(row.get("max_score")),
            _fmt_pct(row.get("percentage")),
            row.get("grade") or "",
            *[_score_cell(item) for item in row.get("question_scores", [])],
        ])

    writer.writerow([])
    writer.writerow(["Question Analysis"])
    writer.writerow(["Question", "Type", "Max Marks", "Average", "Average %", "Highest", "Attempt Rate", "Review"])
    for q in report["question_analysis"]:
        writer.writerow([
            q["label"],
            q["question_type"],
            _fmt_num(q["max_marks"]),
            _fmt_num(q["average_score"]),
            _fmt_pct(q["average_percentage"]),
            _fmt_num(q["highest_score"]),
            _fmt_pct(q["attempt_rate"]),
            "Needs review" if q["needs_review"] else "OK",
        ])

    data = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    filename = _report_filename(report, "csv")
    return StreamingResponse(
        data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_report_pdf_response(report: Dict[str, Any]) -> StreamingResponse:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        logger.error(f"ReportLab is required for PDF report generation: {exc}")
        raise HTTPException(status_code=500, detail="PDF report generation dependency is not available")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=0.35 * inch,
        rightMargin=0.35 * inch,
        topMargin=0.35 * inch,
        bottomMargin=0.45 * inch,
        title=f"{report['paper']['title']} Class Report",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.HexColor("#0f172a"), alignment=TA_CENTER, spaceAfter=8)
    section_style = ParagraphStyle("ReportSection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=12, textColor=colors.HexColor("#0A66C2"), spaceBefore=10, spaceAfter=6)
    small_style = ParagraphStyle("ReportSmall", parent=styles["BodyText"], fontSize=7, leading=8, textColor=colors.HexColor("#0f172a"), alignment=TA_LEFT)
    small_center = ParagraphStyle("ReportSmallCenter", parent=small_style, alignment=TA_CENTER)
    small_right = ParagraphStyle("ReportSmallRight", parent=small_style, alignment=TA_RIGHT)
    muted_style = ParagraphStyle("ReportMuted", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#475569"), alignment=TA_CENTER)
    story = []

    story.append(Paragraph("Class Result Report", title_style))
    story.append(Paragraph(_esc(f"{report['class']['name']} / {report['subject']['name']} / {report['paper']['title']}"), muted_style))
    story.append(Spacer(1, 0.08 * inch))

    meta_rows = [
        ["Class", report["class"]["name"], "Subject", report["subject"]["name"]],
        ["Paper", report["paper"]["title"], "Total Marks", _fmt_num(report["summary"]["total_marks"])],
        ["Teacher", report["teacher"]["name"], "Generated", report["generated_at"]],
    ]
    meta_table = Table([[ _p(cell, small_style if i % 2 else small_center) for i, cell in enumerate(row)] for row in meta_rows], colWidths=[0.85 * inch, 3.7 * inch, 0.95 * inch, 3.7 * inch])
    meta_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dbeafe")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eff6ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(meta_table)

    summary = report["summary"]
    summary_data = [
        ["Roster", summary["roster_students"], "Submitted", summary["submitted_count"], "Not Submitted", summary["not_submitted_count"]],
        ["Average", _fmt_pct(summary["average_percentage"]), "Highest", _fmt_pct(summary["highest_percentage"]), "Lowest", _fmt_pct(summary["lowest_percentage"])],
        ["Pass Rate", _fmt_pct(summary["pass_rate"]), "Graded", summary["graded_count"], "Unmatched", summary["unmatched_submission_count"]],
    ]
    summary_table = Table([[ _p(cell, small_center) for cell in row] for row in summary_data], colWidths=[1.15 * inch] * 6)
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(Paragraph("Summary", section_style))
    story.append(summary_table)

    distribution = summary.get("grade_distribution") or {}
    if distribution:
        dist_text = "   ".join(f"{grade}: {count}" for grade, count in sorted(distribution.items()))
        story.append(Paragraph(_esc(f"Grade distribution: {dist_text}"), muted_style))

    story.append(Paragraph("Student Results", section_style))
    story.extend(_build_pdf_result_tables(report, small_style, small_center, small_right, colors, inch, Table, TableStyle, Paragraph, PageBreak))

    story.append(PageBreak())
    story.append(Paragraph("Question Analysis", section_style))
    analysis_rows = [["Question", "Type", "Max", "Average", "Average %", "Highest", "Attempted", "Review"]]
    for q in report["question_analysis"]:
        review = "Needs review" if q["needs_review"] else "OK"
        analysis_rows.append([
            _p(f"{q['label']}: {q['question_text'][:95]}", small_style),
            _p(q["question_type"], small_center),
            _p(_fmt_num(q["max_marks"]), small_center),
            _p(_fmt_num(q["average_score"]), small_center),
            _p(_fmt_pct(q["average_percentage"]), small_center),
            _p(_fmt_num(q["highest_score"]), small_center),
            _p(_fmt_pct(q["attempt_rate"]), small_center),
            _p(review, small_center),
        ])
    if len(analysis_rows) == 1:
        analysis_rows.append([_p("No question-level data available.", small_center), "", "", "", "", "", "", ""])
    analysis_table = Table(analysis_rows, repeatRows=1, colWidths=[3.4 * inch, 1.0 * inch, 0.55 * inch, 0.75 * inch, 0.75 * inch, 0.65 * inch, 0.8 * inch, 1.0 * inch])
    analysis_table.setStyle(_report_table_style(colors))
    story.append(analysis_table)

    difficult = [q for q in report["question_analysis"] if q["needs_review"]]
    if difficult:
        story.append(Paragraph("Review Focus", section_style))
        focus = "; ".join(f"{q['label']} ({_fmt_pct(q['average_percentage'])} avg, {_fmt_pct(q['attempt_rate'])} attempted)" for q in difficult[:8])
        story.append(Paragraph(_esc(focus), small_style))

    def _footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(doc.leftMargin, 0.22 * inch, f"Generated {report['generated_at']}")
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.22 * inch, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    filename = _report_filename(report, "pdf")
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_pdf_result_tables(report, small_style, small_center, small_right, colors, inch, Table, TableStyle, Paragraph, PageBreak):
    questions = report["questions"]
    rows = report["rows"]
    if not questions:
        questions = [{"label": "Result", "max_marks": report["summary"]["total_marks"], "id": "result", "question_text": "", "question_type": ""}]

    chunks = [questions[i:i + 8] for i in range(0, len(questions), 8)]
    flowables = []
    for chunk_index, chunk in enumerate(chunks):
        if chunk_index > 0:
            flowables.append(PageBreak())
            flowables.append(Paragraph(f"Student Results (continued: {chunk[0]['label']} - {chunk[-1]['label']})", small_style))
        fixed_widths = [0.7 * inch, 1.65 * inch, 0.65 * inch, 0.55 * inch, 0.55 * inch, 0.75 * inch]
        q_width = max(0.42 * inch, (10.0 * inch - sum(fixed_widths)) / max(len(chunk), 1))
        table_rows = [["Roll", "Student", "Total", "%", "Grade", "Status", *[f"{q['label']}\n/{_fmt_num(q['max_marks'])}" for q in chunk]]]
        for row in rows:
            q_cells = []
            for question in chunk:
                q_item = next((item for item in row.get("question_scores", []) if item.get("question_id") == question["id"]), None)
                q_cells.append(_p(_score_cell(q_item), small_center))
            table_rows.append([
                _p(row.get("roll_number") or "-", small_center),
                _p(row.get("student_name") or "-", small_style),
                _p(_fmt_num(row.get("total_score")), small_right),
                _p(_fmt_pct(row.get("percentage")), small_center),
                _p(row.get("grade") or "-", small_center),
                _p(_status_label(row.get("status")), small_center),
                *q_cells,
            ])
        table = Table(table_rows, repeatRows=1, colWidths=[*fixed_widths, *([q_width] * len(chunk))])
        table.setStyle(_report_table_style(colors))
        flowables.append(table)
    return flowables


def _build_report_email_pdf_file(report: Dict[str, Any], student_id: Optional[str] = None) -> tuple[bytes, str, str, Optional[Dict[str, Any]]]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        logger.error(f"ReportLab is required for PDF report email generation: {exc}")
        raise HTTPException(status_code=500, detail="PDF report generation dependency is not available")

    selected_row = None
    email_report = dict(report)
    if student_id:
        for row in report.get("rows", []):
            if str(row.get("student_id") or "") == str(student_id):
                selected_row = row
                break
        if not selected_row:
            raise HTTPException(status_code=404, detail="Student result was not found for this paper report")
        email_report["rows"] = [selected_row]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=0.35 * inch,
        rightMargin=0.35 * inch,
        topMargin=0.35 * inch,
        bottomMargin=0.45 * inch,
        title=f"{report['paper']['title']} Result Report",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportEmailTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.HexColor("#0f172a"), alignment=TA_CENTER, spaceAfter=8)
    section_style = ParagraphStyle("ReportEmailSection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=12, textColor=colors.HexColor("#0A66C2"), spaceBefore=10, spaceAfter=6)
    small_style = ParagraphStyle("ReportEmailSmall", parent=styles["BodyText"], fontSize=7, leading=8, textColor=colors.HexColor("#0f172a"), alignment=TA_LEFT)
    small_center = ParagraphStyle("ReportEmailSmallCenter", parent=small_style, alignment=TA_CENTER)
    small_right = ParagraphStyle("ReportEmailSmallRight", parent=small_style, alignment=TA_RIGHT)
    muted_style = ParagraphStyle("ReportEmailMuted", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#475569"), alignment=TA_CENTER)

    report_title = "Student Result Report" if selected_row else "Class Result Report"
    story = [
        Paragraph(report_title, title_style),
        Paragraph(_esc(f"{report['class']['name']} / {report['subject']['name']} / {report['paper']['title']}"), muted_style),
        Spacer(1, 0.08 * inch),
    ]
    if selected_row:
        story.append(Paragraph(_esc(f"{selected_row.get('student_name')} - Roll No: {selected_row.get('roll_number') or '-'}"), muted_style))
        story.append(Spacer(1, 0.05 * inch))

    meta_rows = [
        ["Class", report["class"]["name"], "Subject", report["subject"]["name"]],
        ["Paper", report["paper"]["title"], "Total Marks", _fmt_num(report["summary"]["total_marks"])],
        ["Teacher", report["teacher"]["name"], "Generated", report["generated_at"]],
    ]
    meta_table = Table([[_p(cell, small_style if i % 2 else small_center) for i, cell in enumerate(row)] for row in meta_rows], colWidths=[0.85 * inch, 3.7 * inch, 0.95 * inch, 3.7 * inch])
    meta_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dbeafe")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eff6ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(meta_table)

    summary = report["summary"]
    summary_rows = [
        ["Roster", summary["roster_students"], "Submitted", summary["submitted_count"], "Not Submitted", summary["not_submitted_count"]],
        ["Average", _fmt_pct(summary["average_percentage"]), "Highest", _fmt_pct(summary["highest_percentage"]), "Lowest", _fmt_pct(summary["lowest_percentage"])],
        ["Pass Rate", _fmt_pct(summary["pass_rate"]), "Graded", summary["graded_count"], "Unmatched", summary["unmatched_submission_count"]],
    ]
    summary_table = Table([[_p(cell, small_center) for cell in row] for row in summary_rows], colWidths=[1.15 * inch] * 6)
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(Paragraph("Summary", section_style))
    story.append(summary_table)

    story.append(Paragraph("Result Details", section_style))
    story.extend(_build_pdf_result_tables(email_report, small_style, small_center, small_right, colors, inch, Table, TableStyle, Paragraph, PageBreak))

    if not selected_row:
        story.append(PageBreak())
        story.append(Paragraph("Question Analysis", section_style))
        analysis_rows = [["Question", "Type", "Max", "Average", "Average %", "Highest", "Attempted", "Review"]]
        for q in report["question_analysis"]:
            analysis_rows.append([
                _p(f"{q['label']}: {q['question_text'][:95]}", small_style),
                _p(q["question_type"], small_center),
                _p(_fmt_num(q["max_marks"]), small_center),
                _p(_fmt_num(q["average_score"]), small_center),
                _p(_fmt_pct(q["average_percentage"]), small_center),
                _p(_fmt_num(q["highest_score"]), small_center),
                _p(_fmt_pct(q["attempt_rate"]), small_center),
                _p("Needs review" if q["needs_review"] else "OK", small_center),
            ])
        if len(analysis_rows) == 1:
            analysis_rows.append([_p("No question-level data available.", small_center), "", "", "", "", "", "", ""])
        analysis_table = Table(analysis_rows, repeatRows=1, colWidths=[3.4 * inch, 1.0 * inch, 0.55 * inch, 0.75 * inch, 0.75 * inch, 0.65 * inch, 0.8 * inch, 1.0 * inch])
        analysis_table.setStyle(_report_table_style(colors))
        story.append(analysis_table)

    def _footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(doc.leftMargin, 0.22 * inch, f"Generated {report['generated_at']}")
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.22 * inch, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    if selected_row:
        stem = f"{selected_row.get('student_name')}_{report['paper']['title']}_result_report"
        filename = f"{re.sub(r'[^A-Za-z0-9._-]+', '_', stem).strip('._-')[:120] or 'student_result_report'}.pdf"
    else:
        filename = _report_filename(report, "pdf")
    return buffer.getvalue(), filename, "application/pdf", selected_row


def _report_table_style(colors):
    from reportlab.platypus import TableStyle
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dbeafe")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0A66C2")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])


def _p(value: Any, style):
    from reportlab.platypus import Paragraph
    return Paragraph(_esc(value), style)


def _esc(value: Any) -> str:
    return escape(str(value if value is not None and value != "" else "-"))


def _fmt_num(value: Any) -> str:
    number = _to_float(value, None)
    if number is None:
        return "-"
    if abs(number - round(number)) < 0.005:
        return str(int(round(number)))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _fmt_pct(value: Any) -> str:
    number = _to_float(value, None)
    if number is None:
        return "-"
    return f"{_fmt_num(number)}%"


def _score_cell(item: Optional[dict]) -> str:
    if not item or item.get("score") is None:
        return "-"
    return f"{_fmt_num(item.get('score'))}/{_fmt_num(item.get('max_marks'))}"


def _status_label(status: Any) -> str:
    value = str(status or "").replace("_", " ").strip()
    if not value:
        return "-"
    return value[:1].upper() + value[1:]


def _report_filename(report: Dict[str, Any], ext: str) -> str:
    stem = f"{report['class']['name']}_{report['subject']['name']}_{report['paper']['title']}_report"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "class_report"
    return f"{stem[:120]}.{ext}"

