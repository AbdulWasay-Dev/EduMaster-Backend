"""
Supabase client service for database operations
"""
import logging
from typing import Optional, Dict, Any, List
import io
import mimetypes
from supabase import create_client, Client
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SupabaseService:
    """Supabase service for database operations"""
    
    def __init__(self):
        """Initialize Supabase client"""
        try:
            self.client: Client = create_client(
                settings.supabase_url,
                settings.supabase_anon_key
            )
            self.service_client: Client = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key
            )
            logger.info("✅ Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Supabase client: {e}")
            raise
    
    async def get_teacher(self, teacher_id: str) -> Optional[Dict[str, Any]]:
        """Get teacher by ID"""
        try:
            # Use service client to bypass RLS on server-side
            response = self.service_client.table("teachers").select("*").eq("id", teacher_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error getting teacher {teacher_id}: {e}")
            return None
    
    async def create_teacher(self, teacher_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new teacher"""
        try:
            response = self.client.table("teachers").insert(teacher_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating teacher: {e}")
            return None
    
    async def update_teacher(self, teacher_id: str, teacher_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update teacher data"""
        try:
            response = self.client.table("teachers").update(teacher_data).eq("id", teacher_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error updating teacher {teacher_id}: {e}")
            return None
    
    async def get_subject(self, subject_id: str) -> Optional[Dict[str, Any]]:
        """Get subject by ID"""
        try:
            response = self.service_client.table("subjects").select("*").eq("id", subject_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error getting subject {subject_id}: {e}")
            return None
    
    async def create_subject(self, subject_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new subject"""
        try:
            # Use service client for writes that may be blocked by RLS
            response = self.service_client.table("subjects").insert(subject_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating subject: {e}")
            return None
    
    async def get_subjects(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get subjects by teacher"""
        try:
            response = self.service_client.table("subjects").select("*").eq("teacher_id", teacher_id).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error getting subjects for teacher {teacher_id}: {e}")
            return []
    
    async def create_document(self, document_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new document record"""
        try:
            response = self.service_client.table("documents").insert(document_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating document: {e}")
            return None
    
    async def get_documents(self, subject_id: str) -> List[Dict[str, Any]]:
        """Get documents by subject"""
        try:
            response = self.service_client.table("documents").select("*").eq("subject_id", subject_id).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error getting documents for subject {subject_id}: {e}")
            return []

    async def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID"""
        try:
            response = self.service_client.table("documents").select("*").eq("id", document_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return None

    async def update_document_status(self, document_id: str, status: str) -> bool:
        """Update document processing status"""
        try:
            self.service_client.table("documents").update({"processing_status": status}).eq("id", document_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating document {document_id} status: {e}")
            return False

    async def delete_document(self, document_id: str) -> bool:
        """Delete a document and its chunks"""
        try:
            # Delete chunks first
            self.service_client.table("doc_chunks").delete().eq("document_id", document_id).execute()
            # Delete document
            self.service_client.table("documents").delete().eq("id", document_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting document {document_id}: {e}")
            return False
    
    async def create_document_chunks(self, chunks_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create document chunks with embeddings"""
        try:
            response = self.service_client.table("doc_chunks").insert(chunks_data).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error creating document chunks: {e}")
            return []
    
    async def search_similar_chunks(
        self, 
        embedding: List[float], 
        subject_id: str, 
        limit: int = 5,
        match_threshold: float | None = None,
    ) -> List[Dict[str, Any]]:
        """Search for similar chunks using vector similarity"""
        try:
            # Use pgvector similarity search
            response = self.service_client.rpc(
                "search_similar_chunks",
                {
                    "query_embedding": embedding,
                    "subject_id": subject_id,
                    "match_threshold": match_threshold if match_threshold is not None else settings.similarity_threshold,
                    "match_count": limit,
                }
            ).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error searching similar chunks: {e}")
            return []
    
    async def create_paper(self, paper_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new paper"""
        try:
            response = self.service_client.table("papers").insert(paper_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating paper: {e}")
            return None
    
    async def get_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """Get paper by ID"""
        try:
            response = self.service_client.table("papers").select("*").eq("id", paper_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error getting paper {paper_id}: {e}")
            return None
    
    async def update_paper(self, paper_id: str, paper_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update paper"""
        try:
            response = self.service_client.table("papers").update(paper_data).eq("id", paper_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error updating paper {paper_id}: {e}")
            return None
    
    async def get_papers(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get papers by teacher"""
        try:
            response = self.service_client.table("papers").select("*").eq("owner_id", teacher_id).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error getting papers for teacher {teacher_id}: {e}")
            return []
    
    async def upload_file(self, bucket_name: str, file_path: str, file_data: bytes) -> Optional[str]:
        """Upload file to Supabase storage"""
        try:
            # Try upload; if bucket missing, create it and retry
            try:
                content_type, _ = mimetypes.guess_type(file_path)
                self.service_client.storage.from_(bucket_name).upload(
                    file_path,
                    file_data,
                    {
                        "content-type": content_type or "application/octet-stream",
                        "upsert": "true",
                    },
                )
            except Exception as e:
                # Attempt to create bucket and retry
                try:
                    self.service_client.storage.create_bucket(bucket_name, public=True)
                except Exception:
                    pass
                content_type, _ = mimetypes.guess_type(file_path)
                self.service_client.storage.from_(bucket_name).upload(
                    file_path,
                    file_data,
                    {
                        "content-type": content_type or "application/octet-stream",
                        "upsert": "true",
                    },
                )

            # Some SDKs return None on success; verify by fetching public URL
            result = self.service_client.storage.from_(bucket_name).get_public_url(file_path)
            if isinstance(result, dict):
                url = result.get("publicUrl") or result.get("public_url") or result.get("signedURL")
            else:
                url = result
            return url
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return None
    
    async def download_file(self, bucket_name: str, file_path: str) -> Optional[bytes]:
        """Download file from Supabase storage"""
        try:
            response = self.service_client.storage.from_(bucket_name).download(file_path)
            return response
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None
    
    async def delete_file(self, bucket_name: str, file_path: str) -> bool:
        """Delete file from Supabase storage"""
        try:
            response = self.client.storage.from_(bucket_name).remove([file_path])
            return not response.get("error")
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False
    
    # Student Management Methods
    async def create_student(self, student_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new student"""
        try:
            response = self.service_client.table("students").insert(student_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating student: {e}")
            return None
    
    async def get_students(self, class_id: str) -> List[Dict[str, Any]]:
        """Get students by class"""
        try:
            response = self.service_client.table("students").select("*").eq("class_id", class_id).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error getting students for class {class_id}: {e}")
            return []
    
    async def get_student(self, student_id: str) -> Optional[Dict[str, Any]]:
        """Get student by ID"""
        try:
            response = self.service_client.table("students").select("*").eq("id", student_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error getting student {student_id}: {e}")
            return None
    
    async def update_student(self, student_id: str, student_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update student data"""
        try:
            response = self.service_client.table("students").update(student_data).eq("id", student_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error updating student {student_id}: {e}")
            return None
    
    async def delete_student(self, student_id: str) -> bool:
        """Delete student"""
        try:
            self.service_client.table("students").delete().eq("id", student_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting student {student_id}: {e}")
            return False
    
    # Class Management Methods
    async def create_class(self, class_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new class"""
        try:
            response = self.service_client.table("classes").insert(class_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating class: {e}")
            return None
    
    async def get_classes(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get classes by teacher"""
        try:
            response = self.service_client.table("classes").select("*").eq("teacher_id", teacher_id).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error getting classes for teacher {teacher_id}: {e}")
            return []
    
    # Answer Sheet Grading Methods
    async def create_submission(self, submission_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new submission"""
        try:
            # Use service role client to bypass RLS for server-side trusted insert
            response = self.service_client.table("submissions").insert(submission_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating submission: {e}")
            return None
    
    async def get_submissions(self, paper_id: str) -> List[Dict[str, Any]]:
        """Get submissions by paper"""
        try:
            # Use service client to avoid RLS filtering on server-side fetches
            response = self.service_client.table("submissions").select("*").eq("paper_id", paper_id).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error getting submissions for paper {paper_id}: {e}")
            return []

    async def get_submission(self, submission_id: str) -> Optional[Dict[str, Any]]:
        """Get single submission by ID"""
        try:
            response = self.service_client.table("submissions").select("*").eq("id", submission_id).limit(1).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error getting submission {submission_id}: {e}")
            return None
    
    async def update_submission(self, submission_id: str, submission_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update submission"""
        try:
            response = self.service_client.table("submissions").update(submission_data).eq("id", submission_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error updating submission {submission_id}: {e}")
            return None

    async def delete_submission(self, submission_id: str) -> bool:
        """Delete a submission by ID"""
        try:
            self.service_client.table("submissions").delete().eq("id", submission_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting submission {submission_id}: {e}")
            return False


# Global instance
supabase_service = SupabaseService()


def get_supabase_service() -> SupabaseService:
    """Get Supabase service instance"""
    return supabase_service
