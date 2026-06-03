"""
Paper Management API endpoints
"""
import json
import logging
import uuid
from typing import Any, List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel, Field

from utils.security import get_current_teacher, require_teacher_or_admin, require_teacher
from services.database import get_database
from services.file_storage import get_file_storage
from services.text_extractor import get_text_extractor
from services.llm_service import get_llm_service
from services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)
router = APIRouter()


class PaperGenerationRequest(BaseModel):
    """Paper generation request model"""
    subject_id: str = Field(..., description="Subject ID")
    class_id: Optional[str] = Field(None, description="Class ID")
    title: str = Field(..., description="Paper title")
    description: Optional[str] = Field(None, description="Paper description")
    question_count: int = Field(default=10, ge=1, le=50, description="Number of questions")
    question_types: List[str] = Field(default=["mcq", "short_answer"], description="Question types")
    difficulty_level: str = Field(default="medium", description="Difficulty level")
    time_limit: Optional[int] = Field(None, description="Time limit in minutes")
    total_marks: Optional[float] = Field(None, description="Total marks")

    # New fields for chapter-specific generation
    chapter_keywords: Optional[List[str]] = Field(None, description="Keywords to filter content by chapter (e.g., ['Chapter 1', 'Introduction'])")
    document_ids: Optional[List[str]] = Field(None, description="Specific document IDs to generate questions from")
    content_filter: Optional[str] = Field(None, description="Text filter to focus on specific topics or chapters")

    # Advanced paper configuration
    question_type_counts: Optional[Dict[str, int]] = Field(None, description="Per-type question counts e.g. {'mcq': 5, 'short_answer': 3, 'essay': 2}")
    template: Optional[str] = Field(default=None, description="Paper template: formal")
    institution_name: Optional[str] = Field(None, description="Institution / school name for the paper header")
    faculty_name: Optional[str] = Field(None, description="Faculty name for the paper header")
    department_name: Optional[str] = Field(None, description="Department name for the paper header")
    program_name: Optional[str] = Field(None, description="Program name displayed on the paper")
    session_name: Optional[str] = Field(None, description="Session / academic term")
    teacher_name: Optional[str] = Field(None, description="Teacher name displayed on the paper")
    course_name: Optional[str] = Field(None, description="Course name displayed on the paper")
    course_code: Optional[str] = Field(None, description="Course code displayed on the paper")
    exam_date: Optional[str] = Field(None, description="Exam date displayed on the paper")
    duration: Optional[str] = Field(None, description="Duration string e.g. '3 Hours'")
    instructions: Optional[str] = Field(None, description="Custom paper instructions")
    student_fields: Optional[List[str]] = Field(default=None, description="Student detail fields to show on paper")
    topic_focus: Optional[str] = Field(None, description="Topic focus alias used by the frontend")


class PaperFromSheetRequest(BaseModel):
    """Create paper from question sheet request"""
    subject_id: str = Field(..., description="Subject ID")
    class_id: Optional[str] = Field(None, description="Class ID")
    title: str = Field(..., description="Paper title")
    description: Optional[str] = Field(None, description="Paper description")
    question_sheet_image: str = Field(..., description="Base64 encoded question sheet image")


class PaperResponse(BaseModel):
    """Paper response model"""
    id: str
    title: str
    description: str
    subject_id: str
    class_id: Optional[str]
    questions: List[dict]
    answer_key: dict
    total_marks: float
    is_published: bool
    created_at: str
    # Extended fields
    duration_minutes: Optional[int] = None
    difficulty_level: str = "medium"
    template: str = "formal"
    institution_name: Optional[str] = None
    faculty_name: Optional[str] = None
    department_name: Optional[str] = None
    program_name: Optional[str] = None
    session_name: Optional[str] = None
    teacher_name: Optional[str] = None
    course_name: Optional[str] = None
    course_code: Optional[str] = None
    exam_date: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    student_fields: Optional[List[str]] = None


class GradingReportSendRequest(BaseModel):
    class_id: Optional[str] = None
    student_id: Optional[str] = None
    recipient_email: Optional[str] = None


def _parse_string_list(value: Any, fallback: Optional[List[str]] = None) -> List[str]:
    fallback = fallback or ["name", "roll_number"]
    if isinstance(value, list):
        parsed = [str(item) for item in value if item]
        return parsed or fallback
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                parsed = [str(item) for item in decoded if item]
                return parsed or fallback
        except Exception:
            pass
    return fallback


def _normalize_template_key(value: Optional[str]) -> str:
    if value == "formal":
        return "formal"
    if value in ("classic", "university", "school", "minimalist"):
        return "formal"
    return "formal"


def _teacher_paper_defaults(teacher: Optional[dict], subject_name: str = "") -> dict:
    teacher = teacher or {}
    return {
        "template": _normalize_template_key(teacher.get("default_paper_template")),
        "institution_name": teacher.get("school_name") or "EduMaster Institute",
        "faculty_name": "",
        "department_name": teacher.get("department") or "",
        "program_name": "",
        "session_name": "",
        "teacher_name": teacher.get("name") or "Unknown Teacher",
        "course_name": teacher.get("default_course_name") or subject_name,
        "course_code": "",
        "duration": teacher.get("default_exam_duration") or "3 Hours",
        "instructions": teacher.get("default_exam_instructions")
            or "Answer ALL questions. Marks are indicated against each question.",
        "student_fields": _parse_string_list(teacher.get("default_student_fields")),
    }


