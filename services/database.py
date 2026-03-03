"""
PostgreSQL Database Service for EduMaster Backend
Replaces Supabase client with direct asyncpg connection
Integrates ChromaDB for vector similarity search
"""
import logging
import uuid
import os
import json
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

import asyncpg
from asyncpg import Pool
import chromadb
from chromadb.config import Settings as ChromaSettings

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DatabaseService:
    """Async PostgreSQL database service and ChromaDB client"""
    
    _pool: Optional[Pool] = None
    _chroma_client: Optional[chromadb.Client] = None
    
    async def initialize(self):
        """Initialize connection pools and clients"""
        # Initialize PostgreSQL
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    settings.database_url,
                    min_size=2,
                    max_size=10,
                    command_timeout=60
                )
                logger.info("✅ PostgreSQL connection pool initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize PostgreSQL pool: {e}")
                raise

        # Initialize ChromaDB
        if self._chroma_client is None:
            try:
                os.makedirs(settings.chroma_db_path, exist_ok=True)
                self._chroma_client = chromadb.PersistentClient(
                    path=settings.chroma_db_path,
                    settings=ChromaSettings(allow_reset=True)
                )
                logger.info(f"✅ ChromaDB initialized at {settings.chroma_db_path}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize ChromaDB: {e}")
                raise
    
    async def close(self):
        """Close connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL connection pool closed")
    
    @asynccontextmanager
    async def connection(self):
        """Get a connection from the pool"""
        if self._pool is None:
            await self.initialize()
        async with self._pool.acquire() as conn:
            yield conn
    
    async def check_connection(self) -> bool:
        """Check if database connection is working"""
        try:
            async with self.connection() as conn:
                await conn.fetchval("SELECT 1")
            return self._chroma_client is not None
        except Exception as e:
            logger.error(f"Database connection check failed: {e}")
            return False

    # ==================== Teacher Operations ====================
    
    async def get_teacher(self, teacher_id: str) -> Optional[Dict[str, Any]]:
        """Get teacher by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM teachers WHERE id = $1",
                    uuid.UUID(teacher_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting teacher {teacher_id}: {e}")
            return None
    
    async def get_teacher_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get teacher by email"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM teachers WHERE email = $1",
                    email
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting teacher by email {email}: {e}")
            return None
    
    async def create_teacher(self, teacher_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new teacher"""
        try:
            teacher_id = teacher_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO teachers (id, email, name, role, password_hash, profile_image_url, school_name, department)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING *
                    """,
                    uuid.UUID(teacher_id),
                    teacher_data["email"],
                    teacher_data["name"],
                    teacher_data.get("role", "teacher"),
                    teacher_data.get("password_hash"),
                    teacher_data.get("profile_image_url"),
                    teacher_data.get("school_name"),
                    teacher_data.get("department")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating teacher: {e}")
            return None
    
    async def update_teacher(self, teacher_id: str, teacher_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update teacher data"""
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in teacher_data.items():
                if key != "id":
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
            
            if not set_clauses:
                return await self.get_teacher(teacher_id)
            
            values.append(uuid.UUID(teacher_id))
            query = f"UPDATE teachers SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating teacher {teacher_id}: {e}")
            return None

    # ==================== Subject Operations ====================
    
    async def get_subject(self, subject_id: str) -> Optional[Dict[str, Any]]:
        """Get subject by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM subjects WHERE id = $1",
                    uuid.UUID(subject_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting subject {subject_id}: {e}")
            return None
    
    async def create_subject(self, subject_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new subject"""
        try:
            subject_id = subject_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO subjects (id, teacher_id, class_id, name, description, color_code)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                    """,
                    uuid.UUID(subject_id),
                    uuid.UUID(subject_data["teacher_id"]),
                    uuid.UUID(subject_data["class_id"]) if subject_data.get("class_id") else None,
                    subject_data["name"],
                    subject_data.get("description"),
                    subject_data.get("color_code")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating subject: {e}")
            return None
    
    async def get_subjects(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get subjects by teacher"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM subjects WHERE teacher_id = $1",
                    uuid.UUID(teacher_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting subjects for teacher {teacher_id}: {e}")
            return []

    # ==================== Document Operations ====================
    
    async def create_document(self, document_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new document record"""
        try:
            doc_id = document_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO documents (id, subject_id, owner_id, filename, original_filename, 
                                          storage_path, file_type, file_size, processing_status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING *
                    """,
                    uuid.UUID(doc_id),
                    uuid.UUID(document_data["subject_id"]),
                    uuid.UUID(document_data["owner_id"]),
                    document_data["filename"],
                    document_data["original_filename"],
                    document_data["storage_path"],
                    document_data["file_type"],
                    document_data.get("file_size", 0),
                    document_data.get("processing_status", "pending")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating document: {e}")
            return None
    
    async def get_documents(self, subject_id: str) -> List[Dict[str, Any]]:
        """Get documents by subject"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM documents WHERE subject_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(subject_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting documents for subject {subject_id}: {e}")
            return []

    async def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM documents WHERE id = $1",
                    uuid.UUID(document_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return None

    async def get_document_chunks(self, document_id: str) -> List[Dict[str, Any]]:
        """Get text chunks for a document"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT id, chunk_index, text, metadata FROM doc_chunks WHERE document_id = $1 ORDER BY chunk_index",
                    uuid.UUID(document_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting chunks for document {document_id}: {e}")
            return []

    async def update_document_status(self, document_id: str, status: str) -> bool:
        """Update document processing status"""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "UPDATE documents SET processing_status = $1, updated_at = NOW() WHERE id = $2",
                    status,
                    uuid.UUID(document_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating document {document_id} status: {e}")
            return False

    async def delete_document(self, document_id: str) -> bool:
        """Delete a document and its chunks from PostgreSQL and ChromaDB"""
        try:
            # Get subject_id first to find the ChromaDB collection
            document = await self.get_document(document_id)
            if not document:
                return False
            
            subject_id = str(document["subject_id"])
            
            async with self.connection() as conn:
                # Delete from PostgreSQL
                await conn.execute(
                    "DELETE FROM doc_chunks WHERE document_id = $1",
                    uuid.UUID(document_id)
                )
                await conn.execute(
                    "DELETE FROM documents WHERE id = $1",
                    uuid.UUID(document_id)
                )
            
            # Delete from ChromaDB
            try:
                collection_name = f"subject_{subject_id.replace('-', '_')}"
                collection = self._chroma_client.get_collection(name=collection_name)
                # Chroma delete by where metadata
                collection.delete(where={"document_id": str(document_id)})
                logger.info(f"Deleted chunks for document {document_id} from ChromaDB")
            except Exception as ce:
                logger.warning(f"Could not delete from ChromaDB (collection might not exist): {ce}")
                
            return True
        except Exception as e:
            logger.error(f"Error deleting document {document_id}: {e}")
            return False

    # ==================== Document Chunks Operations ====================
    
    async def create_document_chunks(self, chunks_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create document chunks in PostgreSQL and embeddings in ChromaDB"""
        try:
            if not chunks_data:
                return []
            
            # 1. Store relational data in PostgreSQL
            results = []
            async with self.connection() as conn:
                for chunk in chunks_data:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO doc_chunks (document_id, subject_id, owner_id, chunk_index, text)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id, document_id, chunk_index, text
                        """,
                        uuid.UUID(chunk["document_id"]),
                        uuid.UUID(chunk["subject_id"]),
                        uuid.UUID(chunk["owner_id"]),
                        chunk["chunk_index"],
                        chunk["text"]
                    )
                    if row:
                        results.append(dict(row))
            
            # 2. Store embeddings in ChromaDB
            if results:
                subject_id = str(chunks_data[0]["subject_id"])
                collection = self._chroma_client.get_or_create_collection(
                    name=f"subject_{subject_id.replace('-', '_')}"
                )
                
                ids = [str(r["id"]) for r in results]
                embeddings = [c["embedding"] for c in chunks_data]
                metadatas = [{"document_id": str(c["document_id"]), "chunk_index": c["chunk_index"]} for c in chunks_data]
                documents = [c["text"] for c in chunks_data]
                
                collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=documents
                )
                logger.info(f"Added {len(ids)} chunks to ChromaDB collection for subject {subject_id}")
                
            return results
        except Exception as e:
            logger.error(f"Error creating document chunks: {e}")
            return []
    
    async def search_similar_chunks(
        self, 
        embedding: List[float], 
        subject_id: str, 
        limit: int = 5,
        match_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Search for similar chunks using ChromaDB"""
        try:
            collection_name = f"subject_{subject_id.replace('-', '_')}"
            collection = self._chroma_client.get_or_create_collection(name=collection_name)
            
            results = collection.query(
                query_embeddings=[embedding],
                n_results=limit,
                include=["documents", "metadatas", "distances"]
            )
            
            search_results = []
            if results["ids"] and results["ids"][0]:
                for i in range(len(results["ids"][0])):
                    distance = results["distances"][0][i]
                    # Assuming default is cosine distance (0 to 2, where 0 is identical)
                    # For cosine, similarity = 1 - (distance / 2)? Or if it's cosine similarity...
                    # Chroma default is l2 (squared L2 distance). 
                    # If we use cosine, it's 1.0 - distance.
                    similarity = 1.0 - (distance / 2.0) if distance <= 2.0 else 0.0
                    
                    if similarity >= match_threshold:
                        search_results.append({
                            "id": results["ids"][0][i],
                            "document_id": results["metadatas"][0][i]["document_id"],
                            "text": results["documents"][0][i],
                            "similarity": similarity
                        })
            
            return search_results
        except Exception as e:
            logger.error(f"Error searching similar chunks in ChromaDB: {e}")
            return []

    # ==================== Paper Operations ====================
    
    async def create_paper(self, paper_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new paper"""
        try:
            paper_id = paper_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO papers (id, subject_id, class_id, owner_id, title, description, 
                                       questions, configuration, answer_key, total_marks, is_published)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING *
                    """,
                    uuid.UUID(paper_id),
                    uuid.UUID(paper_data["subject_id"]),
                    uuid.UUID(paper_data["class_id"]) if paper_data.get("class_id") else None,
                    uuid.UUID(paper_data["owner_id"]) if paper_data.get("owner_id") else None,
                    paper_data["title"],
                    paper_data.get("description"),
                    json.dumps(paper_data.get("questions", [])),
                    json.dumps(paper_data.get("configuration", {})),
                    json.dumps(paper_data.get("answer_key", {})),
                    paper_data.get("total_marks", 0),
                    paper_data.get("is_published", False)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating paper: {e}")
            return None
    
    async def get_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """Get paper by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM papers WHERE id = $1",
                    uuid.UUID(paper_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting paper {paper_id}: {e}")
            return None
    
    async def update_paper(self, paper_id: str, paper_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update paper"""
        try:
            set_clauses = []
            values = []
            idx = 1
            
            for key, value in paper_data.items():
                if key == "id":
                    continue
                if key in ["questions", "configuration", "answer_key"]:
                    value = json.dumps(value)
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1
            
            if not set_clauses:
                return await self.get_paper(paper_id)
            
            values.append(uuid.UUID(paper_id))
            query = f"UPDATE papers SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating paper {paper_id}: {e}")
            return None
    
    async def get_papers(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get papers by teacher"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM papers WHERE owner_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(teacher_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting papers for teacher {teacher_id}: {e}")
            return []

    async def get_papers_by_class(self, class_id: str) -> List[Dict[str, Any]]:
        """Get papers by class ID"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM papers WHERE class_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(class_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting papers for class {class_id}: {e}")
            return []

    # ==================== Student Operations ====================
    
    async def create_student(self, student_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new student"""
        try:
            student_id = student_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO students (id, class_id, student_name, student_id, email, phone)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                    """,
                    uuid.UUID(student_id),
                    uuid.UUID(student_data["class_id"]),
                    student_data["student_name"],
                    student_data.get("student_id"),
                    student_data.get("email"),
                    student_data.get("phone")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating student: {e}")
            return None
    
    async def get_students(self, class_id: str) -> List[Dict[str, Any]]:
        """Get students by class"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM students WHERE class_id = $1 ORDER BY student_name",
                    uuid.UUID(class_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting students for class {class_id}: {e}")
            return []
    
    async def get_student(self, student_id: str) -> Optional[Dict[str, Any]]:
        """Get student by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM students WHERE id = $1",
                    uuid.UUID(student_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting student {student_id}: {e}")
            return None
    
    async def update_student(self, student_id: str, student_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update student data"""
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in student_data.items():
                if key != "id":
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
            
            if not set_clauses:
                return await self.get_student(student_id)
            
            values.append(uuid.UUID(student_id))
            query = f"UPDATE students SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating student {student_id}: {e}")
            return None
    
    async def delete_student(self, student_id: str) -> bool:
        """Delete student"""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "DELETE FROM students WHERE id = $1",
                    uuid.UUID(student_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting student {student_id}: {e}")
            return False

    # ==================== Class Operations ====================
    
    async def create_class(self, class_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new class"""
        try:
            class_id = class_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO classes (id, teacher_id, name, description, grade_level, subject_area, academic_year, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING *
                    """,
                    uuid.UUID(class_id),
                    uuid.UUID(class_data["teacher_id"]),
                    class_data["name"],
                    class_data.get("description"),
                    class_data.get("grade_level"),
                    class_data.get("subject_area"),
                    class_data.get("academic_year"),
                    class_data.get("is_active", True)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating class: {e}")
            return None
    
    async def get_classes(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get classes by teacher"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM classes WHERE teacher_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(teacher_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting classes for teacher {teacher_id}: {e}")
            return []

    async def get_class(self, class_id: str) -> Optional[Dict[str, Any]]:
        """Get class by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM classes WHERE id = $1",
                    uuid.UUID(class_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting class {class_id}: {e}")
            return None

    # ==================== Submission Operations ====================
    
    async def create_submission(self, submission_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new submission"""
        try:
            sub_id = submission_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO submissions (id, paper_id, student_id, class_id, student_name, storage_path, 
                                            ocr_text, submission_data, total_score, grade_percentage, feedback, grading_status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    RETURNING *
                    """,
                    uuid.UUID(sub_id),
                    uuid.UUID(submission_data["paper_id"]),
                    uuid.UUID(submission_data["student_id"]) if submission_data.get("student_id") else None,
                    uuid.UUID(submission_data["class_id"]) if submission_data.get("class_id") else None,
                    submission_data.get("student_name", ""),
                    submission_data.get("storage_path"),
                    submission_data.get("ocr_text"),
                    json.dumps(submission_data.get("submission_data", {})) if submission_data.get("submission_data") else None,
                    submission_data.get("total_score"),
                    submission_data.get("grade_percentage"),
                    submission_data.get("feedback"),
                    submission_data.get("grading_status", "pending")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating submission: {e}")
            return None
    
    async def get_submissions(self, paper_id: str) -> List[Dict[str, Any]]:
        """Get submissions by paper"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM submissions WHERE paper_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(paper_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting submissions for paper {paper_id}: {e}")
            return []

    async def get_submission(self, submission_id: str) -> Optional[Dict[str, Any]]:
        """Get single submission by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM submissions WHERE id = $1",
                    uuid.UUID(submission_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting submission {submission_id}: {e}")
            return None
    
    async def update_submission(self, submission_id: str, submission_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update submission"""
        try:
            set_clauses = []
            values = []
            idx = 1
            
            for key, value in submission_data.items():
                if key == "id":
                    continue
                if key == "submission_data" and isinstance(value, dict):
                    value = json.dumps(value)
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1
            
            if not set_clauses:
                return await self.get_submission(submission_id)
            
            values.append(uuid.UUID(submission_id))
            query = f"UPDATE submissions SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating submission {submission_id}: {e}")
            return None

    async def get_submissions_by_status(self, paper_id: str, status: str) -> List[Dict[str, Any]]:
        """Get submissions by paper and grading status"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM submissions WHERE paper_id = $1 AND grading_status = $2",
                    uuid.UUID(paper_id),
                    status
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting submissions for paper {paper_id} with status {status}: {e}")
            return []

    async def delete_submission(self, submission_id: str) -> bool:
        """Delete a submission by ID"""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "DELETE FROM submissions WHERE id = $1",
                    uuid.UUID(submission_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting submission {submission_id}: {e}")
            return False

    # ==================== Additional Query Methods ====================
    
    async def get_doc_chunks_by_subject(self, subject_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get document chunks by subject ID"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT id, document_id, subject_id, owner_id, chunk_index, text FROM doc_chunks WHERE subject_id = $1 LIMIT $2",
                    uuid.UUID(subject_id),
                    limit
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting chunks for subject {subject_id}: {e}")
            return []


# Global instance
_database_service: Optional[DatabaseService] = None


async def get_database() -> DatabaseService:
    """Get database service instance (initializes on first call)"""
    global _database_service
    if _database_service is None:
        _database_service = DatabaseService()
        await _database_service.initialize()
    return _database_service


def get_database_sync() -> DatabaseService:
    """Get database service instance (sync version, assumes already initialized)"""
    global _database_service
    if _database_service is None:
        _database_service = DatabaseService()
    return _database_service
