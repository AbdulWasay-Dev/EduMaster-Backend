"""
Document management API — upload, list, status, chunks, delete.
Documents are processed in a background asyncio task so the upload
endpoint returns immediately and the frontend can poll progress.
"""
import asyncio
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from utils.security import require_teacher
from services.database import get_database
from services.file_storage import get_file_storage
from services.text_extractor import get_text_extractor
from services.chunker import get_chunker
from services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)
router = APIRouter()

# ── File size limits ───────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024   # 200 MB
ALLOWED_TYPES = {'pdf', 'pptx', 'docx', 'png', 'jpg', 'jpeg'}

# ── Embedding sub-batch size for large documents ───────────────────────────────
EMBED_BATCH_SIZE = 64


# ── Models ─────────────────────────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    page_count: Optional[int] = None
    word_count: Optional[int] = None
    chunk_count: Optional[int] = None
    processing_status: str
    processing_progress: int = 0
    processing_stage: str = ""
    processing_error: Optional[str] = None
    subject_id: str
    created_at: str


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int


def _doc_to_response(doc: dict) -> DocumentResponse:
    display_filename = doc.get("original_filename") or doc.get("filename") or "Untitled document"
    return DocumentResponse(
        id=str(doc["id"]),
        filename=display_filename,
        original_filename=doc.get("original_filename") or display_filename,
        file_type=doc["file_type"],
        file_size=doc.get("file_size") or 0,
        page_count=doc.get("page_count"),
        word_count=doc.get("word_count"),
        chunk_count=doc.get("chunk_count"),
        processing_status=doc.get("processing_status", "pending"),
        processing_progress=doc.get("processing_progress") or 0,
        processing_stage=doc.get("processing_stage") or "",
        processing_error=doc.get("processing_error"),
        subject_id=str(doc["subject_id"]),
        created_at=str(doc["created_at"]),
    )