@router.post("/generate", response_model=PaperResponse)
async def generate_paper(
    request: PaperGenerationRequest,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Generate paper using RAG system from uploaded documents
    """
    try:
        logger.info(f"Paper generation request from teacher {current_teacher['id']}")
        
        # Get services
        db = await get_database()
        llm_service = get_llm_service()
        embedding_service = get_embedding_service()
        
        # Verify teacher has access to the subject
        subjects = await db.get_subjects(current_teacher["id"])
        subject_ids = [str(s["id"]) for s in subjects]

        if request.subject_id not in subject_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this subject"
            )

        # Get documents for the subject
        documents = await db.get_documents(request.subject_id)
        
        if not documents:
            raise HTTPException(
                status_code=400,
                detail="No documents found for this subject. Please upload documents first to generate questions."
            )
        
        # Use RAG system to retrieve comprehensive content
        # Create a more specific query based on the subject and paper requirements
        subject_name = "the subject"  # We'll try to get this from the subject data
        subject_data = None
        try:
            # Try to get subject name for better query
            subject_data = await db.get_subject(request.subject_id)
            if subject_data and subject_data.get('name'):
                subject_name = subject_data['name']
        except:
            pass  # Use default if we can't get subject name
        
        content_query = f"Generate questions about {subject_name} covering important topics, concepts, definitions, examples, and key information"
        
        # Get query embedding
        query_embedding = await embedding_service.generate_query_embedding(content_query)
        if not query_embedding:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate query embedding"
            )
        
        # First try the RPC function
        relevant_chunks = await db.search_similar_chunks(
            embedding=query_embedding,
            subject_id=request.subject_id,
            limit=30,  # Get more chunks for comprehensive paper generation
            match_threshold=0.3  # Lower threshold to get more content
        )
        
        logger.info(f"RPC search found {len(relevant_chunks)} chunks with threshold 0.3")
        
        # If RPC fails, try direct database query (fallback)
        if not relevant_chunks:
            logger.warning("RPC search failed, trying direct database query")
            try:
                # Get chunks directly using the new method
                chunks = await db.get_doc_chunks_by_subject(request.subject_id, 30)
                if chunks:
                    relevant_chunks = chunks
                    logger.info(f"Direct query found {len(relevant_chunks)} chunks")
            except Exception as e:
                logger.error(f"Direct query also failed: {e}")
        
        # Apply chapter/content filtering if specified
        content_filter = request.content_filter or request.topic_focus
        if relevant_chunks and (request.chapter_keywords or content_filter):
            filtered_chunks = []
            
            for chunk in relevant_chunks:
                chunk_text = chunk.get("text", "").lower()
                
                # Filter by chapter keywords
                if request.chapter_keywords:
                    if any(keyword.lower() in chunk_text for keyword in request.chapter_keywords):
                        filtered_chunks.append(chunk)
                        continue
                
                # Filter by content filter
                if content_filter:
                    if content_filter.lower() in chunk_text:
                        filtered_chunks.append(chunk)
                        continue
            
            if filtered_chunks:
                relevant_chunks = filtered_chunks
                logger.info(f"Content filtering reduced chunks to {len(relevant_chunks)}")
            else:
                logger.warning("Content filtering removed all chunks, using original set")
        
        # If still no chunks, try a different approach - get all chunks for the subject
        if not relevant_chunks:
            logger.warning("No chunks found with similarity search, trying to get all chunks")
            try:
                # First check if any chunks exist for this subject
                chunks = await db.get_doc_chunks_by_subject(request.subject_id, 50)
                if chunks:
                    relevant_chunks = chunks
                    logger.info(f"Found {len(relevant_chunks)} chunks directly from database")
                else:
                    logger.error("No chunks found in database for this subject")
                    
                    # Check if documents exist and are processed
                    docs = await db.get_documents(request.subject_id)
                    if docs:
                        processed_docs = [d for d in docs if d.get('processing_status') == 'completed']
                        logger.error(f"Found {len(docs)} documents, {len(processed_docs)} processed")
                        
                        if not processed_docs:
                            raise HTTPException(
                                status_code=400,
                                detail="Documents found but not processed. Please wait for document processing to complete or re-upload documents."
                            )
                    else:
                        logger.error("No documents found for this subject")
                        
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error getting chunks directly: {e}")
        
        if not relevant_chunks:
            raise HTTPException(
                status_code=400,
                detail=f"No content found for paper generation. Please ensure documents are uploaded and processed for subject {request.subject_id}. Check document processing status."
            )
        
        # Organize content for question generation
        from routers.rag import organize_content_for_questions
        organized_content = await organize_content_for_questions(relevant_chunks, request.question_count)
        
        # Resolve question count and types from question_type_counts if provided
        if request.question_type_counts:
            resolved_types = list(request.question_type_counts.keys())
            resolved_count = sum(request.question_type_counts.values())
        else:
            resolved_types = request.question_types
            resolved_count = request.question_count

        # Generate questions using RAG content
        questions = await llm_service.generate_questions_from_rag_content(
            organized_content=organized_content,
            question_count=resolved_count,
            question_types=resolved_types,
            difficulty_level=request.difficulty_level,
            subject_id=request.subject_id,
            question_type_counts=request.question_type_counts
        )
        
        if not questions:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate questions from document content"
            )
        
        # Sort questions by type for proper ordering (MCQs first, then short answer, etc.)
        questions = _sort_questions_by_type(questions, resolved_types)

        # Normalize field names: add 'marks' alias and 'difficulty' string
        _diff_map = {1: 'easy', 2: 'easy', 3: 'medium', 4: 'hard', 5: 'hard'}
        for q in questions:
            if 'marks' not in q:
                q['marks'] = q.get('max_score', 5)
            if 'difficulty' not in q:
                raw_dl = q.get('difficulty_level', 3)
                try:
                    q['difficulty'] = _diff_map.get(int(raw_dl), 'medium')
                except (TypeError, ValueError):
                    q['difficulty'] = str(raw_dl) if raw_dl else 'medium'

        # Create answer key using the sorted question IDs
        answer_key = {}
        total_marks = 0

        for question in questions:
            question_id = question.get("id", f"q{question.get('question_number', 1)}")
            answer_key[question_id] = question.get("correct_answer", "")
            total_marks += question.get("marks", question.get("max_score", 5))
        
        teacher_defaults = _teacher_paper_defaults(current_teacher, subject_name)
        resolved_template = _normalize_template_key(request.template or teacher_defaults["template"])
        resolved_student_fields = request.student_fields or teacher_defaults["student_fields"]
        resolved_institution = request.institution_name or teacher_defaults["institution_name"]
        resolved_faculty = request.faculty_name or teacher_defaults["faculty_name"]
        resolved_department = request.department_name or teacher_defaults["department_name"]
        resolved_program = request.program_name or teacher_defaults["program_name"]
        resolved_session = request.session_name or teacher_defaults["session_name"]
        resolved_teacher_name = request.teacher_name or teacher_defaults["teacher_name"]
        resolved_course = request.course_name or teacher_defaults["course_name"]
        resolved_course_code = request.course_code or teacher_defaults["course_code"]
        resolved_duration = request.duration or teacher_defaults["duration"]
        resolved_instructions = request.instructions or teacher_defaults["instructions"]

        # Create paper record
        paper_data = {
            "id": str(uuid.uuid4()),
            "subject_id": request.subject_id,
            "class_id": request.class_id,
            "owner_id": current_teacher["id"],
            "title": request.title,
            "description": request.description or "",
            "questions": questions,
            "answer_key": answer_key,
            "total_marks": total_marks,
            "configuration": {
                "question_types": resolved_types,
                "difficulty_level": request.difficulty_level,
                "time_limit": request.time_limit,
                "template": resolved_template,
                "institution_name": resolved_institution,
                "faculty_name": resolved_faculty,
                "department_name": resolved_department,
                "program_name": resolved_program,
                "session_name": resolved_session,
                "teacher_name": resolved_teacher_name,
                "course_name": resolved_course,
                "course_code": resolved_course_code,
                "exam_date": request.exam_date,
                "duration": resolved_duration,
                "instructions": resolved_instructions,
                "student_fields": resolved_student_fields,
                "question_type_counts": request.question_type_counts,
                "teacher_profile": {
                    "teacher_name": resolved_teacher_name,
                    "department": current_teacher.get("department"),
                    "designation": current_teacher.get("designation"),
                    "institution_type": current_teacher.get("institution_type"),
                    "institution_level": current_teacher.get("institution_level"),
                },
            },
            "is_published": False
        }
        
        paper = await db.create_paper(paper_data)
        if not paper:
            raise HTTPException(
                status_code=500,
                detail="Failed to create paper"
            )

        # Fire notification
        try:
            from services.notification_service import notify
            await notify(
                teacher_id=current_teacher["id"],
                title="Paper generated",
                message=f'"{request.title}" has been created with {len(questions)} questions ({total_marks} marks).',
                notification_type="paper_assigned",
                metadata={"paper_id": str(paper["id"]), "paper_title": request.title, "total_marks": total_marks},
            )
        except Exception:
            pass

        return PaperResponse(**_serialize_paper(paper))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating paper: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during paper generation"
        )


@router.post("/create-from-sheet", response_model=PaperResponse)
async def create_paper_from_question_sheet(
    request: PaperFromSheetRequest,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Create paper from uploaded question sheet using OCR and RAG system
    """
    try:
        logger.info(f"Paper creation from sheet request from teacher {current_teacher['id']}")
        
        # Get services
        db = await get_database()
        text_extractor = get_text_extractor()
        llm_service = get_llm_service()
        
        # Verify teacher has access to the subject
        subjects = await db.get_subjects(current_teacher["id"])
        subject_ids = [str(s["id"]) for s in subjects]

        if request.subject_id not in subject_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this subject"
            )

        # Decode and process the question sheet image
        import base64
        import io
        from PIL import Image
        
        try:
            # Remove data URL prefix if present
            image_data = request.question_sheet_image
            if image_data.startswith('data:image'):
                image_data = image_data.split(',')[1]
            
            # Decode base64 image
            image_bytes = base64.b64decode(image_data)
            
            # Extract text using OCR
            ocr_text = await text_extractor.extract_text(image_bytes, "image")
            
            if not ocr_text or len(ocr_text.strip()) < 50:
                raise HTTPException(
                    status_code=400,
                    detail="Could not extract sufficient text from the question sheet. Please ensure the image is clear and readable."
                )
            
        except Exception as e:
            logger.error(f"Error processing question sheet image: {e}")
            raise HTTPException(
                status_code=400,
                detail="Failed to process question sheet image"
            )
        
        # Use RAG system to enhance and validate the extracted questions
        # Get documents for context
        documents = await db.get_documents(request.subject_id)
        
        if documents:
            # Use RAG to get relevant content for validation
            from services.embedding_service import get_embedding_service
            embedding_service = get_embedding_service()
            
            # Create query from extracted text
            content_query = f"Validate and enhance questions about {request.subject_id}: {ocr_text[:200]}"
            
            query_embedding = await embedding_service.generate_query_embedding(content_query)
            if query_embedding:
                relevant_chunks = await db.search_similar_chunks(
                    embedding=query_embedding,
                    subject_id=request.subject_id,
                    limit=10
                )
                
                # Combine OCR text with relevant content for better processing
                if relevant_chunks:
                    context_content = "\n\n".join([chunk.get("text", "") for chunk in relevant_chunks[:5]])
                    enhanced_text = f"CONTEXT FROM DOCUMENTS:\n{context_content}\n\nEXTRACTED QUESTIONS:\n{ocr_text}"
                else:
                    enhanced_text = ocr_text
            else:
                enhanced_text = ocr_text
        else:
            enhanced_text = ocr_text
        
        # Process the text to extract and structure questions
        questions = await llm_service.process_question_sheet_text(
            text=enhanced_text,
            subject_id=request.subject_id
        )
        
        if not questions:
            raise HTTPException(
                status_code=400,
                detail="Could not extract valid questions from the sheet. Please ensure the question sheet is properly formatted."
            )
        
        # Sort questions by type for proper ordering (MCQs first, then short answer, etc.)
        # Extract question types from the generated questions
        question_types = list(set([q.get('question_type', 'short_answer') for q in questions]))
        questions = _sort_questions_by_type(questions, question_types)
        
        # Create answer key using the sorted question IDs
        answer_key = {}
        total_marks = 0
        
        for question in questions:
            question_id = question.get("id", f"q{question.get('question_number', 1)}")
            answer_key[question_id] = question.get("correct_answer", "")
            total_marks += question.get("max_score", 5)

        subject_name = ""
        try:
            subject_data = await db.get_subject(request.subject_id)
            subject_name = subject_data.get("name", "") if subject_data else ""
        except Exception:
            subject_name = ""
        teacher_defaults = _teacher_paper_defaults(current_teacher, subject_name)
        
        # Create paper record
        paper_data = {
            "id": str(uuid.uuid4()),
            "subject_id": request.subject_id,
            "class_id": request.class_id,
            "owner_id": current_teacher["id"],
            "title": request.title,
            "description": request.description or "",
            "questions": questions,
            "answer_key": answer_key,
            "total_marks": total_marks,
            "configuration": {
                "source": "question_sheet",
                "ocr_text": ocr_text,
                "template": teacher_defaults["template"],
                "institution_name": teacher_defaults["institution_name"],
                "faculty_name": teacher_defaults["faculty_name"],
                "department_name": teacher_defaults["department_name"],
                "program_name": teacher_defaults["program_name"],
                "session_name": teacher_defaults["session_name"],
                "teacher_name": teacher_defaults["teacher_name"],
                "course_name": teacher_defaults["course_name"],
                "course_code": teacher_defaults["course_code"],
                "duration": teacher_defaults["duration"],
                "instructions": teacher_defaults["instructions"],
                "student_fields": teacher_defaults["student_fields"],
                "teacher_profile": {
                    "teacher_name": teacher_defaults["teacher_name"],
                    "department": current_teacher.get("department"),
                    "designation": current_teacher.get("designation"),
                    "institution_type": current_teacher.get("institution_type"),
                    "institution_level": current_teacher.get("institution_level"),
                },
            },
            "is_published": False
        }
        
        paper = await db.create_paper(paper_data)
        if not paper:
            raise HTTPException(
                status_code=500,
                detail="Failed to create paper"
            )
        
        return PaperResponse(**_serialize_paper(paper))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating paper from sheet: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during paper creation"
        )


