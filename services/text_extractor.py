"""
Text extraction service for various document formats
"""
import logging
from typing import Optional
import io
import re
import zipfile
import xml.etree.ElementTree as ET

import PyPDF2
from PIL import Image
import pytesseract

try:
    from docx import Document as DocxDocument
except Exception:
    DocxDocument = None

try:
    from pptx import Presentation
except Exception:
    Presentation = None

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
            elif file_type == "docx":
                return await self._extract_docx_text(file_content)
            elif file_type == "pptx":
                return await self._extract_pptx_text(file_content)
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

    async def _extract_docx_text(self, file_content: bytes) -> Optional[str]:
        """Extract text from DOCX"""
        try:
            if DocxDocument is not None:
                doc = DocxDocument(io.BytesIO(file_content))
                parts = []

                for paragraph in doc.paragraphs:
                    text = paragraph.text.strip()
                    if text:
                        parts.append(text)

                for table in doc.tables:
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
                        if cells:
                            parts.append(" | ".join(cells))

                return "\n".join(parts).strip()

            return self._extract_docx_text_xml(file_content)

        except Exception as e:
            logger.error(f"Error extracting DOCX text: {e}")
            return None

    async def _extract_pptx_text(self, file_content: bytes) -> Optional[str]:
        """Extract text from PPTX"""
        try:
            if Presentation is not None:
                presentation = Presentation(io.BytesIO(file_content))
                slides_text = []

                for slide in presentation.slides:
                    lines = []
                    for shape in slide.shapes:
                        text = getattr(shape, "text", "")
                        if text:
                            lines.append(text.strip())
                    if lines:
                        slides_text.append("\n".join(lines))

                return "\n\n".join(slides_text).strip()

            return self._extract_pptx_text_xml(file_content)

        except Exception as e:
            logger.error(f"Error extracting PPTX text: {e}")
            return None

    def _extract_docx_text_xml(self, file_content: bytes) -> Optional[str]:
        """Fallback DOCX extraction using XML"""
        try:
            with zipfile.ZipFile(io.BytesIO(file_content)) as zf:
                with zf.open("word/document.xml") as doc_xml:
                    tree = ET.parse(doc_xml)

            root = tree.getroot()
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = []
            for paragraph in root.iter(f"{ns}p"):
                texts = [node.text for node in paragraph.iter(f"{ns}t") if node.text]
                if texts:
                    paragraphs.append("".join(texts))

            return "\n".join(paragraphs).strip()
        except Exception as e:
            logger.error(f"Error extracting DOCX text (xml): {e}")
            return None

    def _extract_pptx_text_xml(self, file_content: bytes) -> Optional[str]:
        """Fallback PPTX extraction using XML"""
        try:
            with zipfile.ZipFile(io.BytesIO(file_content)) as zf:
                slide_files = [
                    name
                    for name in zf.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                ]
                slide_files.sort(key=self._pptx_slide_sort_key)

                slides_text = []
                text_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
                for slide_name in slide_files:
                    with zf.open(slide_name) as slide_xml:
                        tree = ET.parse(slide_xml)
                    texts = [node.text for node in tree.iter(f"{text_ns}t") if node.text]
                    if texts:
                        slides_text.append(" ".join(texts))

            return "\n\n".join(slides_text).strip()
        except Exception as e:
            logger.error(f"Error extracting PPTX text (xml): {e}")
            return None

    def _pptx_slide_sort_key(self, name: str) -> int:
        match = re.search(r"slide(\d+)\.xml$", name)
        return int(match.group(1)) if match else 0


# Global instance
text_extractor = TextExtractor()


def get_text_extractor() -> TextExtractor:
    """Get text extractor instance"""
    return text_extractor
