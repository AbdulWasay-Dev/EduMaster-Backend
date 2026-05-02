"""
OCR Service using local Tesseract OCR for handwritten text extraction
"""
import logging
import base64
from typing import List, Dict, Any, Optional
import io
from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np
import pytesseract
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class OCRService:
    """Service for OCR processing using local Tesseract pipeline"""
    
    def __init__(self):
        """Initialize OCR service and auto-configure Tesseract path."""
        self._configure_tesseract()
        logger.info("✅ OCR service initialized (Tesseract)")
    
    def _configure_tesseract(self):
        """
        Configure the Tesseract executable path.

        Priority:
        1. TESSERACT_PATH env var (via settings)
        2. Common Windows install locations (auto-detect)
        3. Hope it is on the system PATH already
        """
        import os

        # 1. Explicit env override
        if settings.tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_path
            logger.info(f"Tesseract path from env: {settings.tesseract_path}")
            return

        # 2. Auto-detect on Windows
        windows_candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe"),
        ]
        for path in windows_candidates:
            if os.path.isfile(path):
                pytesseract.pytesseract.tesseract_cmd = path
                logger.info(f"Tesseract auto-detected at: {path}")
                return

        # 3. Fall back — assume it is on PATH
        logger.warning(
            "Tesseract not found in common Windows locations. "
            "Set TESSERACT_PATH in .env if OCR fails."
        )
    
    def encode_image(self, image_path: str) -> Optional[str]:
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except FileNotFoundError:
            logger.error(f"Error: The file {image_path} was not found.")
            return None
        except Exception as e:
            logger.error(f"Error encoding image: {e}")
            return None
    
    def encode_image_from_bytes(self, image_bytes: bytes) -> str:
        try:
            return base64.b64encode(image_bytes).decode('utf-8')
        except Exception as e:
            logger.error(f"Error encoding image bytes: {e}")
            raise
    
    def _decode_base64_to_bytes(self, base64_image: str) -> Optional[bytes]:
        try:
            if base64_image.startswith('data:image'):
                base64_image = base64_image.split(',', 1)[1]
            return base64.b64decode(base64_image)
        except Exception as e:
            logger.error(f"Error decoding base64 image: {e}")
            return None
    
    def _preprocess_for_ocr(self, image_bytes: bytes) -> Optional[np.ndarray]:
        """
        Multi-strategy preprocessing for handwritten answer sheets.
        Tries multiple approaches and picks the one that yields the most text.
        """
        try:
            pil_image = Image.open(io.BytesIO(image_bytes)).convert('RGB')

            # Resize if too small — Tesseract works better with larger images
            w, h = pil_image.size
            if max(w, h) < 1500:
                scale = 1500 / max(w, h)
                pil_image = pil_image.resize(
                    (int(w * scale), int(h * scale)), Image.LANCZOS
                )

            cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)

            # Strategy 1: Simple Otsu threshold (best for clean scans)
            _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Strategy 2: Adaptive threshold with large block size (better for
            # uneven lighting / phone photos of handwritten sheets)
            adaptive = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 15
            )

            # Strategy 3: Contrast-enhanced grayscale (no binarization,
            # preserves more handwriting detail)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced_gray = clahe.apply(gray)

            # Run Tesseract on all three and pick the one with the most output
            best_image = gray  # fallback
            best_len = 0

            for label, candidate in [("otsu", otsu), ("adaptive", adaptive), ("enhanced", enhanced_gray)]:
                try:
                    text = pytesseract.image_to_string(candidate, config="--oem 3 --psm 6")
                    tlen = len(text.strip())
                    logger.debug(f"OCR strategy '{label}' produced {tlen} chars")
                    if tlen > best_len:
                        best_len = tlen
                        best_image = candidate
                except Exception as exc:
                    logger.warning(f"OCR strategy '{label}' failed: {exc}")

            logger.info(f"Best OCR strategy produced {best_len} characters")
            return best_image

        except Exception as e:
            logger.error(f"Error preprocessing image for OCR: {e}")
            try:
                return cv2.cvtColor(
                    np.array(Image.open(io.BytesIO(image_bytes)).convert('RGB')),
                    cv2.COLOR_RGB2BGR,
                )
            except Exception:
                return None
    
    def _tesseract_extract(self, cv_image: np.ndarray) -> str:
        """Extract text from preprocessed image using OCR.

        Uses multiple PSM modes and picks the best result.
        No character whitelist — we want to capture ALL characters including
        numbers, punctuation, and special symbols that are commonly found in
        handwritten answer sheets.
        """
        best_text = ""
        configs = [
            "--oem 3 --psm 6",   # Uniform block of text
            "--oem 3 --psm 4",   # Assume a single column of text of variable sizes
            "--oem 3 --psm 3",   # Fully automatic page segmentation (no OSD)
        ]
        for cfg in configs:
            try:
                text = pytesseract.image_to_string(cv_image, config=cfg)
                text = text.strip()
                if len(text) > len(best_text):
                    best_text = text
            except Exception as e:
                logger.warning(f"Tesseract config '{cfg}' failed: {e}")
        return best_text
    
    async def extract_text_from_image_url(self, image_url: str) -> Optional[Dict[str, Any]]:
        logger.warning("extract_text_from_image_url not implemented without external OCR; provide bytes/base64 instead")
        return None
    
    async def extract_text_from_base64(self, base64_image: str) -> Optional[Dict[str, Any]]:
        try:
            logger.info("Processing OCR for base64 image (Tesseract)")
            image_bytes = self._decode_base64_to_bytes(base64_image)
            if image_bytes is None:
                return None
            pre = self._preprocess_for_ocr(image_bytes)
            if pre is None:
                return None
            text = self._tesseract_extract(pre)

            # Calculate real confidence from Tesseract
            confidence = self._compute_confidence(pre)

            logger.info(f"OCR extracted {len(text)} characters with confidence {confidence:.2f}")
            return {
                "text": text,
                "confidence": confidence,
            }
        except Exception as e:
            logger.error(f"Error extracting text from base64 image: {e}")
            return None

    def _compute_confidence(self, cv_image: np.ndarray) -> float:
        """Compute average per-character confidence from Tesseract."""
        try:
            data = pytesseract.image_to_data(cv_image, output_type=pytesseract.Output.DICT, config="--oem 3 --psm 6")
            confs = [int(c) for c in data.get("conf", []) if int(c) >= 0]
            if confs:
                return round(sum(confs) / len(confs) / 100.0, 2)
        except Exception:
            pass
        return 0.5  # fallback
    
    async def extract_text_from_file(self, image_path: str) -> Optional[Dict[str, Any]]:
        try:
            logger.info(f"Processing OCR for image file: {image_path}")
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            pre = self._preprocess_for_ocr(image_bytes)
            if pre is None:
                return None
            text = self._tesseract_extract(pre)
            confidence = self._compute_confidence(pre)
            return {"text": text, "confidence": confidence}
        except Exception as e:
            logger.error(f"Error extracting text from image file: {e}")
            return None
    
    async def extract_text_from_bytes(self, image_bytes: bytes, image_type: str = "jpeg") -> Optional[Dict[str, Any]]:
        try:
            logger.info("Processing OCR for image bytes (Tesseract)")
            pre = self._preprocess_for_ocr(image_bytes)
            if pre is None:
                return None
            text = self._tesseract_extract(pre)
            confidence = self._compute_confidence(pre)
            return {"text": text, "confidence": confidence}
        except Exception as e:
            logger.error(f"Error extracting text from image bytes: {e}")
            return None
    
    async def process_multiple_images(self, images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        try:
            logger.info(f"Processing {len(images)} images for OCR")
            results = []
            combined_text = []
            
            for i, image_data in enumerate(images):
                logger.info(f"Processing image {i+1}/{len(images)}")
                if "base64" in image_data:
                    result = await self.extract_text_from_base64(image_data["base64"])
                elif "bytes" in image_data:
                    result = await self.extract_text_from_bytes(image_data["bytes"], image_data.get("type", "jpeg"))
                elif "file_path" in image_data:
                    result = await self.extract_text_from_file(image_data["file_path"])
                else:
                    result = None
                if result:
                    result["image_index"] = i
                    result["image_id"] = image_data.get("id", f"image_{i}")
                    results.append(result)
                    combined_text.append(result.get("text", ""))
                else:
                    results.append({
                        "image_index": i,
                        "image_id": image_data.get("id", f"image_{i}"),
                        "text": "",
                        "confidence": 0.0,
                        "error": "Failed to process image"
                    })
            combined_result = {
                "combined_text": "\n\n".join([t for t in combined_text if t]),
                "total_images": len(images),
                "processed_images": len([r for r in results if r.get("text")]),
                "individual_results": results,
                "overall_confidence": sum(r.get("confidence", 0) for r in results) / len(results) if results else 0,
            }
            logger.info(f"Successfully processed {combined_result['processed_images']}/{combined_result['total_images']} images")
            return [combined_result]
        except Exception as e:
            logger.error(f"Error processing multiple images: {e}")
            return []
    
    def clean_ocr_text(self, text: str) -> str:
        """Light cleanup of OCR text.

        IMPORTANT: We intentionally do NOT replace '0' with 'O' or perform
        any digit-destroying transformations. Numbers are critical for grading.
        """
        if not text:
            return ""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        cleaned_text = '\n'.join(lines)
        # Only fix obviously broken pipe characters that should be 'l' or 'I'
        # Do NOT touch digits
        return cleaned_text
    
    def extract_answers_from_text(self, text: str, question_count: int = None) -> Dict[str, str]:
        try:
            if not text:
                return {}
            cleaned_text = self.clean_ocr_text(text)
            answers: Dict[str, str] = {}
            lines = cleaned_text.split('\n')
            current_question = None
            current_answer: List[str] = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.lower().startswith(('q', 'question')):
                    if current_question and current_answer:
                        answers[current_question] = ' '.join(current_answer).strip()
                    current_question = line.split()[0] if line.split() else None
                    current_answer = []
                    if ':' in line or '.' in line:
                        answer_part = line.split(':', 1)[-1].split('.', 1)[-1].strip()
                        if answer_part:
                            current_answer.append(answer_part)
                else:
                    if current_question:
                        current_answer.append(line)
            if current_question and current_answer:
                answers[current_question] = ' '.join(current_answer).strip()
            if not answers and question_count:
                for i in range(1, question_count + 1):
                    if i <= len(lines):
                        answers[f"Q{i}"] = lines[i-1]
            return answers
        except Exception as e:
            logger.error(f"Error extracting answers from text: {e}")
            return {}


# Global instance
ocr_service = OCRService()


def get_ocr_service() -> OCRService:
    return ocr_service
