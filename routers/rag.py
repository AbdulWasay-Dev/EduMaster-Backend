"""
RAG (Retrieval Augmented Generation) API endpoints
"""
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from utils.security import get_current_teacher, require_teacher_or_admin, require_teacher
from services.database import get_database
from services.embedding_service import get_embedding_service
from services.llm_service import get_llm_service

logger = logging.getLogger(__name__)
router = APIRouter()


# Pydantic models
class RAGQueryRequest(BaseModel):
    """Request model for RAG queries"""
    subject_id: Optional[str] = Field(None, description="Subject ID to search in")
    document_ids: Optional[List[str]] = Field(None, description="Specific document IDs to search")
    # Accept both 'question' (backend) and 'query' (frontend) field names
    question: Optional[str] = Field(None, min_length=1, max_length=1000, description="Question to ask")
    query: Optional[str] = Field(None, min_length=1, max_length=1000, description="Query (alias for question)")
    question_type: str = Field(default="general", description="Type of question")
    difficulty: str = Field(default="medium", description="Difficulty level")
    include_sources: bool = Field(default=True, description="Include source citations")
    top_k: Optional[int] = Field(None, description="Number of results to retrieve")

    @property
    def effective_question(self) -> str:
        return self.question or self.query or ""


class RAGSource(BaseModel):
    """Source reference model"""
    document_id: str = ""
    document_name: str = ""
    document_title: Optional[str] = None
    chunk_text: str = ""
    relevance_score: float = 0.0
    page_number: Optional[int] = None


class RAGQueryResponse(BaseModel):
    """Response model for RAG queries"""
    answer: str
    sources: List[RAGSource] = []
    query: str = ""
    confidence: float = 0.0
    subject_id: str = ""


class QuestionGenerationRequest(BaseModel):
    """Request model for question generation"""
    subject_id: str = Field(..., description="Subject ID")
    document_ids: Optional[List[str]] = Field(None, description="Specific document IDs")
    question_count: int = Field(default=5, ge=1, le=20, description="Number of questions to generate")
    question_types: List[str] = Field(default=["mcq", "short_answer"], description="Types of questions")
    difficulty_level: str = Field(default="medium", description="Difficulty level")
    title: Optional[str] = Field(default=None, description="Title for the generated paper")


class QuestionGenerationResponse(BaseModel):
    """Response model for question generation"""
    questions: List[dict]
    title: str
    subject_id: str
    total_questions: int


