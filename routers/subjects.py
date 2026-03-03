"""
Subjects API endpoints
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.security import get_current_teacher, require_teacher
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


class SubjectCreate(BaseModel):
    """Subject creation model"""
    name: str
    description: str = ""
    class_id: Optional[str] = None


class SubjectResponse(BaseModel):
    """Subject response model"""
    id: str
    name: str
    description: str
    class_id: Optional[str] = None
    created_at: str


@router.post("/", response_model=SubjectResponse)
async def create_subject(
    subject_data: SubjectCreate,
    current_user: dict = Depends(require_teacher())
):
    """Create a new subject"""
    try:
        db = await get_database()
        
        subject_data_dict = {
            "teacher_id": current_user["id"],
            "name": subject_data.name,
            "description": subject_data.description,
            "class_id": subject_data.class_id
        }
        
        subject = await db.create_subject(subject_data_dict)
        if not subject:
            raise HTTPException(status_code=500, detail="Failed to create subject")
        
        return SubjectResponse(
            id=str(subject["id"]),
            name=subject["name"],
            description=subject.get("description", ""),
            class_id=str(subject["class_id"]) if subject.get("class_id") else None,
            created_at=str(subject["created_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating subject: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/", response_model=List[SubjectResponse])
async def list_subjects(current_user: dict = Depends(require_teacher())):
    """List user's subjects"""
    try:
        db = await get_database()
        subjects = await db.get_subjects(current_user["id"])
        
        return [
            SubjectResponse(
                id=str(subject["id"]),
                name=subject["name"],
                description=subject.get("description", ""),
                class_id=str(subject["class_id"]) if subject.get("class_id") else None,
                created_at=str(subject["created_at"])
            )
            for subject in subjects
        ]
        
    except Exception as e:
        logger.error(f"Error listing subjects: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