# ── Upload ─────────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    subject_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_teacher()),
):
    """
    Upload a document.
    Returns immediately with status='processing'; poll /{id}/status for progress.
    """
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

        file_content = await file.read()
        if len(file_content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large ({len(file_content)/1024/1024:.1f} MB). Maximum is {MAX_FILE_SIZE_BYTES//1024//1024} MB.",
            )

        db = await get_database()

        # Access check
        subjects = await db.get_subjects(current_user["id"])
        if subject_id not in [str(s["id"]) for s in subjects]:
            raise HTTPException(status_code=403, detail="Access denied to this subject")

        # Store file
        file_id = str(uuid.uuid4())
        storage_filename = f"{file_id}.{ext}"
        storage_path = f"{current_user['id']}/{storage_filename}"
        file_storage = get_file_storage()
        public_url = await file_storage.upload_file("documents", storage_path, file_content)
        if not public_url:
            raise HTTPException(status_code=500, detail="Failed to upload file to storage")

        # Create DB record
        doc_data = {
            "id": file_id,
            "subject_id": subject_id,
            "owner_id": current_user["id"],
            "filename": storage_filename,
            "original_filename": file.filename,
            "storage_path": storage_path,
            "file_type": ext,
            "file_size": len(file_content),
            "processing_status": "processing",
            "processing_progress": 0,
            "processing_stage": "queued",
        }
        document = await db.create_document(doc_data)
        if not document:
            raise HTTPException(status_code=500, detail="Failed to create document record")

        # Kick off processing in background
        background_tasks.add_task(
            process_document_async,
            document_id=str(document["id"]),
            file_content=file_content,
        )

        return _doc_to_response(document)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during upload")


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    subject_id: Optional[str] = None,
    current_user: dict = Depends(require_teacher()),
):
    """List documents. Omit subject_id to get all documents."""
    try:
        db = await get_database()
        if subject_id:
            subjects = await db.get_subjects(current_user["id"])
            if subject_id not in [str(s["id"]) for s in subjects]:
                raise HTTPException(status_code=403, detail="Access denied to this subject")
            documents = await db.get_documents(subject_id)
        else:
            subjects = await db.get_subjects(current_user["id"])
            documents = []
            for s in subjects:
                documents.extend(await db.get_documents(str(s["id"])))

        return DocumentListResponse(
            documents=[_doc_to_response(d) for d in documents],
            total=len(documents),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Get single ────────────────────────────────────────────────────────────────

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    current_user: dict = Depends(require_teacher()),
):
    try:
        db = await get_database()
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        if str(doc["owner_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        return _doc_to_response(doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document {document_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: dict = Depends(require_teacher()),
):
    try:
        db = await get_database()
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        if str(doc["owner_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        file_storage = get_file_storage()
        await file_storage.delete_file("documents", doc["storage_path"])
        ok = await db.delete_document(document_id)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to delete document")
        return {"message": "Document deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document {document_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Status (progress) ─────────────────────────────────────────────────────────

@router.get("/{document_id}/status")
async def get_document_status(
    document_id: str,
    current_user: dict = Depends(require_teacher()),
):
    """
    Rich progress endpoint — returns status, progress (0-100), stage, and stats.
    Frontend polls this every 2s during upload.
    """
    try:
        db = await get_database()
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        if str(doc["owner_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        return {
            "document_id": document_id,
            "status": doc.get("processing_status", "pending"),
            "progress": doc.get("processing_progress") or 0,
            "stage": doc.get("processing_stage") or "",
            "page_count": doc.get("page_count"),
            "word_count": doc.get("word_count"),
            "chunk_count": doc.get("chunk_count"),
            "error": doc.get("processing_error"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Chunks (preview) ─────────────────────────────────────────────────────────

@router.get("/{document_id}/chunks")
async def get_document_chunks(
    document_id: str,
    current_user: dict = Depends(require_teacher()),
):
    try:
        db = await get_database()
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        if str(doc["owner_id"]) != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        chunks = await db.get_document_chunks(document_id)
        return {
            "chunks": [
                {
                    "id": str(c.get("id", "")),
                    "chunk_index": c.get("chunk_index", 0),
                    "chunk_type": c.get("chunk_type", "paragraph"),
                    "content": c.get("text", ""),
                    "char_count": len(c.get("text", "")),
                    "metadata": c.get("metadata"),
                }
                for c in chunks
            ],
            "total": len(chunks),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chunks for {document_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Background processing ─────────────────────────────────────────────────────

async def process_document_async(document_id: str, file_content: bytes):
    """
    Full processing pipeline, emitting progress to the DB at every major step.

    Progress stages (% → label):
      2   queued
      5   downloading file
      15  extracting text
      35  chunking
      55  generating embeddings (0-100% internal per batch)
      90  storing chunks
      100 completed
    """
    db = None

    async def progress(pct: int, stage: str):
        """Persist progress to DB so the frontend can poll it."""
        if db:
            await db.update_document_progress(
                document_id, progress=pct, stage=stage
            )

    try:
        db = await get_database()
        document = await db.get_document(document_id)
        if not document:
            logger.error(f"process_document_async: document {document_id} not found")
            return

        logger.info(f"Starting processing for document {document_id} ({document['original_filename']})")

        await db.update_document_progress(
            document_id,
            status="processing",
            progress=2,
            stage="starting",
        )

        # ── 1. Download file content (if not passed directly) ─────────────
        await progress(5, "loading file")
        if not file_content:
            file_storage = get_file_storage()
            file_content = await file_storage.download_file("documents", document["storage_path"])
        if not file_content:
            await db.update_document_progress(
                document_id, status="failed", stage="", error="Could not read file from storage"
            )
            return

        # ── 2. Extract text ───────────────────────────────────────────────
        await progress(10, "extracting text")
        text_extractor = get_text_extractor()
        supported = {"pdf", "pptx", "docx", "png", "jpg", "jpeg"}
        file_type = document["file_type"]

        if file_type not in supported:
            await db.update_document_progress(
                document_id, status="failed", stage="", error=f"Unsupported type: {file_type}"
            )
            return

        text, page_count, word_count = await text_extractor.extract_full(file_content, file_type)

        if not text or len(text.strip()) < 10:
            await db.update_document_progress(
                document_id,
                status="failed",
                stage="",
                error="No readable text found in document. If it's a scanned PDF, ensure OCR is supported.",
            )
            return

        await db.update_document_progress(
            document_id,
            progress=20,
            stage=f"extracted {word_count:,} words / {page_count} pages",
            page_count=page_count,
            word_count=word_count,
        )

        # ── 3. Chunk text ─────────────────────────────────────────────────
        await progress(25, "chunking text")
        chunker = get_chunker()

        async def chunk_progress(pct: int, stage: str):
            # Chunking occupies 25-45% of the total bar
            mapped = 25 + int(pct * 0.20)
            await progress(mapped, stage)

        source_meta = {
            "document_id": document_id,
            "original_filename": document["original_filename"],
            "file_type": file_type,
            "page_count": page_count,
        }
        chunks = await chunker.chunk_text_with_progress(
            text, progress_callback=chunk_progress, source_meta=source_meta
        )

        if not chunks:
            await db.update_document_progress(
                document_id, status="failed", stage="", error="Chunking produced no output"
            )
            return

        await db.update_document_progress(
            document_id,
            progress=45,
            stage=f"split into {len(chunks)} chunks",
        )

        # ── 4. Generate embeddings ────────────────────────────────────────
        embedding_service = get_embedding_service()
        chunk_texts = [c["text"] for c in chunks]

        async def embed_progress(pct: int, stage: str):
            # Embedding occupies 45-85% of total bar
            mapped = 45 + int(pct * 0.40)
            await progress(mapped, stage)

        embeddings = await embedding_service.generate_embeddings_batch(
            chunk_texts,
            batch_size=EMBED_BATCH_SIZE,
            progress_callback=embed_progress,
        )

        # ── 5. Store chunks in DB ─────────────────────────────────────────
        await progress(87, "storing chunks")
        chunks_data = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            if not embedding:
                continue
            chunks_data.append({
                "document_id": document_id,
                "subject_id": str(document["subject_id"]),
                "owner_id": str(document["owner_id"]),
                "chunk_index": chunk.get("chunk_index", i),
                "chunk_type": chunk.get("chunk_type", "paragraph"),
                "text": chunk["text"],
                "embedding": embedding,
                "metadata": chunk.get("metadata"),
            })

        if not chunks_data:
            await db.update_document_progress(
                document_id, status="failed", stage="", error="All embeddings failed — model may be unavailable"
            )
            return

        # Store in batches of 500 to avoid large transactions
        STORE_BATCH = 500
        for batch_start in range(0, len(chunks_data), STORE_BATCH):
            await db.create_document_chunks(chunks_data[batch_start:batch_start + STORE_BATCH])

        # ── 6. Finalise ───────────────────────────────────────────────────
        await db.update_document_progress(
            document_id,
            status="completed",
            progress=100,
            stage="done",
            chunk_count=len(chunks_data),
            word_count=word_count,
            page_count=page_count,
        )

        logger.info(
            f"Document {document_id} done: {len(chunks_data)} chunks, "
            f"{page_count} pages, {word_count} words"
        )

        # Fire notification
        try:
            from services.notification_service import notify
            await notify(
                teacher_id=str(document["owner_id"]),
                title="Document ready",
                message=(
                    f'"{document["original_filename"]}" processed — '
                    f'{page_count} page(s), {word_count:,} words, {len(chunks_data)} AI chunks ready.'
                ),
                notification_type="document_processed",
                metadata={
                    "document_id": document_id,
                    "filename": document.get("original_filename", ""),
                    "subject_id": str(document.get("subject_id", "")),
                    "chunk_count": len(chunks_data),
                    "page_count": page_count,
                    "word_count": word_count,
                },
            )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"process_document_async failed for {document_id}: {e}", exc_info=True)
        if db:
            await db.update_document_progress(
                document_id,
                status="failed",
                stage="",
                error=str(e)[:500],
            )
