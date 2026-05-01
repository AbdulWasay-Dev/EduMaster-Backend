"""
Document management API endpoints
"""
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel, Field

from utils.security import get_current_teacher, require_teacher
from services.database import get_database
from services.file_storage import get_file_storage
from services.text_extractor import get_text_extractor
from services.chunker import get_chunker
from services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)
router = APIRouter()


# Pydantic models
class DocumentResponse(BaseModel):
    """Response model for document operations"""
    id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    processing_status: str
    subject_id: str
    created_at: str


class DocumentListResponse(BaseModel):
    """Response model for document listing"""
    documents: List[DocumentResponse]
    total: int


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    subject_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_teacher())
):
    """
    Upload a document for processing
    """
    try:
        logger.info(f"Document upload from user {current_user['id']}: {file.filename}")
        
        # Validate file
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="No file provided"
            )
        
        # Check file type
        file_extension = file.filename.split('.')[-1].lower()
        if file_extension not in ['pdf', 'pptx', 'docx', 'png', 'jpg', 'jpeg']:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_extension}"
            )
        
        # Check file size
        file_content = await file.read()
        if len(file_content) > 50 * 1024 * 1024:  # 50MB limit
            raise HTTPException(
                status_code=400,
                detail="File too large. Maximum size is 50MB"
            )
        
        # Get database service
        db = await get_database()
        
        # Verify user has access to the subject
        subjects = await db.get_subjects(current_user["id"])
        subject_ids = [str(s["id"]) for s in subjects]
        
        if subject_id not in subject_ids:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this subject"
            )
        
        # Generate unique filename
        file_id = str(uuid.uuid4())
        file_extension = file.filename.split('.')[-1].lower()
        storage_filename = f"{file_id}.{file_extension}"
        
        # Get file storage service
        file_storage = get_file_storage()
        
        # Upload to local storage
        storage_path = f"{current_user['id']}/{storage_filename}"
        public_url = await file_storage.upload_file("documents", storage_path, file_content)
        
        if not public_url:
            raise HTTPException(
                status_code=500,
                detail="Failed to upload file to storage"
            )
        
        # Create document record
        document_data = {
            "id": file_id,
            "subject_id": subject_id,
            "owner_id": current_user["id"],
            "filename": storage_filename,
            "original_filename": file.filename,
            "storage_path": storage_path,
            "file_type": file_extension,
            "file_size": len(file_content),
            "processing_status": "pending"
        }
        
        document = await db.create_document(document_data)
        if not document:
            raise HTTPException(
                status_code=500,
                detail="Failed to create document record"
            )
        
        # Process synchronously: extract text -> chunk -> embed -> store chunks
        await process_document_async(str(document["id"]))
        
        return DocumentResponse(
            id=str(document["id"]),
            filename=document["filename"],
            original_filename=document["original_filename"],
            file_type=document["file_type"],
            file_size=document["file_size"],
            processing_status=document["processing_status"],
            subject_id=str(document["subject_id"]),
            created_at=str(document["created_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during document upload"
        )


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    subject_id: Optional[str] = None,
    current_user: dict = Depends(require_teacher())
):
    """
    List documents for a subject (subject_id optional — if omitted returns all)
    """
    try:
        db = await get_database()

        if subject_id:
            # Verify user has access to the subject
            subjects = await db.get_subjects(current_user["id"])
            subject_ids = [str(s["id"]) for s in subjects]
            
            if subject_id not in subject_ids:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied to this subject"
                )
            documents = await db.get_documents(subject_id)
        else:
            # Return all documents across all teacher's subjects
            subjects = await db.get_subjects(current_user["id"])
            documents = []
            for s in subjects:
                docs = await db.get_documents(str(s["id"]))
                documents.extend(docs)
        
        document_responses = [
            DocumentResponse(
                id=str(doc["id"]),
                filename=doc["filename"],
                original_filename=doc["original_filename"],
                file_type=doc["file_type"],
                file_size=doc.get("file_size", 0),
                processing_status=doc.get("processing_status", "pending"),
                subject_id=str(doc["subject_id"]),
                created_at=str(doc["created_at"])
            )
            for doc in documents
        ]
        
        return DocumentListResponse(
            documents=document_responses,
            total=len(document_responses)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    current_user: dict = Depends(require_teacher())
):
    """
    Get document details
    """
    try:
        db = await get_database()
        
        document = await db.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Authorization: ensure owner matches
        if str(document["owner_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        return DocumentResponse(
            id=str(document["id"]),
            filename=document["filename"],
            original_filename=document["original_filename"],
            file_type=document["file_type"],
            file_size=document.get("file_size", 0),
            processing_status=document.get("processing_status", "pending"),
            subject_id=str(document["subject_id"]),
            created_at=str(document["created_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: dict = Depends(require_teacher())
):
    """
    Delete a document
    """
    try:
        db = await get_database()
        document = await db.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        if str(document["owner_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        # Delete file from storage
        file_storage = get_file_storage()
        await file_storage.delete_file("documents", document["storage_path"])

        ok = await db.delete_document(document_id)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to delete document")
        return {"message": "Document deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/{document_id}/status")
async def get_document_status(
    document_id: str,
    current_user: dict = Depends(require_teacher())
):
    """
    Get document processing status
    """
    try:
        db = await get_database()
        document = await db.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        if str(document["owner_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        return {"document_id": document_id, "status": document.get("processing_status", "pending")}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document status: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/{document_id}/chunks")
async def get_document_chunks(
    document_id: str,
    current_user: dict = Depends(require_teacher())
):
    """
    Get text chunks for a document (for preview)
    """
    try:
        db = await get_database()
        document = await db.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        if str(document["owner_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        chunks = await db.get_document_chunks(document_id)
        return {
            "chunks": [
                {
                    "id": str(c.get("id", "")),
                    "chunk_index": c.get("chunk_index", 0),
                    "content": c.get("text", ""),
                    "char_count": len(c.get("text", "")),
                    "metadata": c.get("metadata"),
                }
                for c in chunks
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document chunks: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def process_document_async(document_id: str):
    """
    Process document asynchronously (extract text, chunk, embed)
    """
    db = None
    try:
        logger.info(f"Processing document {document_id}")
        
        # Get services
        db = await get_database()
        file_storage = get_file_storage()
        text_extractor = get_text_extractor()
        chunker = get_chunker()
        embedding_service = get_embedding_service()
        
        # Get document
        document = await db.get_document(document_id)
        if not document:
            logger.error("Document not found during processing")
            return
        
        # Update status to processing
        await db.update_document_status(document_id, "processing")
        
        # Download file content to extract text
        file_bytes = await file_storage.download_file("documents", document["storage_path"])
        if not file_bytes:
            await db.update_document_status(document_id, "failed")
            return
        
        # Extract text for supported types (skip OCR per request)
        supported_text_types = {"pdf", "pptx", "docx"}
        text = await text_extractor.extract_text(file_bytes, document["file_type"]) if document["file_type"] in supported_text_types else None
        if not text:
            await db.update_document_status(document_id, "failed")
            return
        
        # Chunk text
        chunks = await chunker.chunk_text_semantic(text)
        if not chunks:
            await db.update_document_status(document_id, "failed")
            return
        
        # Generate embeddings
        embeddings = await embedding_service.generate_embeddings_batch([c["text"] for c in chunks])
        
        # Store chunks with embeddings
        chunks_data = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            if not embedding:
                continue
            chunks_data.append({
                "document_id": document_id,
                "subject_id": str(document["subject_id"]),
                "owner_id": str(document["owner_id"]),
                "chunk_index": i,
                "text": chunk["text"],
                "embedding": embedding
            })
        if chunks_data:
            await db.create_document_chunks(chunks_data)
        
        # Update status to completed
        await db.update_document_status(document_id, "completed")
        
        logger.info(f"Document {document_id} processed successfully")
        
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        # Update status to failed
        if db:
            await db.update_document_status(document_id, "failed")