@router.get("/{paper_id}/preview", response_model=PaperResponse)
async def preview_paper(
    paper_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Preview generated paper before publishing
    """
    try:
        db = await get_database()
        
        # Get paper details
        paper = await db.get_paper(paper_id)
        if not paper:
            raise HTTPException(
                status_code=404,
                detail="Paper not found"
            )
        
        # Verify teacher has access
        if str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(
                status_code=403,
                detail="Access denied to this paper"
            )
        
        return PaperResponse(**_serialize_paper(paper))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error previewing paper: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.post("/{paper_id}/publish")
async def publish_paper(
    paper_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Publish paper to make it available for grading
    """
    try:
        db = await get_database()
        
        # Get paper details
        paper = await db.get_paper(paper_id)
        if not paper:
            raise HTTPException(
                status_code=404,
                detail="Paper not found"
            )
        
        # Verify teacher has access
        if str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(
                status_code=403,
                detail="Access denied to this paper"
            )
        
        # Update paper status
        updated_paper = await db.update_paper(paper_id, {
            "is_published": True,
            "published_at": "now()"
        })
        
        if not updated_paper:
            raise HTTPException(
                status_code=500,
                detail="Failed to publish paper"
            )

        # Fire notification
        try:
            from services.notification_service import notify
            await notify(
                teacher_id=current_teacher["id"],
                title="Paper published",
                message=f'"{paper["title"]}" is now published and ready to distribute.',
                notification_type="paper_published",
                metadata={"paper_id": paper_id, "paper_title": paper.get("title", "")},
            )
        except Exception:
            pass

        return PaperResponse(**_serialize_paper(updated_paper))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error publishing paper: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/{paper_id}/export")
async def export_paper(
    paper_id: str,
    format: str = "pdf",
    template_name: Optional[str] = Query(default=None, alias="template"),
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Export paper in printable format (PDF, HTML, or plain text).
    Supports the formal PDF template.
    """
    try:
        db = await get_database()

        # Get paper details
        paper = await db.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        # Verify teacher has access
        if str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this paper")

        paper = _normalize_paper_row(paper)

        teacher_info = await db.get_teacher(str(paper["owner_id"]))
        teacher_defaults = _teacher_paper_defaults(teacher_info)

        # Extract metadata from configuration
        _cfg = paper.get("configuration") or {}
        if isinstance(_cfg, str):
            import json as _j2
            try:
                _cfg = _j2.loads(_cfg)
            except Exception:
                _cfg = {}

        paper_meta = {
            "institution_name": _cfg.get("institution_name") or teacher_defaults["institution_name"],
            "faculty_name": _cfg.get("faculty_name") or teacher_defaults["faculty_name"],
            "department_name": _cfg.get("department_name") or teacher_defaults["department_name"],
            "program_name": _cfg.get("program_name") or teacher_defaults["program_name"],
            "session_name": _cfg.get("session_name") or teacher_defaults["session_name"],
            "teacher_name": _cfg.get("teacher_name") or teacher_defaults["teacher_name"],
            "course_name": _cfg.get("course_name") or teacher_defaults["course_name"],
            "course_code": _cfg.get("course_code") or teacher_defaults["course_code"],
            "exam_date": _cfg.get("exam_date", "________________"),
            "duration": _cfg.get("duration") or teacher_defaults["duration"],
            "instructions": _cfg.get("instructions") or teacher_defaults["instructions"],
            "student_fields": _cfg.get("student_fields") or teacher_defaults["student_fields"],
        }
        # Template: query param overrides stored config
        resolved_template = _normalize_template_key(
            template_name or _cfg.get("template") or teacher_defaults["template"]
        )

        # Generate printable content (text fallback)
        printable_content = _generate_printable_content(paper)

        if format.lower() == "pdf":
            try:
                # Get extra context
                subject_info = await db.get_subject(str(paper['subject_id']))
                class_info = None
                if subject_info and subject_info.get('class_id'):
                    class_info = await db.get_class(str(subject_info['class_id']))
                teacher_name = paper_meta["teacher_name"]
                subject_name = subject_info.get('name', 'Unknown Subject') if subject_info else 'Unknown Subject'
                class_name = class_info.get('name', '') if class_info else ''

                pdf_bytes = _build_paper_pdf(
                    paper=paper,
                    meta=paper_meta,
                    template=resolved_template,
                    subject_name=subject_name,
                    class_name=class_name,
                    teacher_name=teacher_name,
                )

                from fastapi.responses import Response
                safe_title = paper['title'].replace(' ', '_').replace('/', '-')
                return Response(
                    content=pdf_bytes,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={safe_title}.pdf"}
                )
            except ImportError:
                logger.warning("ReportLab not installed, falling back to HTML")
                from fastapi.responses import HTMLResponse
                html_content = _generate_html_paper(paper, printable_content)
                return HTMLResponse(content=html_content, media_type="text/html")
            except Exception as e:
                logger.error(f"Error generating PDF: {e}")
                from fastapi.responses import HTMLResponse
                html_content = _generate_html_paper(paper, printable_content)
                return HTMLResponse(content=html_content, media_type="text/html")

        elif format.lower() == "html":
            from fastapi.responses import HTMLResponse
            html_content = _generate_html_paper(paper, printable_content)
            return HTMLResponse(content=html_content, media_type="text/html")

        elif format.lower() == "txt":
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(content=printable_content, media_type="text/plain")

        else:
            raise HTTPException(status_code=400, detail="Unsupported format. Use 'pdf', 'html', or 'txt'")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting paper: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{paper_id}/printable")
async def get_printable_paper(
    paper_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Get paper in printable format with proper structure
    """
    try:
        db = await get_database()
        
        # Get paper details
        paper = await db.get_paper(paper_id)
        if not paper:
            raise HTTPException(
                status_code=404,
                detail="Paper not found"
            )
        
        # Verify teacher has access
        if str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(
                status_code=403,
                detail="Access denied to this paper"
            )

        paper = _normalize_paper_row(paper)
        
        # Generate printable format
        printable_paper = _generate_printable_paper_format(paper)
        
        return printable_paper
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting printable paper: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/{paper_id}/answer-key")
async def download_answer_key(
    paper_id: str,
    format: str = Query(default="pdf", description="Export format: pdf, html, txt"),
    current_user: dict = Depends(require_teacher())
):
    """Download answer key for a paper"""
    try:
        logger.info(f"Generating answer key for paper {paper_id} in format {format}")
        
        # Get paper from database
        db = await get_database()
        paper = await db.get_paper(paper_id)
        
        if not paper:
            logger.error(f"Paper {paper_id} not found")
            raise HTTPException(status_code=404, detail="Paper not found")
        
        # Check ownership
        if str(paper['owner_id']) != str(current_user['id']):
            logger.error(f"Access denied for user {current_user['id']} to paper {paper_id}")
            raise HTTPException(status_code=403, detail="Access denied")

        paper = _normalize_paper_row(paper)
        
        # Validate paper has questions and answer key
        questions = paper.get('questions', [])
        answer_key = paper.get('answer_key', {})
        
        if not questions:
            logger.error(f"Paper {paper_id} has no questions")
            raise HTTPException(status_code=400, detail="Paper has no questions")
        
        if not answer_key:
            logger.error(f"Paper {paper_id} has no answer key")
            raise HTTPException(status_code=400, detail="Paper has no answer key")

        cfg = paper.get("configuration") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        teacher_defaults = _teacher_paper_defaults(current_user)
        institution_name = cfg.get("institution_name") or teacher_defaults["institution_name"]
        teacher_name = cfg.get("teacher_name") or teacher_defaults["teacher_name"]
        
        if format.lower() == "pdf":
            # Generate PDF answer key
            try:
                from reportlab.lib.pagesizes import letter, A4
                from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import inch
                from reportlab.lib.enums import TA_CENTER, TA_LEFT
                from reportlab.lib import colors
                import io
                
                # Get paper details safely
                subject_info = None
                try:
                    subject_info = await db.get_subject(paper['subject_id'])
                except Exception as e:
                    logger.warning(f"Could not get subject info: {e}")
                
                try:
                    teacher_info = await db.get_teacher(str(paper['owner_id']))
                    if teacher_info:
                        teacher_name = cfg.get("teacher_name") or teacher_info.get('name', teacher_name)
                except Exception as e:
                    logger.warning(f"Could not get teacher info: {e}")
                
                # Create PDF buffer
                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4, 
                                      rightMargin=50, leftMargin=50, 
                                      topMargin=50, bottomMargin=50)
                
                # Get styles
                styles = getSampleStyleSheet()
                
                title_style = ParagraphStyle(
                    'Title',
                    parent=styles['Heading1'],
                    fontSize=16,
                    spaceAfter=20,
                    alignment=TA_CENTER,
                    textColor=colors.black
                )
                
                question_style = ParagraphStyle(
                    'Question',
                    parent=styles['Normal'],
                    fontSize=11,
                    spaceAfter=8,
                    leftIndent=0
                )
                
                answer_style = ParagraphStyle(
                    'Answer',
                    parent=styles['Normal'],
                    fontSize=11,
                    spaceAfter=12,
                    leftIndent=20,
                    textColor=colors.darkgreen
                )
                
                # Build content
                story = []
                
                # Header
                story.append(Paragraph("ANSWER KEY", title_style))
                story.append(Paragraph(institution_name, styles['Normal']))
                story.append(Paragraph(f"Paper: {paper.get('title', 'Untitled Paper')}", styles['Normal']))
                story.append(Paragraph(f"Subject: {subject_info.get('name', 'Unknown Subject') if subject_info else 'Unknown Subject'}", styles['Normal']))
                story.append(Paragraph(f"Teacher: {teacher_name}", styles['Normal']))
                story.append(Paragraph(f"Total Marks: {paper.get('total_marks', 0)}", styles['Normal']))
                story.append(Spacer(1, 20))
                
                # Organize questions by type
                questions = paper.get('questions', [])
                answer_key = paper.get('answer_key', {})
                
                mcq_questions = [q for q in questions if q.get('question_type') == 'mcq']
                short_questions = [q for q in questions if q.get('question_type') == 'short_answer']
                long_questions = [q for q in questions if q.get('question_type') in ['essay', 'long_answer']]
                other_questions = [q for q in questions if q.get('question_type') not in ['mcq', 'short_answer', 'essay', 'long_answer']]
                
                question_num = 1
                
                # MCQ Answers
                if mcq_questions:
                    story.append(Paragraph("SECTION A: MULTIPLE CHOICE ANSWERS", ParagraphStyle('SectionBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, spaceAfter=10)))
                    
                    for question in mcq_questions:
                        question_id = f"q{question_num}"
                        answer = answer_key.get(question_id, question.get('correct_answer', 'No answer'))
                        
                        story.append(Paragraph(f"Q{question_num}. {question.get('question_text', 'No question text')[:100]}...", question_style))
                        story.append(Paragraph(f"Answer: {answer}", answer_style))
                        question_num += 1
                
                # Short Answer Solutions
                if short_questions:
                    story.append(Paragraph("SECTION B: SHORT ANSWER SOLUTIONS", ParagraphStyle('SectionBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, spaceAfter=10, spaceBefore=15)))
                    
                    for question in short_questions:
                        question_id = f"q{question_num}"
                        answer = answer_key.get(question_id, question.get('correct_answer', 'Sample answer not provided'))
                        
                        story.append(Paragraph(f"Q{question_num}. {question.get('question_text', 'No question text')}", question_style))
                        story.append(Paragraph(f"Answer: {answer}", answer_style))
                        story.append(Spacer(1, 10))
                        question_num += 1
                
                # Long Answer Solutions
                if long_questions:
                    story.append(Paragraph("SECTION C: LONG ANSWER SOLUTIONS", ParagraphStyle('SectionBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, spaceAfter=10, spaceBefore=15)))
                    
                    for question in long_questions:
                        question_id = f"q{question_num}"
                        answer = answer_key.get(question_id, question.get('correct_answer', 'Detailed answer not provided'))
                        
                        story.append(Paragraph(f"Q{question_num}. {question.get('question_text', 'No question text')}", question_style))
                        story.append(Paragraph(f"Answer: {answer}", answer_style))
                        story.append(Spacer(1, 15))
                        question_num += 1
                
                # Other Answers
                if other_questions:
                    story.append(Paragraph("SECTION D: OTHER ANSWERS", ParagraphStyle('SectionBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, spaceAfter=10, spaceBefore=15)))
                    
                    for question in other_questions:
                        question_id = f"q{question_num}"
                        answer = answer_key.get(question_id, question.get('correct_answer', 'Answer not provided'))
                        
                        story.append(Paragraph(f"Q{question_num}. {question.get('question_text', 'No question text')}", question_style))
                        story.append(Paragraph(f"Answer: {answer}", answer_style))
                        story.append(Spacer(1, 10))
                        question_num += 1
                
                # Build PDF
                doc.build(story)
                
                # Get PDF bytes
                pdf_bytes = buffer.getvalue()
                buffer.close()
                
                from fastapi.responses import Response
                filename = f"{paper.get('title', 'Paper').replace(' ', '_')}_Answer_Key.pdf"
                return Response(
                    content=pdf_bytes,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={filename}"}
                )
                
            except ImportError as e:
                logger.warning(f"ReportLab not installed: {e}, falling back to text")
                # Fallback to text format
                format = "txt"
            except Exception as e:
                logger.error(f"Error generating PDF answer key: {e}")
                # Fallback to text format
                format = "txt"
        
        if format.lower() == "txt":
            # Generate text answer key
            content = f"ANSWER KEY\n"
            content += f"Institution: {institution_name}\n"
            content += f"Teacher: {teacher_name}\n"
            content += f"Paper: {paper.get('title', 'Untitled Paper')}\n"
            content += f"Total Marks: {paper.get('total_marks', 0)}\n"
            content += "="*50 + "\n\n"
            
            for i, question in enumerate(questions, 1):
                question_id = f"q{i}"
                answer = answer_key.get(question_id, question.get('correct_answer', 'No answer'))
                content += f"Q{i}. {question.get('question_text', 'No question text')}\n"
                content += f"Answer: {answer}\n\n"
            
            from fastapi.responses import Response
            filename = f"{paper.get('title', 'Paper').replace(' ', '_')}_Answer_Key.txt"
            return Response(
                content=content,
                media_type="text/plain",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        
        elif format.lower() == "html":
            # Generate HTML answer key
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Answer Key - {paper.get('title', 'Untitled Paper')}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    .header {{ text-align: center; margin-bottom: 30px; }}
                    .question {{ margin-bottom: 20px; }}
                    .answer {{ color: #006600; margin-left: 20px; font-weight: bold; }}
                    .section {{ font-weight: bold; font-size: 14px; margin: 20px 0 10px 0; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>ANSWER KEY</h1>
                    <p>{institution_name}</p>
                    <p>Teacher: {teacher_name}</p>
                    <p>Paper: {paper.get('title', 'Untitled Paper')}</p>
                    <p>Total Marks: {paper.get('total_marks', 0)}</p>
                </div>
            """
            
            questions = paper.get('questions', [])
            answer_key = paper.get('answer_key', {})
            
            for i, question in enumerate(questions, 1):
                question_id = f"q{i}"
                answer = answer_key.get(question_id, question.get('correct_answer', 'No answer'))
                html_content += f"""
                <div class="question">
                    <p><strong>Q{i}.</strong> {question.get('question_text', 'No question text')}</p>
                    <p class="answer">Answer: {answer}</p>
                </div>
                """
            
            html_content += "</body></html>"
            
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content=html_content, media_type="text/html")
        
        else:
            raise HTTPException(status_code=400, detail="Invalid format. Use 'pdf', 'html', or 'txt'")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating answer key for paper {paper_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to generate answer key: {str(e)}"
        )


@router.get("/{paper_id}/grading-report")
async def export_paper_grading_report(
    paper_id: str,
    format: str = Query("pdf", pattern="^(pdf|csv)$"),
    class_id: Optional[str] = Query(None),
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """Download the class grading report for this selected paper."""
    try:
        from routers.grading import (
            _build_paper_class_report_data,
            _build_report_csv_response,
            _build_report_pdf_response,
        )

        db = await get_database()
        report = await _build_paper_class_report_data(db, paper_id, current_teacher, class_id_override=class_id)
        if format.lower() == "csv":
            return _build_report_csv_response(report)
        return _build_report_pdf_response(report)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting grading report for paper {paper_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error while generating report")


@router.post("/{paper_id}/grading-report/send")
async def send_paper_grading_report(
    paper_id: str,
    request: GradingReportSendRequest,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """Send the selected paper grading report by SMTP."""
    try:
        from services.email_service import EmailSender
        from routers.grading import _build_paper_class_report_data, _build_report_email_pdf_file, _fmt_pct

        db = await get_database()
        report = await _build_paper_class_report_data(db, paper_id, current_teacher, class_id_override=request.class_id)
        content, filename, media_type, selected_row = _build_report_email_pdf_file(report, student_id=request.student_id)

        recipient = (request.recipient_email or "").strip()
        if selected_row and not recipient:
            recipient = (selected_row.get("email") or "").strip()
        if not recipient:
            raise HTTPException(status_code=400, detail="Enter a recipient email address, or select a student with an email in the class roster")

        email_config = await db.get_email_config(current_teacher["id"])
        if not email_config or not email_config.get("is_active"):
            raise HTTPException(status_code=400, detail="Configure and enable teacher email SMTP settings before sending reports")

        sender = EmailSender(
            email_config["email_address"],
            email_config["app_password"],
            email_config.get("smtp_host") or "smtp.gmail.com",
            email_config.get("smtp_port") or 587,
            email_config.get("smtp_use_tls", True),
            email_config.get("smtp_use_ssl", False),
            email_config.get("from_name") or "EduMaster Reports",
        )
        if selected_row:
            subject = f"Result Report - {selected_row.get('student_name')} - {report['paper']['title']}"
            body = (
                f"Attached is the result report for {selected_row.get('student_name')} "
                f"for {report['paper']['title']} ({report['class']['name']} / {report['subject']['name']}).\n\n"
                f"Score: {selected_row.get('total_score') or '-'} / {selected_row.get('max_score') or '-'}\n"
                f"Percentage: {_fmt_pct(selected_row.get('percentage'))}\n"
                f"Grade: {selected_row.get('grade') or '-'}\n"
            )
        else:
            subject = f"Class Result Report - {report['paper']['title']} - {report['class']['name']}"
            body = (
                f"Attached is the class result report for {report['class']['name']} / {report['subject']['name']} "
                f"for the selected paper: {report['paper']['title']}.\n\n"
                f"Submitted: {report['summary']['submitted_count']}\n"
                f"Average: {_fmt_pct(report['summary']['average_percentage'])}\n"
                f"Pass rate: {_fmt_pct(report['summary']['pass_rate'])}\n"
            )

        result = sender.send_email(
            recipient,
            subject,
            body,
            [{"filename": filename, "content": content, "media_type": media_type}],
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message") or "Report email could not be sent")
        return {"status": "success", "message": f"Grading report sent to {recipient}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending grading report for paper {paper_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error while sending report")


def _generate_printable_content(paper: dict) -> str:
    """Generate printable text content for the paper"""
    content = []
    cfg = paper.get("configuration") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    
    # Header
    content.append("=" * 80)
    if cfg.get("institution_name"):
        content.append(str(cfg["institution_name"]).upper())
    content.append(f"QUESTION PAPER: {paper['title']}")
    content.append("=" * 80)
    
    if paper.get('description'):
        content.append(f"\nDescription: {paper['description']}")
    
    content.append(f"Total Marks: {paper.get('total_marks', 0)}")
    teacher_name = cfg.get("teacher_name") or (cfg.get("teacher_profile") or {}).get("teacher_name")
    if teacher_name:
        content.append(f"Teacher: {teacher_name}")
    if cfg.get("course_name"):
        content.append(f"Course: {cfg['course_name']}")
    if cfg.get("duration"):
        content.append(f"Duration: {cfg['duration']}")
    content.append(f"Created: {paper.get('created_at', 'Unknown')}")
    content.append("\n" + "=" * 80)
    
    # Questions
    questions = paper.get('questions', [])
    for i, question in enumerate(questions, 1):
        content.append(f"\nQ{i}. {question.get('question_text', 'No question text')}")
        
        # Add marks
        max_score = question.get('max_score', 5)
        content.append(f"[{max_score} marks]")
        
        # Add options for MCQ
        if question.get('question_type') == 'mcq' and question.get('options'):
            options = question['options']
            for j, option in enumerate(options):
                letter = chr(65 + j)  # A, B, C, D
                content.append(f"   {letter}) {option}")
        
        # Add space for answer
        content.append("\nAnswer: _________________________________")
        content.append("\n" + "-" * 40)
    
    # Answer key section
    content.append("\n\n" + "=" * 80)
    content.append("ANSWER KEY")
    content.append("=" * 80)
    
    answer_key = paper.get('answer_key', {})
    for i, question in enumerate(questions, 1):
        question_id = f"q{i}"
        answer = answer_key.get(question_id, "No answer provided")
        content.append(f"Q{i}. {answer}")
    
    return "\n".join(content)


def _generate_html_paper(paper: dict, printable_content: str) -> str:
    """Generate HTML format for the paper"""
    cfg = paper.get("configuration") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    institution = cfg.get("institution_name", "")
    teacher_name = cfg.get("teacher_name") or (cfg.get("teacher_profile") or {}).get("teacher_name", "")
    course = cfg.get("course_name", "")
    duration = cfg.get("duration", "")
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{paper['title']}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ text-align: center; border-bottom: 2px solid #333; padding-bottom: 10px; }}
            .question {{ margin: 20px 0; padding: 10px; border: 1px solid #ddd; }}
            .question-number {{ font-weight: bold; color: #333; }}
            .marks {{ color: #666; font-style: italic; }}
            .options {{ margin-left: 20px; }}
            .answer-space {{ border-bottom: 1px solid #333; margin: 10px 0; }}
            .answer-key {{ background-color: #f5f5f5; padding: 20px; margin-top: 30px; }}
            @media print {{ 
                body {{ margin: 0; }}
                .no-print {{ display: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="header">
            {f'<h2>{institution}</h2>' if institution else ''}
            <h1>{paper['title']}</h1>
            {f'<p>Teacher: {teacher_name}</p>' if teacher_name else ''}
            {f'<p>Course: {course}</p>' if course else ''}
            <p>Total Marks: {paper.get('total_marks', 0)}</p>
            {f'<p>Duration: {duration}</p>' if duration else ''}
            <p>Created: {paper.get('created_at', 'Unknown')}</p>
        </div>
        
        <div class="questions">
    """
    
    questions = paper.get('questions', [])
    for i, question in enumerate(questions, 1):
        html += f"""
            <div class="question">
                <div class="question-number">Q{i}.</div>
                <div class="question-text">{question.get('question_text', 'No question text')}</div>
                <div class="marks">[{question.get('max_score', 5)} marks]</div>
        """
        
        # Add options for MCQ
        if question.get('question_type') == 'mcq' and question.get('options'):
            html += '<div class="options">'
            options = question['options']
            for j, option in enumerate(options):
                letter = chr(65 + j)  # A, B, C, D
                html += f'<div>{letter}) {option}</div>'
            html += '</div>'
        
        # Add answer space
        html += '<div class="answer-space">Answer: _________________________________</div>'
        html += '</div>'
    
    # Answer key
    html += """
        </div>
        
        <div class="answer-key">
            <h2>ANSWER KEY</h2>
    """
    
    answer_key = paper.get('answer_key', {})
    for i, question in enumerate(questions, 1):
        question_id = f"q{i}"
        answer = answer_key.get(question_id, "No answer provided")
        html += f'<div>Q{i}. {answer}</div>'
    
    html += """
        </div>
    </body>
    </html>
    """
    
    return html


def _generate_printable_paper_format(paper: dict) -> dict:
    """Generate structured printable format for the paper"""
    questions = paper.get('questions', [])
    
    # Calculate statistics
    total_marks = sum(q.get('max_score', 5) for q in questions)
    question_types = {}
    difficulty_levels = {}
    
    for question in questions:
        q_type = question.get('question_type', 'unknown')
        difficulty = question.get('difficulty_level', 1)
        
        question_types[q_type] = question_types.get(q_type, 0) + 1
        difficulty_levels[difficulty] = difficulty_levels.get(difficulty, 0) + 1
    
    # Generate printable questions
    printable_questions = []
    for i, question in enumerate(questions, 1):
        printable_q = {
            "question_number": i,
            "question_text": question.get('question_text', ''),
            "question_type": question.get('question_type', 'short_answer'),
            "max_score": question.get('max_score', 5),
            "difficulty_level": question.get('difficulty_level', 1),
            "printable_format": question.get('printable_format', ''),
            "options": question.get('options', []),
            "correct_answer": question.get('correct_answer', ''),
            "explanation": question.get('explanation', '')
        }
        printable_questions.append(printable_q)
    
    return {
        "paper_info": {
            "id": paper['id'],
            "title": paper['title'],
            "description": paper.get('description', ''),
            "subject_id": paper['subject_id'],
            "class_id": paper.get('class_id'),
            "created_at": paper['created_at'],
            "is_published": paper.get('is_published', False)
        },
        "statistics": {
            "total_questions": len(questions),
            "total_marks": total_marks,
            "question_type_distribution": question_types,
            "difficulty_distribution": difficulty_levels,
            "estimated_time": f"{len(questions) * 3} minutes"
        },
        "questions": printable_questions,
        "answer_key": paper.get('answer_key', {}),
        "printable_content": _generate_printable_content(paper)
    }


@router.get("/documents/{subject_id}")
async def list_subject_documents(
    subject_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    List documents for a subject to help with chapter-specific paper generation
    """
    try:
        db = await get_database()
        
        # Verify teacher has access to the subject
        subjects = await db.get_subjects(current_teacher["id"])
        subject_ids = [s["id"] for s in subjects]
        
        if subject_id not in subject_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this subject"
            )
        
        # Get documents for the subject
        documents = await db.get_documents(subject_id)
        
        # Return document info for chapter selection
        document_info = []
        for doc in documents:
            display_filename = doc.get("original_filename") or doc.get("filename") or "Untitled document"
            document_info.append({
                "id": doc["id"],
                "filename": display_filename,
                "original_filename": display_filename,
                "processing_status": doc.get("processing_status", "unknown"),
                "created_at": doc.get("created_at"),
                "file_size": doc.get("file_size")
            })
        
        return {
            "subject_id": subject_id,
            "documents": document_info,
            "total": len(document_info)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing subject documents: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/")
async def list_papers(
    subject_id: Optional[str] = None,
    class_id: Optional[str] = None,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    List papers for teacher
    """
    try:
        db = await get_database()
        
        # Get papers for teacher
        papers = await db.get_papers(current_teacher["id"])
        
        # Filter by subject or class if specified (compare as strings to handle UUID objects)
        if subject_id:
            papers = [p for p in papers if str(p.get("subject_id", "")) == subject_id]
        
        if class_id:
            papers = [p for p in papers if str(p.get("class_id", "")) == class_id]
        
        return {
            "papers": [_serialize_paper(p) for p in papers],
            "total": len(papers)
        }
        
    except Exception as e:
        logger.error(f"Error listing papers: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(
    paper_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """Get paper by ID"""
    try:
        db = await get_database()
        paper = await db.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        if str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this paper")
        return PaperResponse(**_serialize_paper(paper))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting paper {paper_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{paper_id}", response_model=PaperResponse)
async def update_paper_endpoint(
    paper_id: str,
    payload: dict,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """Update paper fields (title, questions, metadata, template, etc.)"""
    try:
        db = await get_database()
        paper = await db.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        if str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this paper")

        # Fields that map directly to DB columns
        allowed_direct = {"title", "description", "questions", "answer_key", "total_marks",
                          "difficulty_level", "time_limit", "is_published", "class_id"}
        # Fields that live inside the `configuration` JSONB column
        meta_fields = {"template", "institution_name", "faculty_name", "department_name",
                   "program_name", "session_name", "teacher_name", "course_name",
                   "course_code", "exam_date", "duration", "instructions",
                   "student_fields"}

        update_data: dict = {k: v for k, v in payload.items() if k in allowed_direct}

        # Merge metadata into configuration
        if any(k in payload for k in meta_fields):
            existing_cfg = paper.get("configuration") or {}
            if isinstance(existing_cfg, str):
                import json as _jj
                try:
                    existing_cfg = _jj.loads(existing_cfg)
                except Exception:
                    existing_cfg = {}
            for k in meta_fields:
                if k in payload:
                    existing_cfg[k] = payload[k]
            update_data["configuration"] = existing_cfg

        updated = await db.update_paper(paper_id, update_data)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update paper")

        return PaperResponse(**_serialize_paper(updated))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating paper {paper_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{paper_id}")
async def delete_paper(
    paper_id: str,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """Delete a paper"""
    try:
        db = await get_database()
        paper = await db.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        if str(paper["owner_id"]) != str(current_teacher["id"]):
            raise HTTPException(status_code=403, detail="Access denied to this paper")

        import uuid as _uuid
        async with db.connection() as conn:
            await conn.execute("DELETE FROM papers WHERE id = $1", _uuid.UUID(paper_id))
        return {"deleted": True, "paper_id": paper_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting paper {paper_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def _serialize_paper(paper: dict) -> dict:
    """Serialize a paper DB row to a JSON-safe dict"""
    import json as _j

    def _parse_json(val, default):
        if isinstance(val, str):
            try:
                return _j.loads(val)
            except Exception:
                return default
        return val if val is not None else default

    cfg = _parse_json(paper.get("configuration"), {})
    return {
        "id": str(paper["id"]),
        "title": paper.get("title", ""),
        "description": paper.get("description") or "",
        "subject_id": str(paper["subject_id"]),
        "class_id": str(paper["class_id"]) if paper.get("class_id") else None,
        "questions": _parse_json(paper.get("questions"), []),
        "answer_key": _parse_json(paper.get("answer_key"), {}),
        "total_marks": paper.get("total_marks") or 0,
        "is_published": paper.get("is_published", False),
        "difficulty_level": cfg.get("difficulty_level", "medium"),
        "template": _normalize_template_key(cfg.get("template")),
        "institution_name": cfg.get("institution_name"),
        "faculty_name": cfg.get("faculty_name"),
        "department_name": cfg.get("department_name"),
        "program_name": cfg.get("program_name"),
        "session_name": cfg.get("session_name"),
        "teacher_name": cfg.get("teacher_name") or (cfg.get("teacher_profile") or {}).get("teacher_name"),
        "course_name": cfg.get("course_name"),
        "course_code": cfg.get("course_code"),
        "exam_date": cfg.get("exam_date"),
        "duration": cfg.get("duration"),
        "instructions": cfg.get("instructions"),
        "student_fields": cfg.get("student_fields", ["name", "roll_number"]),
        "teacher_id": str(paper["owner_id"]) if paper.get("owner_id") else None,
        "created_at": str(paper["created_at"]),
    }


def _normalize_paper_row(paper: dict) -> dict:
    """Normalize a paper row by parsing JSON fields for internal use."""
    def _parse_json(val, default):
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return default
        return val if val is not None else default

    normalized = dict(paper)
    normalized["configuration"] = _parse_json(paper.get("configuration"), {})
    normalized["questions"] = _parse_json(paper.get("questions"), [])
    normalized["answer_key"] = _parse_json(paper.get("answer_key"), {})

    if not isinstance(normalized["configuration"], dict):
        normalized["configuration"] = {}
    if not isinstance(normalized["questions"], list):
        normalized["questions"] = []
    if not isinstance(normalized["answer_key"], dict):
        normalized["answer_key"] = {}

    return normalized


def _build_paper_pdf(
    paper: dict,
    meta: dict,
    template: str,
    subject_name: str = "",
    class_name: str = "",
    teacher_name: str = "",
) -> bytes:
    """Build a PDF for the paper using the specified template. Returns raw bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, cm
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib import colors
    import io

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()

    questions = paper.get("questions", [])
    title = paper.get("title", "Examination Paper")
    total_marks = paper.get("total_marks", 0)
    institution = meta.get("institution_name") or "EduMaster Institute"
    course = meta.get("course_name") or subject_name
    exam_date = meta.get("exam_date") or "________________"
    duration = meta.get("duration") or "3 Hours"
    custom_instructions = meta.get("instructions") or ""
    student_fields = meta.get("student_fields") or ["name", "roll_number"]

    template = _normalize_template_key(template)
    base_font = "Times-Roman"
    bold_font = "Times-Bold"
    faculty_name = meta.get("faculty_name") or ""
    department_name = meta.get("department_name") or ""
    program_name = meta.get("program_name") or ""
    session_name = meta.get("session_name") or ""
    course_code = meta.get("course_code") or ""
    note_text = custom_instructions or "Attempt all questions."

    def _line_value(value, length=24):
        if value is None:
            return "_" * length
        if isinstance(value, (int, float)):
            if value == 0:
                return "_" * length
            return str(value)
        if isinstance(value, str) and value.strip():
            return value
        return "_" * length


    def _clean_option(opt: str) -> str:
        clean = opt.strip()
        for prefix in ("A)", "B)", "C)", "D)", "a)", "b)", "c)", "d)"):
            if clean.startswith(prefix):
                clean = clean[2:].strip()
        return clean

    def _format_question_text(q: dict, extra_lines: int) -> str:
        text = (q.get("question_text") or "").strip()
        if not text:
            text = "_" * 35
        if q.get("question_type") == "mcq" and q.get("options"):
            options = [f"{chr(65 + i)}) {_clean_option(opt)}" for i, opt in enumerate(q["options"]) if opt]
            if options:
                text += "<br/>" + "<br/>".join(options)
        if extra_lines > 0:
            text += "<br/>" * extra_lines
        return text

    def _add_section(story, section_title, section_questions, start_num, extra_lines):
        if not section_questions:
            return start_num
        story.append(Paragraph(section_title, ParagraphStyle(
            "Section", parent=styles["Normal"], fontName=bold_font,
            fontSize=12, alignment=TA_CENTER, spaceBefore=10, spaceAfter=6)))
        rows = [["Q No.", "Questions", "Marks", "CLOs"]]
        n = start_num
        q_style = ParagraphStyle("QStyle", parent=styles["Normal"], fontName=base_font, fontSize=9, leading=12)
        for q in section_questions:
            marks = q.get("marks") or q.get("max_score") or 5
            q_text = _format_question_text(q, extra_lines)
            rows.append([
                str(n),
                Paragraph(q_text, q_style),
                str(marks),
                "_" * 6,
            ])
            n += 1
        table = Table(
            rows,
            colWidths=[0.6 * inch, doc.width - (2.0 * inch), 0.7 * inch, 0.7 * inch],
            repeatRows=1,
        )
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f5")),
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 1), (2, -1), "CENTER"),
            ("ALIGN", (3, 1), (3, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))
        return n

    margin = 0.8 * inch
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )
    story = []

    header_title = ParagraphStyle("HdrTitle", parent=styles["Normal"], fontName=bold_font, fontSize=18, alignment=TA_CENTER, leading=20)
    header_sub = ParagraphStyle("HdrSub", parent=styles["Normal"], fontName=bold_font, fontSize=14, alignment=TA_CENTER, leading=16)
    story.append(Paragraph(institution.upper(), header_title))
    story.append(Paragraph(faculty_name or "Faculty Name", header_sub))
    story.append(Paragraph(department_name or "Department Name", header_sub))
    story.append(Spacer(1, 12))

    info_style = ParagraphStyle("Info", parent=styles["Normal"], fontName=base_font, fontSize=9, leading=12)

    field_labels = {
        "name": "Student Name",
        "roll_number": "Roll No.",
        "class": "Class",
        "section": "Section",
        "signature": "Signature",
        "father_name": "Father's Name",
    }

    def _student_box(story, fields):
        if not fields:
            return
        rows = []
        for f in fields:
            label = field_labels.get(f, f.replace("_", " ").title())
            rows.append([
                Paragraph(f"<b>{label}:</b>", info_style),
                Paragraph("_" * 32, info_style),
            ])
        table = Table(rows, colWidths=[1.6 * inch, doc.width - (1.6 * inch)])
        table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)
        story.append(Spacer(1, 10))

    session_value = session_name or exam_date
    info_rows = [
        [
            Paragraph(f"<b>Program:</b> {_line_value(program_name)}", info_style),
            Paragraph(f"<b>Time Allowed:</b> {_line_value(duration, 12)}", info_style),
        ],
        [
            Paragraph(f"<b>Session:</b> {_line_value(session_value)}", info_style),
            Paragraph(f"<b>Total Marks:</b> {_line_value(total_marks if total_marks else '', 12)}", info_style),
        ],
        [
            Paragraph(f"<b>Examination:</b> {_line_value(title, 18)}", info_style),
            Paragraph(f"<b>Instructor:</b> {_line_value(teacher_name, 18)}", info_style),
        ],
        [
            Paragraph(f"<b>Course Title:</b> {_line_value(course or subject_name, 18)}", info_style),
            Paragraph(f"<b>Course Code:</b> {_line_value(course_code, 12)}", info_style),
        ],
        [Paragraph(f"<b>Note:</b> {note_text}", info_style), ""],
    ]

    info_table = Table(info_rows, colWidths=[9.5 * cm, 6.5 * cm])
    info_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
        ("INNERGRID", (0, 0), (-1, -2), 0.5, colors.black),
        ("SPAN", (0, -1), (1, -1)),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story.append(info_table)
    story.append(Spacer(1, 8))
    _student_box(story, student_fields)
    story.append(Spacer(1, 8))

    short_questions = [q for q in questions if q.get("question_type") not in ("essay", "long_answer")]
    long_questions = [q for q in questions if q.get("question_type") in ("essay", "long_answer")]

    n = 1
    n = _add_section(story, "SECTION -- A : SHORT QUESTIONS", short_questions, n, 2)
    n = _add_section(story, "SECTION -- B : LONG QUESTIONS", long_questions, n, 6)

    sig_style = ParagraphStyle("Sig", parent=styles["Normal"], fontName=bold_font, fontSize=10)
    sig_table = Table(
        [[
            Paragraph("<b>Instructor Signature:</b> ____________________", sig_style),
            Paragraph("<b>HOD Signature:</b> ____________________", sig_style),
        ]],
        colWidths=[doc.width / 2, doc.width / 2],
    )
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(Spacer(1, 6))
    story.append(sig_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph("--- Best of Luck ---", ParagraphStyle(
        "BestLuck", parent=styles["Normal"], fontName=bold_font, fontSize=10, alignment=TA_CENTER)))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def _sort_questions_by_type(questions: List[dict], question_types: List[str]) -> List[dict]:
    """
    Sort questions by type in the standard order: MCQ, Short Answer, Essay, True/False, Others
    """
    # Define the standard order for question types
    type_order = {
        'mcq': 1,
        'multiple_choice': 1,
        'short_answer': 2,
        'essay': 3,
        'long_answer': 3,
        'true_false': 4,
        'fill_blank': 5,
        'fill_in_blank': 5
    }
    
    def get_type_priority(question):
        """Get priority for question type sorting"""
        q_type = question.get('question_type', 'short_answer').lower()
        return type_order.get(q_type, 99)  # Unknown types go to the end
    
    # Sort questions by type priority
    sorted_questions = sorted(questions, key=get_type_priority)
    
    # Update question numbers to reflect the new order
    for i, question in enumerate(sorted_questions):
        question['question_number'] = i + 1
        question['id'] = f"q{i+1}"
    
    logger.info(f"Sorted {len(sorted_questions)} questions by type: {[q.get('question_type') for q in sorted_questions]}")
    
    return sorted_questions
