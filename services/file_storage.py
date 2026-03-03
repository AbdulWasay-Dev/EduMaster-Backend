"""
Local File Storage Service for EduMaster Backend
Replaces Supabase Storage with local filesystem storage
"""
import os
import logging
import uuid
import shutil
from pathlib import Path
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class FileStorageService:
    """Local file storage service to replace Supabase Storage"""
    
    def __init__(self):
        """Initialize storage directory"""
        self.base_path = Path(settings.upload_path).resolve()
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure storage directories exist"""
        self.base_path.mkdir(parents=True, exist_ok=True)
        # Create subdirectories for different buckets
        (self.base_path / "documents").mkdir(exist_ok=True)
        (self.base_path / "answer_sheets").mkdir(exist_ok=True)
        logger.info(f"✅ File storage initialized at: {self.base_path}")
    
    def _get_full_path(self, bucket_name: str, file_path: str) -> Path:
        """Get full filesystem path for a file"""
        return self.base_path / bucket_name / file_path
    
    async def upload_file(self, bucket_name: str, file_path: str, file_data: bytes) -> Optional[str]:
        """
        Upload file to local storage
        
        Returns the relative path that can be used as a URL
        """
        try:
            full_path = self._get_full_path(bucket_name, file_path)
            
            # Ensure parent directory exists
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file
            with open(full_path, 'wb') as f:
                f.write(file_data)
            
            # Return relative URL path
            relative_path = f"/static/uploads/{bucket_name}/{file_path}"
            logger.info(f"File uploaded: {relative_path}")
            return relative_path
            
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return None
    
    async def download_file(self, bucket_name: str, file_path: str) -> Optional[bytes]:
        """Download file from local storage"""
        try:
            full_path = self._get_full_path(bucket_name, file_path)
            
            if not full_path.exists():
                logger.error(f"File not found: {full_path}")
                return None
            
            with open(full_path, 'rb') as f:
                return f.read()
                
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None
    
    async def delete_file(self, bucket_name: str, file_path: str) -> bool:
        """Delete file from local storage"""
        try:
            full_path = self._get_full_path(bucket_name, file_path)
            
            if full_path.exists():
                full_path.unlink()
                logger.info(f"File deleted: {full_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False
    
    async def file_exists(self, bucket_name: str, file_path: str) -> bool:
        """Check if file exists"""
        full_path = self._get_full_path(bucket_name, file_path)
        return full_path.exists()
    
    def get_public_url(self, bucket_name: str, file_path: str) -> str:
        """Get public URL for a file (served by FastAPI static files)"""
        return f"/static/uploads/{bucket_name}/{file_path}"


# Global instance
_file_storage_service: Optional[FileStorageService] = None


def get_file_storage() -> FileStorageService:
    """Get file storage service instance"""
    global _file_storage_service
    if _file_storage_service is None:
        _file_storage_service = FileStorageService()
    return _file_storage_service