@router.post("/query", response_model=RAGQueryResponse)
async def query_rag(
    request: RAGQueryRequest,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Query the RAG system with a question
    """
    try:
        effective_question = request.effective_question
        if not effective_question:
            raise HTTPException(status_code=422, detail="Either 'question' or 'query' field is required")

        logger.info(f"RAG query from teacher {current_teacher['id']}: {effective_question[:50]}...")
        
        # Get services
        db = await get_database()
        embedding_service = get_embedding_service()
        llm_service = get_llm_service()
        
        # Determine subject scope
        subjects = await db.get_subjects(current_teacher["id"])
        subject_ids = [str(s["id"]) for s in subjects]

        if request.subject_id:
            if request.subject_id not in subject_ids:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied to this subject"
                )
            search_subject_id = request.subject_id
        else:
            # No subject_id provided — use the first available subject, or skip subject filter
            search_subject_id = subject_ids[0] if subject_ids else None
        
        # Generate query embedding
        query_embedding = await embedding_service.generate_query_embedding(effective_question)
        if not query_embedding:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate query embedding"
            )
        
        # Search for similar chunks
        similar_chunks = await db.search_similar_chunks(
            embedding=query_embedding,
            subject_id=search_subject_id,
            limit=request.top_k or 10,
            match_threshold=0.55
        )
        
        if not similar_chunks:
            return RAGQueryResponse(
                answer="I couldn't find relevant information in the provided documents to answer your question. Please make sure the documents contain information about this topic.",
                sources=[],
                confidence=0.0,
                query=effective_question,
                subject_id=search_subject_id or ""
            )
        
        # Extract context from chunks
        # Accept both 'text' or 'chunk_text' keys depending on SQL function
        context = [chunk.get("text") or chunk.get("chunk_text", "") for chunk in similar_chunks if (chunk.get("text") or chunk.get("chunk_text"))]
        
        # Generate answer using LLM
        answer_result = await llm_service.generate_answer(
            question=effective_question,
            context=context,
            question_type=request.question_type
        )
        
        if not answer_result:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate answer"
            )
        
        # Prepare sources if requested. Use document names from the DB, not storage IDs.
        rag_sources: List[RAGSource] = []
        if request.include_sources:
            document_names: Dict[str, str] = {}
            seen_sources = set()
            max_sources = min(request.top_k or 5, 5)

            for chunk in similar_chunks:
                document_id = str(chunk.get("document_id") or "")
                if document_id and document_id not in document_names:
                    document = await db.get_document(document_id)
                    document_names[document_id] = (
                        (document or {}).get("original_filename")
                        or (document or {}).get("title")
                        or (document or {}).get("filename")
                        or ""
                    )

                source_key = (
                    document_id,
                    str(chunk.get("id") or chunk.get("chunk_index") or chunk.get("text", "")[:80]),
                )
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)

                rag_sources.append(RAGSource(
                    document_id=document_id,
                    document_name=document_names.get(document_id, ""),
                    document_title=document_names.get(document_id, ""),
                    chunk_text=chunk.get("text") or chunk.get("chunk_text", ""),
                    relevance_score=float(chunk.get("relevance_score", chunk.get("similarity", 0.0))),
                    page_number=(chunk.get("metadata") or {}).get("page_number") if isinstance(chunk.get("metadata"), dict) else None,
                ))

                if len(rag_sources) >= max_sources:
                    break

            if not rag_sources:
                raw_sources = answer_result.get("sources", [])
                for src in raw_sources:
                    if isinstance(src, dict):
                        rag_sources.append(RAGSource(
                            document_id=str(src.get("document_id", "")),
                            document_name=src.get("document_name", ""),
                            document_title=src.get("document_title"),
                            chunk_text=src.get("chunk_text", src.get("text", "")),
                            relevance_score=float(src.get("relevance_score", src.get("similarity", 0.0))),
                        ))
                    elif isinstance(src, str):
                        rag_sources.append(RAGSource(chunk_text=src))
        
        return RAGQueryResponse(
            answer=answer_result["answer"],
            sources=rag_sources,
            confidence=answer_result.get("confidence", 0.0),
            query=effective_question,
            subject_id=search_subject_id or ""
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in RAG query: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during RAG query"
        )


@router.post("/generate-questions", response_model=QuestionGenerationResponse)
async def generate_questions(
    request: QuestionGenerationRequest,
    current_teacher: dict = Depends(require_teacher_or_admin())
):
    """
    Generate questions from documents using RAG system and AI
    """
    try:
        logger.info(f"Question generation request from teacher {current_teacher['id']}")
        
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
                detail="No documents found for this subject. Please upload documents first."
            )
        
        # Filter by specific document IDs if provided
        if request.document_ids:
            documents = [doc for doc in documents if str(doc["id"]) in request.document_ids]
        
        if not documents:
            raise HTTPException(
                status_code=400,
                detail="No matching documents found"
            )
        
        # Use RAG system to retrieve relevant content from documents
        # Generate a query to get comprehensive content for question generation
        content_query = f"Generate comprehensive questions about {request.subject_id} covering all important topics and concepts"
        
        # Get query embedding
        query_embedding = await embedding_service.generate_query_embedding(content_query)
        if not query_embedding:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate query embedding"
            )
        
        # Search for relevant chunks using RAG
        relevant_chunks = await db.search_similar_chunks(
            embedding=query_embedding,
            subject_id=request.subject_id,
            limit=20  # Get more chunks for comprehensive question generation
        )
        
        if not relevant_chunks:
            raise HTTPException(
                status_code=400,
                detail="No relevant content found in documents. Please ensure documents are properly processed."
            )
        
        # Organize content by topics/sections for better question generation
        organized_content = await organize_content_for_questions(relevant_chunks, request.question_count)
        
        # Generate questions using the organized content
        questions = await llm_service.generate_questions_from_rag_content(
            organized_content=organized_content,
            question_count=request.question_count,
            question_types=request.question_types,
            difficulty_level=request.difficulty_level,
            subject_id=request.subject_id
        )
        
        if not questions:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate questions from document content"
            )
        
        # Add source information to questions
        for question in questions:
            question["source_documents"] = [str(doc["id"]) for doc in documents]
            question["content_sources"] = [str(chunk["document_id"]) for chunk in relevant_chunks[:5]]
        
        return QuestionGenerationResponse(
            questions=questions,
            title=request.title or f"Questions for {request.subject_id}",
            subject_id=request.subject_id,
            total_questions=len(questions)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating questions: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during question generation"
        )


@router.get("/suggestions/{subject_id}")
async def get_question_suggestions(
    subject_id: str,
    current_user: dict = Depends(require_teacher())
):
    """
    Get suggested questions for a subject
    """
    try:
        # Verify user has access to the subject
        db = await get_database()
        subjects = await db.get_subjects(current_user["id"])
        subject_ids = [str(s["id"]) for s in subjects]
        
        if subject_id not in subject_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this subject"
            )
        
        # Get some sample questions based on document content
        # This is a simplified implementation
        suggestions = [
            "What are the main concepts covered in this topic?",
            "Can you explain the key principles?",
            "What are the practical applications?",
            "How do these concepts relate to each other?",
            "What are the important examples or case studies?"
        ]
        
        return {
            "subject_id": subject_id,
            "suggestions": suggestions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting question suggestions: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.post("/summarize")
async def summarize_content(
    subject_id: str,
    document_ids: Optional[List[str]] = None,
    current_user: dict = Depends(require_teacher())
):
    """
    Summarize document content
    """
    try:
        # This would be implemented similar to question generation
        # but focused on summarization
        return {
            "summary": "Content summarization feature coming soon",
            "subject_id": subject_id
        }
        
    except Exception as e:
        logger.error(f"Error summarizing content: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


async def organize_content_for_questions(chunks: List[Dict[str, Any]], question_count: int) -> Dict[str, Any]:
    """
    Organize RAG-retrieved chunks into structured content for question generation
    """
    try:
        # Group chunks by similarity and topics
        organized_content = {
            "main_content": [],
            "key_concepts": [],
            "examples": [],
            "definitions": []
        }
        
        # Simple organization - in practice, you'd want more sophisticated topic modeling
        for chunk in chunks:
            # Handle different possible field names for chunk text
            text = chunk.get("text", "") or chunk.get("chunk_text", "") or chunk.get("content", "")
            
            if not text or len(text.strip()) < 10:  # Skip very short chunks
                continue
            
            # Categorize content based on keywords and structure
            text_lower = text.lower()
            if any(keyword in text_lower for keyword in ["definition", "define", "is defined as", "means", "refers to"]):
                organized_content["definitions"].append(text)
            elif any(keyword in text_lower for keyword in ["example", "for instance", "such as", "e.g.", "including"]):
                organized_content["examples"].append(text)
            elif any(keyword in text_lower for keyword in ["concept", "principle", "theory", "fundamental", "basic"]):
                organized_content["key_concepts"].append(text)
            else:
                organized_content["main_content"].append(text)
        
        # If we don't have enough content in categories, put everything in main_content
        total_content = sum(len(content) for content in organized_content.values())
        if total_content < 3:  # Not enough content
            logger.warning("Not enough categorized content, putting all chunks in main_content")
            organized_content["main_content"] = []
            for chunk in chunks:
                text = chunk.get("text", "") or chunk.get("chunk_text", "") or chunk.get("content", "")
                if text and len(text.strip()) >= 10:
                    organized_content["main_content"].append(text)
        
        # Limit content to avoid token limits
        max_chunks_per_category = max(5, question_count // 4)
        for category in organized_content:
            organized_content[category] = organized_content[category][:max_chunks_per_category]
        
        logger.info(f"Organized content: {sum(len(content) for content in organized_content.values())} total chunks")
        return organized_content
        
    except Exception as e:
        logger.error(f"Error organizing content: {e}")
        # Fallback: return all chunks as main content
        fallback_content = []
        for chunk in chunks:
            text = chunk.get("text", "") or chunk.get("chunk_text", "") or chunk.get("content", "")
            if text and len(text.strip()) >= 10:
                fallback_content.append(text)
        return {"main_content": fallback_content[:10]}
