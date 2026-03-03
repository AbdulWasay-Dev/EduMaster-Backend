"""
Analytics API endpoints
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from utils.security import get_current_teacher, require_teacher
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/class/{class_id}/overview")
async def get_class_overview(
    class_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Get class performance overview"""
    try:
        db = await get_database()
        classes = await db.get_classes(current_user["id"])
        class_ids = [str(c["id"]) for c in classes]
        if class_id not in class_ids:
            raise HTTPException(status_code=403, detail="Access denied to this class")

        students = await db.get_students(class_id)
        # Get all papers for this class
        papers = await db.get_papers_by_class(class_id)

        return {
            "class_id": class_id,
            "student_count": len(students),
            "paper_count": len(papers),
            "average_score": 0,
            "top_students": [],
            "grade_distribution": []
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analytics class overview error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/student/{student_id}/progress")
async def get_student_progress(
    student_id: str,
    current_user: dict = Depends(require_teacher())
):
    """Get individual student progress"""
    return {"student_id": student_id, "progress": []}


@router.get("/dashboard")
async def get_dashboard_stats(
    current_user: dict = Depends(require_teacher())
):
    """
    Get aggregated stats for the teacher's dashboard:
    total_subjects, total_papers, total_students, recent_submissions.
    """
    try:
        db = await get_database()

        subjects = await db.get_subjects(current_user["id"])
        classes = await db.get_classes(current_user["id"])
        papers = await db.get_papers(current_user["id"])

        total_students = 0
        for cls in classes:
            students = await db.get_students(str(cls["id"]))
            total_students += len(students)

        # Get recent submissions count
        recent_submissions = 0
        for paper in papers[:10]:  # Only check most recent 10 papers
            subs = await db.get_submissions(str(paper["id"]))
            recent_submissions += len(subs)

        return {
            "total_subjects": len(subjects),
            "total_classes": len(classes),
            "total_papers": len(papers),
            "total_students": total_students,
            "recent_submissions": recent_submissions,
        }
    except Exception as e:
        logger.error(f"Dashboard stats error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/activity")
async def get_activity_data(
    days: Optional[int] = Query(default=30, description="Number of days to look back"),
    current_user: dict = Depends(require_teacher())
):
    """Get recent activity data points"""
    # Placeholder implementation
    return []
