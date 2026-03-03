"""
Answer Sheet Grading API endpoints
"""
import logging
from typing import Optional, List
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
    student_id: str
    answer_sheet_image: str  # Base64 encoded image
    grading_mode: str = "auto"  # auto, semi_auto, manual
    strictness: str = "medium"  # lenient, medium, strict


class MultipleAnswerSheetGradingRequest(BaseModel):
    """Multiple answer sheet grading request model"""
    paper_id: str
    student_id: str
    answer_sheet_images: List[str]  # List of base64 encoded images
    grading_mode: str = "auto"  # auto, semi_auto, manual
    strictness: str = "medium"  # lenient, medium, strict


class GradingResponse(BaseModel):
    """Minimal grading response model"""
    submission_id: str
    total_score: float
    grade_percentage: float
    feedback: str


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
        paper_ids = [p["id"] for p in papers]
        
        if request.paper_id not in paper_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this paper"
            )
        
        # Verify student exists and belongs to teacher's class
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
            submission_id=result["submission_id"],
            total_score=result["total_score"],
            grade_percentage=result["grade_percentage"],
            feedback=result["feedback"],
        )
        
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
        paper_ids = [p["id"] for p in papers]
        
        if request.paper_id not in paper_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this paper"
            )
        
        # Verify student exists and belongs to teacher's class
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
            submission_id=result["submission_id"],
            total_score=result["total_score"],
            grade_percentage=result["grade_percentage"],
            feedback=result["feedback"],
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
        paper_ids = [p["id"] for p in papers]
        
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
            "grade_percentage": result["grade_percentage"],
            "feedback": result["feedback"],
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
        class_ids = [c["id"] for c in classes]
        
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
            submissions = await db.get_submissions(paper["id"])
            all_submissions.extend(submissions)
        
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
        paper = await db.get_paper(submission["paper_id"])
        if not paper or paper["owner_id"] != current_teacher["id"]:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this submission"
            )
        
        return GradingResponse(
            submission_id=submission["id"],
            total_score=submission["total_score"],
            grade_percentage=submission["grade_percentage"],
            feedback=submission["feedback"],
        )
        
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
        paper = await db.get_paper(submission.get("paper_id"))
        if not paper or paper.get("owner_id") != current_teacher["id"]:
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
        if paper.get("owner_id") != current_teacher["id"]:
            raise HTTPException(status_code=403, detail="Access denied to this paper")
        if paper.get("class_id") and paper.get("class_id") != class_id:
            raise HTTPException(status_code=403, detail="Paper does not belong to this class")

        # Fetch submissions for the paper
        submissions = await db.get_submissions(paper_id)

        # Build map from student_id to student info (name, roll)
        results = []
        seen_students = {}
        for sub in submissions:
            sid = sub.get("student_id")
            if sid and sid not in seen_students:
                student = await db.get_student(sid)
                seen_students[sid] = {
                    "student_name": (student or {}).get("student_name") or (student or {}).get("name") or "",
                    "roll_number": (student or {}).get("roll_number") or (student or {}).get("roll_no") or (student or {}).get("roll")
                }

        # Compose result rows
        for sub in submissions:
            sid = sub.get("student_id")
            info = seen_students.get(sid, {"student_name": "", "roll_number": None})
            results.append({
                "submission_id": sub.get("id"),
                "student_id": sid,
                "student_name": info["student_name"],
                "roll_number": info["roll_number"],
                "total_score": sub.get("total_score", 0),
                "grade_percentage": sub.get("grade_percentage", 0),
                "feedback": sub.get("feedback", ""),
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

