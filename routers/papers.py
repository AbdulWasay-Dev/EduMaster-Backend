"""
Paper Management API endpoints
"""
import logging
import uuid
from typing import List, Optional, Dict
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
    template: str = Field(default="classic", description="Paper template: classic, university, school, minimalist")
    institution_name: Optional[str] = Field(None, description="Institution / school name for the paper header")
    course_name: Optional[str] = Field(None, description="Course name displayed on the paper")
    exam_date: Optional[str] = Field(None, description="Exam date displayed on the paper")
    duration: Optional[str] = Field(None, description="Duration string e.g. '3 Hours'")
    instructions: Optional[str] = Field(None, description="Custom paper instructions")
    student_fields: Optional[List[str]] = Field(default=["name", "roll_number"], description="Student detail fields to show on paper")


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
    template: str = "classic"
    institution_name: Optional[str] = None
    course_name: Optional[str] = None
    exam_date: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    student_fields: Optional[List[str]] = None


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
        if relevant_chunks and (request.chapter_keywords or request.content_filter):
            filtered_chunks = []
            
            for chunk in relevant_chunks:
                chunk_text = chunk.get("text", "").lower()
                
                # Filter by chapter keywords
                if request.chapter_keywords:
                    if any(keyword.lower() in chunk_text for keyword in request.chapter_keywords):
                        filtered_chunks.append(chunk)
                        continue
                
                # Filter by content filter
                if request.content_filter:
                    if request.content_filter.lower() in chunk_text:
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
                "template": request.template,
                "institution_name": request.institution_name,
                "course_name": request.course_name,
                "exam_date": request.exam_date,
                "duration": request.duration,
                "instructions": request.instructions,
                "student_fields": request.student_fields or ["name", "roll_number"],
                "question_type_counts": request.question_type_counts,
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
                "ocr_text": ocr_text
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
        if paper["owner_id"] != current_teacher["id"]:
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
        if paper["owner_id"] != current_teacher["id"]:
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
    Supports 4 PDF templates: classic, university, school, minimalist.
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

        # Extract metadata from configuration
        _cfg = paper.get("configuration") or {}
        if isinstance(_cfg, str):
            import json as _j2
            try:
                _cfg = _j2.loads(_cfg)
            except Exception:
                _cfg = {}
        if not isinstance(_cfg, dict):
            _cfg = {}

        paper_meta = {
            "institution_name": _cfg.get("institution_name", "EduMaster Institute"),
            "course_name": _cfg.get("course_name", ""),
            "exam_date": _cfg.get("exam_date", "________________"),
            "duration": _cfg.get("duration", "3 Hours"),
            "instructions": _cfg.get("instructions", ""),
            "student_fields": _cfg.get("student_fields", ["name", "roll_number"]),
        }
        # Template: query param overrides stored config
        resolved_template = template_name or _cfg.get("template", "classic")

        # Generate printable content (text fallback)
        printable_content = _generate_printable_content(paper)

        if format.lower() == "pdf":
            try:
                # Get extra context
                subject_info = await db.get_subject(str(paper['subject_id']))
                class_info = None
                if subject_info and subject_info.get('class_id'):
                    class_info = await db.get_class(str(subject_info['class_id']))
                teacher_info = await db.get_teacher(str(paper['owner_id']))
                teacher_name = teacher_info.get('name', 'Unknown Teacher') if teacher_info else 'Unknown Teacher'
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
        
        # Validate paper has questions and answer key
        questions = paper.get('questions', [])
        if isinstance(questions, str):
            import json
            try:
                questions = json.loads(questions)
            except Exception:
                questions = []

        answer_key = paper.get('answer_key', {})


        if isinstance(answer_key, str):


            try:


                import json


                answer_key = json.loads(answer_key)


            except Exception: answer_key = {}
        if isinstance(answer_key, str):
            import json
            try:
                answer_key = json.loads(answer_key)
            except Exception:
                answer_key = {}
        
        if not questions:
            logger.error(f"Paper {paper_id} has no questions")
            raise HTTPException(status_code=400, detail="Paper has no questions")
        
        if not answer_key:
            logger.error(f"Paper {paper_id} has no answer key")
            raise HTTPException(status_code=400, detail="Paper has no answer key")
        
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
                
                teacher_name = "Unknown Teacher"
                try:
                    teacher_info = await db.get_teacher(str(paper['owner_id']))
                    if teacher_info:
                        teacher_name = teacher_info.get('name', 'Unknown Teacher')
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
                story.append(Paragraph(f"Paper: {paper.get('title', 'Untitled Paper')}", styles['Normal']))
                story.append(Paragraph(f"Subject: {subject_info.get('name', 'Unknown Subject') if subject_info else 'Unknown Subject'}", styles['Normal']))
                story.append(Paragraph(f"Teacher: {teacher_name}", styles['Normal']))
                story.append(Paragraph(f"Total Marks: {paper.get('total_marks', 0)}", styles['Normal']))
                story.append(Spacer(1, 20))
                
                # Organize questions by type
                questions = paper.get('questions', [])

                if isinstance(questions, str):

                    try:

                        import json

                        questions = json.loads(questions)

                    except Exception: questions = []
                answer_key = paper.get('answer_key', {})

                if isinstance(answer_key, str):

                    try:

                        import json

                        answer_key = json.loads(answer_key)

                    except Exception: answer_key = {}
                
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
                    <p>Paper: {paper.get('title', 'Untitled Paper')}</p>
                    <p>Total Marks: {paper.get('total_marks', 0)}</p>
                </div>
            """
            
            questions = paper.get('questions', [])

            
            if isinstance(questions, str):

            
                try:

            
                    import json

            
                    questions = json.loads(questions)

            
                except Exception: questions = []
            answer_key = paper.get('answer_key', {})

            if isinstance(answer_key, str):

                try:

                    import json

                    answer_key = json.loads(answer_key)

                except Exception: answer_key = {}
            
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


def _generate_printable_content(paper: dict) -> str:
    """Generate printable text content for the paper"""
    content = []
    
    # Header
    content.append("=" * 80)
    content.append(f"QUESTION PAPER: {paper['title']}")
    content.append("=" * 80)
    
    if paper.get('description'):
        content.append(f"\nDescription: {paper['description']}")
    
    content.append(f"Total Marks: {paper.get('total_marks', 0)}")
    content.append(f"Created: {paper.get('created_at', 'Unknown')}")
    content.append("\n" + "=" * 80)
    
    # Questions
    questions = paper.get('questions', [])
    if isinstance(questions, str):
        import json
        try:
            questions = json.loads(questions)
        except Exception:
            questions = []

    answer_key = paper.get('answer_key', {})


    if isinstance(answer_key, str):


        try:


            import json


            answer_key = json.loads(answer_key)


        except Exception: answer_key = {}
    if isinstance(answer_key, str):
        import json
        try:
            answer_key = json.loads(answer_key)
        except Exception:
            answer_key = {}
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

    
    if isinstance(answer_key, str):

    
        try:

    
            import json

    
            answer_key = json.loads(answer_key)

    
        except Exception: answer_key = {}
    for i, question in enumerate(questions, 1):
        question_id = f"q{i}"
        answer = answer_key.get(question_id, "No answer provided")
        content.append(f"Q{i}. {answer}")
    
    return "\n".join(content)


def _generate_html_paper(paper: dict, printable_content: str) -> str:
    """Generate HTML format for the paper"""
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
            <h1>{paper['title']}</h1>
            <p>Total Marks: {paper.get('total_marks', 0)}</p>
            <p>Created: {paper.get('created_at', 'Unknown')}</p>
        </div>
        
        <div class="questions">
    """
    
    questions = paper.get('questions', [])

    
    if isinstance(questions, str):

    
        try:

    
            import json

    
            questions = json.loads(questions)

    
        except Exception: questions = []
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

    
    if isinstance(answer_key, str):

    
        try:

    
            import json

    
            answer_key = json.loads(answer_key)

    
        except Exception: answer_key = {}
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
    if isinstance(questions, str):
        try:
            import json
            questions = json.loads(questions)
        except:
            questions = []
    
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
            document_info.append({
                "id": doc["id"],
                "filename": doc["filename"],
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
        meta_fields = {"template", "institution_name", "course_name", "exam_date",
                       "duration", "instructions", "student_fields"}

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
        "template": cfg.get("template", "classic"),
        "institution_name": cfg.get("institution_name"),
        "course_name": cfg.get("course_name"),
        "exam_date": cfg.get("exam_date"),
        "duration": cfg.get("duration"),
        "instructions": cfg.get("instructions"),
        "student_fields": cfg.get("student_fields", ["name", "roll_number"]),
        "teacher_id": str(paper["owner_id"]) if paper.get("owner_id") else None,
        "created_at": str(paper["created_at"]),
    }


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
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, cm
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
    from reportlab.lib import colors
    import io
    import json

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()

    questions = paper.get("questions", [])
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
        except Exception:
            questions = []
    title = paper.get("title", "Examination Paper")
    total_marks = paper.get("total_marks", 0)
    institution = meta.get("institution_name") or "EduMaster Institute"
    course = meta.get("course_name") or subject_name
    exam_date = meta.get("exam_date") or "________________"
    duration = meta.get("duration") or "3 Hours"
    custom_instructions = meta.get("instructions") or ""
    student_fields = meta.get("student_fields") or ["name", "roll_number"]

    # Shared question section builder
    def _add_questions(story, section_qs, section_title, blank_space, q_style, opt_style, start_num):
        if not section_qs:
            return start_num
        story.append(Paragraph(section_title, styles["_Section"]))
        story.append(Spacer(1, 8))
        n = start_num
        for q in section_qs:
            marks = q.get("marks") or q.get("max_score") or 5
            q_text = f"{n}. {q.get('question_text', '')} <font size='9' color='grey'>({marks} marks)</font>"
            story.append(Paragraph(q_text, q_style))
            if q.get("question_type") == "mcq" and q.get("options"):
                for j, opt in enumerate(q["options"]):
                    clean = opt.strip()
                    for prefix in ("A)", "B)", "C)", "D)", "a)", "b)", "c)", "d)"):
                        if clean.startswith(prefix):
                            clean = clean[2:].strip()
                    story.append(Paragraph(f"{chr(65+j)}) {clean}", opt_style))
            else:
                story.append(Spacer(1, blank_space))
            story.append(Spacer(1, 6))
            n += 1
        return n

    # ── Student detail box ──────────────────────────────────────────────────
    FIELD_LABELS = {
        "name": "Student Name",
        "roll_number": "Roll No.",
        "class": "Class",
        "section": "Section",
        "signature": "Signature",
        "father_name": "Father's Name",
    }

    def _student_box(story, fields):
        rows = [
            [FIELD_LABELS.get(f, f.replace("_", " ").title()) + ":", "________________________"]
            for f in fields
        ]
        if not rows:
            return
        t = Table(rows, colWidths=[1.6 * inch, 3.2 * inch])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))

    # ── Template dispatchers ─────────────────────────────────────────────────

    if template == "university":
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=50, leftMargin=50,
                                topMargin=45, bottomMargin=45)
        story = []
        # Top border rule
        story.append(HRFlowable(width="100%", thickness=2.5, color=colors.HexColor("#1a237e")))
        story.append(Spacer(1, 6))
        # Two-column header: logo placeholder | institution
        hdr = Table(
            [["[LOGO]", institution.upper()]],
            colWidths=[1.2 * inch, 5.3 * inch],
        )
        hdr.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, 0), "Helvetica"),
            ("FONTSIZE", (0, 0), (0, 0), 9),
            ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (1, 0), (1, 0), 17),
            ("ALIGN", (1, 0), (1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TEXTCOLOR", (1, 0), (1, 0), colors.HexColor("#1a237e")),
        ]))
        story.append(hdr)
        story.append(Spacer(1, 4))
        story.append(Paragraph("Examination Department", ParagraphStyle(
            "SubHdr", parent=styles["Normal"], fontSize=10, alignment=TA_CENTER,
            textColor=colors.HexColor("#3949AB"))))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a237e")))
        story.append(Spacer(1, 10))
        # Info table
        info = Table([
            [f"Course: {course}", f"Date: {exam_date}"],
            [f"Subject: {subject_name}", f"Duration: {duration}"],
            [f"Total Marks: {total_marks}", f"Teacher: {teacher_name}"],
        ], colWidths=[3.5 * inch, 3 * inch])
        info.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(info)
        story.append(Spacer(1, 8))
        story.append(Paragraph(title, ParagraphStyle(
            "PTitle", parent=styles["Heading2"], fontSize=13, alignment=TA_CENTER)))
        story.append(Spacer(1, 6))
        _student_box(story, student_fields)
        if custom_instructions:
            story.append(Paragraph("<b>Instructions:</b> " + custom_instructions,
                                   ParagraphStyle("Ins", parent=styles["Normal"], fontSize=9)))
            story.append(Spacer(1, 8))
        styles.add(ParagraphStyle("_Section", parent=styles["Heading3"], fontSize=11,
                                   spaceBefore=12, spaceAfter=6,
                                   textColor=colors.HexColor("#1a237e"), fontName="Helvetica-Bold"))
        q_style = ParagraphStyle("QStyle", parent=styles["Normal"], fontSize=10, spaceAfter=4)
        opt_style = ParagraphStyle("OptStyle", parent=styles["Normal"], fontSize=9, leftIndent=22, spaceAfter=3)

    elif template == "school":
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=45, leftMargin=45,
                                topMargin=45, bottomMargin=45)
        story = []
        # Colorful header band
        band = Table([[institution.upper()]], colWidths=[6.7 * inch])
        band.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FF6F00")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 16),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(band)
        story.append(Spacer(1, 8))
        story.append(Paragraph(title, ParagraphStyle(
            "SchTitle", parent=styles["Normal"], fontSize=14,
            fontName="Helvetica-Bold", alignment=TA_CENTER)))
        story.append(Spacer(1, 6))
        info = Table([
            [f"Subject: {subject_name or course}", f"Class: {class_name}", f"Total Marks: {total_marks}"],
            [f"Date: {exam_date}", f"Duration: {duration}", f"Teacher: {teacher_name}"],
        ], colWidths=[2.2 * inch, 2.2 * inch, 2.3 * inch])
        info.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#FF6F00")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#FFB74D")),
        ]))
        story.append(info)
        story.append(Spacer(1, 10))
        _student_box(story, student_fields)
        if custom_instructions:
            story.append(Paragraph(f"<b>Instructions:</b> {custom_instructions}",
                                   ParagraphStyle("Ins", parent=styles["Normal"], fontSize=9)))
            story.append(Spacer(1, 8))
        styles.add(ParagraphStyle("_Section", parent=styles["Normal"], fontSize=11,
                                   fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6,
                                   textColor=colors.HexColor("#E65100"), backColor=colors.HexColor("#FFF3E0")))
        q_style = ParagraphStyle("QStyle", parent=styles["Normal"], fontSize=10, spaceAfter=5, leading=14)
        opt_style = ParagraphStyle("OptStyle", parent=styles["Normal"], fontSize=9, leftIndent=22, spaceAfter=3)

    elif template == "minimalist":
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=60, leftMargin=60,
                                topMargin=55, bottomMargin=55)
        story = []
        story.append(Paragraph(institution, ParagraphStyle(
            "MIns", parent=styles["Normal"], fontSize=10,
            textColor=colors.grey, alignment=TA_LEFT)))
        story.append(Spacer(1, 4))
        story.append(Paragraph(title, ParagraphStyle(
            "MTitle", parent=styles["Normal"], fontSize=16,
            fontName="Helvetica-Bold", spaceAfter=4)))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 6))
        info = Table([
            [f"{subject_name or course}", f"{exam_date}", f"{total_marks} marks", f"{duration}"]
        ], colWidths=[1.8 * inch, 1.6 * inch, 1.5 * inch, 1.5 * inch])
        info.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.grey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(info)
        story.append(Spacer(1, 10))
        _student_box(story, student_fields)
        if custom_instructions:
            story.append(Paragraph(custom_instructions,
                                   ParagraphStyle("Ins", parent=styles["Normal"], fontSize=8,
                                                  textColor=colors.grey)))
            story.append(Spacer(1, 8))
        styles.add(ParagraphStyle("_Section", parent=styles["Normal"], fontSize=10,
                                   fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=5,
                                   textColor=colors.black))
        q_style = ParagraphStyle("QStyle", parent=styles["Normal"], fontSize=10, spaceAfter=4, leading=13)
        opt_style = ParagraphStyle("OptStyle", parent=styles["Normal"], fontSize=9, leftIndent=18, spaceAfter=2)

    else:  # classic (default)
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=50, leftMargin=50,
                                topMargin=50, bottomMargin=50)
        story = []
        story.append(Paragraph(institution.upper(), ParagraphStyle(
            "CIns", parent=styles["Heading1"], fontSize=16, spaceAfter=4, alignment=TA_CENTER)))
        story.append(Paragraph("EXAMINATION DEPARTMENT", ParagraphStyle(
            "CDept", parent=styles["Normal"], fontSize=10, alignment=TA_CENTER,
            textColor=colors.grey)))
        story.append(Spacer(1, 16))
        paper_info = [
            ["Subject:", subject_name or course],
            ["Class:", class_name],
            ["Teacher:", teacher_name],
            ["Total Marks:", str(total_marks)],
            ["Time:", duration],
            ["Date:", exam_date],
        ]
        it = Table(paper_info, colWidths=[1.5 * inch, 3 * inch])
        it.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(it)
        story.append(Spacer(1, 16))
        story.append(Paragraph(title, ParagraphStyle(
            "PTitle", parent=styles["Heading2"], fontSize=14, alignment=TA_CENTER)))
        story.append(Spacer(1, 10))
        _student_box(story, student_fields)
        instr_lines = (custom_instructions or "Answer ALL questions. Marks are indicated against each question.").split("\n")
        story.append(Paragraph("<b>Instructions:</b>", ParagraphStyle(
            "InsHdr", parent=styles["Normal"], fontSize=10)))
        for line in instr_lines:
            if line.strip():
                story.append(Paragraph(line.strip(), styles["Normal"]))
        story.append(Spacer(1, 16))
        styles.add(ParagraphStyle("_Section", parent=styles["Heading3"], fontSize=12,
                                   spaceBefore=14, spaceAfter=8, textColor=colors.black))
        q_style = ParagraphStyle("QStyle", parent=styles["Normal"], fontSize=11, spaceAfter=8)
        opt_style = ParagraphStyle("OptStyle", parent=styles["Normal"], fontSize=10, leftIndent=25, spaceAfter=4)

    # ── Common question sections ────────────────────────────────────────────
    mcq_qs = [q for q in questions if q.get("question_type") == "mcq"]
    short_qs = [q for q in questions if q.get("question_type") == "short_answer"]
    long_qs = [q for q in questions if q.get("question_type") in ("essay", "long_answer")]
    tf_qs = [q for q in questions if q.get("question_type") == "true_false"]
    fill_qs = [q for q in questions if q.get("question_type") in ("fill_blank", "fill_in_blank")]
    other_qs = [q for q in questions if q.get("question_type") not in
                ("mcq", "short_answer", "essay", "long_answer", "true_false", "fill_blank", "fill_in_blank")]

    n = 1
    n = _add_questions(story, mcq_qs, "SECTION A: MULTIPLE CHOICE QUESTIONS", 0, q_style, opt_style, n)
    n = _add_questions(story, short_qs, "SECTION B: SHORT ANSWER QUESTIONS", 38, q_style, opt_style, n)
    n = _add_questions(story, long_qs, "SECTION C: LONG ANSWER / ESSAY QUESTIONS", 65, q_style, opt_style, n)
    n = _add_questions(story, tf_qs, "SECTION D: TRUE / FALSE", 20, q_style, opt_style, n)
    n = _add_questions(story, fill_qs, "SECTION E: FILL IN THE BLANKS", 28, q_style, opt_style, n)
    n = _add_questions(story, other_qs, "SECTION F: OTHER QUESTIONS", 38, q_style, opt_style, n)

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
