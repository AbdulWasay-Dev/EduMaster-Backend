"""
Text extraction service for various document formats
"""
import logging
from typing import Optional
import PyPDF2
import io
from PIL import Image
import pytesseract

logger = logging.getLogger(__name__)


class TextExtractor:
    """Service for extracting text from various document formats"""
    
    def __init__(self):
        """Initialize text extractor"""
        logger.info("✅ Text extractor initialized")
    
    async def extract_text(self, file_content: bytes, file_type: str) -> Optional[str]:
        """Extract text from file content"""
        try:
            if file_type == "pdf":
                return await self._extract_pdf_text(file_content)
            elif file_type in ["png", "jpg", "jpeg"]:
                return await self._extract_image_text(file_content)
            else:
                logger.warning(f"Unsupported file type: {file_type}")
                return None
                
        except Exception as e:
            logger.error(f"Error extracting text: {e}")
            return None
    
    async def _extract_pdf_text(self, file_content: bytes) -> Optional[str]:
        """Extract text from PDF"""
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            text = ""
            
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            
            return text.strip()
            
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            return None
    
    async def _extract_image_text(self, file_content: bytes) -> Optional[str]:
        """Extract text from image using OCR"""
        try:
            image = Image.open(io.BytesIO(file_content))
            text = pytesseract.image_to_string(image)
            return text.strip()
            
        except Exception as e:
            logger.error(f"Error extracting image text: {e}")
            return None


# Global instance
text_extractor = TextExtractor()


def get_text_extractor() -> TextExtractor:
    """Get text extractor instance"""
    return text_extractor
