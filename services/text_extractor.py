"""
Advanced text extraction service.
Handles PDFs (PyPDF2 with pdfminer fallback), DOCX, PPTX, and images (OCR).
Returns (text, page_count, word_count) for progress tracking.
"""
import logging
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

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

# Optional: pdfminer for scanned / complex PDFs
try:
    from pdfminer.high_level import extract_text as pdfminer_extract
    _PDFMINER_OK = True
except ImportError:
    _PDFMINER_OK = False

logger = logging.getLogger(__name__)

ExtractionResult = Tuple[Optional[str], int, int]   # (text, page_count, word_count)


class TextExtractor:
    """
    Robust multi-format text extractor.
    All extract_* methods return (text, page_count, word_count).
    The public extract_text() method preserves backward compat (returns text only).
    """

    def __init__(self):
        logger.info("TextExtractor ready — PDF(PyPDF2+pdfminer), DOCX, PPTX, OCR")

    # ── Public API (backward-compatible) ─────────────────────────────────────

    async def extract_text(self, file_content: bytes, file_type: str) -> Optional[str]:
        """Backward-compat wrapper — returns text string or None."""
        text, _, _ = await self.extract_full(file_content, file_type)
        return text

    async def extract_full(
        self,
        file_content: bytes,
        file_type: str,
    ) -> ExtractionResult:
        """
        Full extraction: returns (text, page_count, word_count).
        Raises nothing — errors are logged and returned as (None, 0, 0).
        """
        try:
            ft = file_type.lower().lstrip(".")
            if ft == "pdf":
                return await self._extract_pdf(file_content)
            elif ft == "docx":
                return await self._extract_docx(file_content)
            elif ft == "pptx":
                return await self._extract_pptx(file_content)
            elif ft in {"png", "jpg", "jpeg"}:
                return await self._extract_image(file_content)
            else:
                logger.warning(f"Unsupported file type: {file_type}")
                return None, 0, 0
        except Exception as e:
            logger.error(f"extract_full failed ({file_type}): {e}")
            return None, 0, 0

    # ── PDF ───────────────────────────────────────────────────────────────────

    async def _extract_pdf(self, data: bytes) -> ExtractionResult:
        """
        Two-pass PDF extraction:
          1. PyPDF2 (fast, works for text-layer PDFs)
          2. pdfminer (better for complex/rotated layouts)
        Falls back to per-page OCR if both yield < 100 chars.
        """
        pages_text: list[str] = []
        page_count = 0

        # --- Pass 1: PyPDF2 ---
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            page_count = len(reader.pages)
            for page in reader.pages:
                try:
                    pages_text.append(page.extract_text() or "")
                except Exception:
                    pages_text.append("")
        except Exception as e:
            logger.warning(f"PyPDF2 failed: {e}")

        text = "\n".join(pages_text).strip()

        # --- Pass 2: pdfminer if PyPDF2 gave very little ---
        if len(text) < 200 and _PDFMINER_OK:
            try:
                import asyncio
                from functools import partial
                loop = asyncio.get_event_loop()
                text_pm = await loop.run_in_executor(
                    None,
                    partial(pdfminer_extract, io.BytesIO(data)),
                )
                if text_pm and len(text_pm.strip()) > len(text):
                    text = text_pm.strip()
                    logger.info("Used pdfminer fallback — better extraction")
            except Exception as e:
                logger.warning(f"pdfminer fallback failed: {e}")

        # --- Pass 3: OCR on pages that have no text (scanned PDFs) ---
        if len(text) < 100 or (page_count > 0 and len(text) / page_count < 50):
            try:
                import fitz  # PyMuPDF
                text_parts: list[str] = []
                doc = fitz.open(stream=data, filetype="pdf")
                page_count = len(doc)
                for page in doc:
                    page_text = page.get_text().strip()
                    if len(page_text) < 50:
                        # Render page to image and OCR
                        pix = page.get_pixmap(dpi=200)
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        page_text = pytesseract.image_to_string(img)
                    text_parts.append(page_text)
                text = "\n\n".join(text_parts).strip()
                doc.close()
            except ImportError:
                logger.warning("PyMuPDF not installed — skipping OCR fallback")
            except Exception as e:
                logger.warning(f"OCR fallback failed: {e}")

        word_count = len(text.split()) if text else 0
        return (text if text else None), page_count, word_count

    # ── DOCX ─────────────────────────────────────────────────────────────────

    async def _extract_docx(self, data: bytes) -> ExtractionResult:
        """Extract text from DOCX — paragraphs + tables, with section headings preserved."""
        try:
            if DocxDocument is not None:
                doc = DocxDocument(io.BytesIO(data))
                parts: list[str] = []
                page_estimate = 1  # DOCX has no true page count

                for para in doc.paragraphs:
                    t = para.text.strip()
                    if not t:
                        continue
                    # Preserve heading structure as markdown-like prefix
                    style_name = (para.style.name or "").lower()
                    if "heading" in style_name:
                        try:
                            level = int(re.search(r"\d", style_name).group())
                        except Exception:
                            level = 1
                        parts.append("#" * level + " " + t)
                    else:
                        parts.append(t)

                for table in doc.tables:
                    for row in table.rows:
                        cells = [c.text.strip() for c in row.cells if c.text.strip()]
                        if cells:
                            parts.append(" | ".join(cells))

                # Rough page estimate: ~500 words per page
                text = "\n\n".join(parts)
                words = len(text.split())
                page_estimate = max(1, words // 500)
                return text.strip() or None, page_estimate, words

            # XML fallback
            text = self._extract_docx_xml(data)
            wc = len(text.split()) if text else 0
            return text, max(1, wc // 500), wc

        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
            return None, 0, 0

    # ── PPTX ─────────────────────────────────────────────────────────────────

    async def _extract_pptx(self, data: bytes) -> ExtractionResult:
        """Extract text from PPTX — one block per slide with slide-number prefix."""
        try:
            if Presentation is not None:
                prs = Presentation(io.BytesIO(data))
                slides_text: list[str] = []

                for i, slide in enumerate(prs.slides, 1):
                    lines: list[str] = []
                    for shape in slide.shapes:
                        # Title shapes get a heading prefix
                        is_title = hasattr(shape, "shape_type") and shape.shape_type == 13
                        raw = getattr(shape, "text", "").strip()
                        if not raw:
                            continue
                        if is_title or (hasattr(shape, "name") and "title" in (shape.name or "").lower()):
                            lines.insert(0, f"## {raw}")
                        else:
                            lines.append(raw)
                    if lines:
                        slides_text.append(f"### Slide {i}\n" + "\n".join(lines))

                text = "\n\n".join(slides_text).strip()
                wc = len(text.split())
                return text or None, len(prs.slides), wc

            text = self._extract_pptx_xml(data)
            wc = len(text.split()) if text else 0
            return text, 0, wc

        except Exception as e:
            logger.error(f"PPTX extraction failed: {e}")
            return None, 0, 0

    # ── Image (OCR) ───────────────────────────────────────────────────────────

    async def _extract_image(self, data: bytes) -> ExtractionResult:
        """OCR an image using Tesseract."""
        try:
            image = Image.open(io.BytesIO(data))
            # Upscale small images for better OCR
            w, h = image.size
            if w < 1000:
                scale = 1000 / w
                image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            text = pytesseract.image_to_string(image, config="--psm 6")
            wc = len(text.split()) if text else 0
            return text.strip() or None, 1, wc
        except Exception as e:
            logger.error(f"Image OCR failed: {e}")
            return None, 1, 0

    # ── XML fallbacks ─────────────────────────────────────────────────────────

    def _extract_docx_xml(self, data: bytes) -> Optional[str]:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                with zf.open("word/document.xml") as f:
                    tree = ET.parse(f)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paras: list[str] = []
            for para in tree.getroot().iter(f"{ns}p"):
                texts = [n.text for n in para.iter(f"{ns}t") if n.text]
                if texts:
                    paras.append("".join(texts))
            return "\n".join(paras).strip() or None
        except Exception as e:
            logger.error(f"DOCX XML extraction failed: {e}")
            return None

    def _extract_pptx_xml(self, data: bytes) -> Optional[str]:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                slide_files = sorted(
                    [n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
                    key=lambda x: int(re.search(r"slide(\d+)", x).group(1)),
                )
                text_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
                slides: list[str] = []
                for sf in slide_files:
                    with zf.open(sf) as f:
                        tree = ET.parse(f)
                    texts = [n.text for n in tree.iter(f"{text_ns}t") if n.text]
                    if texts:
                        slides.append(" ".join(texts))
            return "\n\n".join(slides).strip() or None
        except Exception as e:
            logger.error(f"PPTX XML extraction failed: {e}")
            return None

    def _pptx_slide_sort_key(self, name: str) -> int:
        match = re.search(r"slide(\d+)\.xml$", name)
        return int(match.group(1)) if match else 0


# ── Singleton ─────────────────────────────────────────────────────────────────
_text_extractor: Optional[TextExtractor] = None


def get_text_extractor() -> TextExtractor:
    global _text_extractor
    if _text_extractor is None:
        _text_extractor = TextExtractor()
    return _text_extractor
