"""
Answer Sheet Grading Service
Handles photo upload, OCR processing, and AI-powered grading
"""
import logging
import base64
import io
from typing import Dict, Any, Optional, List
from PIL import Image
import pytesseract
import cv2
import numpy as np

from services.llm_service import get_llm_service
from services.database import get_database
from services.ocr_service import get_ocr_service

logger = logging.getLogger(__name__)


class AnswerSheetGradingService:
    """Service for grading handwritten answer sheets"""
    
    def __init__(self):
        """Initialize answer sheet grading service"""
        self.llm_service = get_llm_service()
        self.db = None  # Will be initialized async
        self.ocr_service = get_ocr_service()
        logger.info("✅ Answer sheet grading service initialized")

    
    async def process_multiple_answer_sheets(
        self,
        paper_id: str,
        student_id: Optional[str],
        answer_sheet_images: List[str],  # List of base64 encoded images
        grading_mode: str = "auto",
        strictness: str = "medium"
    ) -> Optional[Dict[str, Any]]:
        """
        Process multiple uploaded answer sheet images and grade them
        """
        try:
            logger.info(f"Processing {len(answer_sheet_images)} answer sheets for paper {paper_id}, student {student_id}")
            
            # Prepare images for OCR processing
            images_data = []
            for i, image_base64 in enumerate(answer_sheet_images):
                images_data.append({
                    "id": f"page_{i+1}",
                    "base64": image_base64
                })
            
            # Process all images with OCR
            ocr_results = await self.ocr_service.process_multiple_images(images_data)
            
            if not ocr_results:
                raise ValueError("Failed to process any images")
            
            combined_result = ocr_results[0]  # combined OCR across pages
            combined_text = combined_result.get("combined_text", "")

            logger.info(f"OCR extracted {len(combined_text)} characters from {len(answer_sheet_images)} images")
            
            # Get paper details and answer key
            paper = await self._get_paper_details(paper_id)
            if not paper:
                raise ValueError("Paper not found")
            
            # Per-question grading: send combined OCR, questions, and answer key to the LLM.
            total_marks = self._resolve_total_marks(paper)
            grading_result = await self.llm_service.grade_paper_by_question(
                ocr_text_combined=combined_text,
                answer_key=paper.get("answer_key", {}),
                questions=paper.get("questions", []),
                total_marks=total_marks,
                strictness=strictness,
            )
            if not grading_result:
                raise ValueError("Per-question grading failed")
            
            # Ensure database is initialized
            if self.db is None:
                self.db = await get_database()
            
            # Lookup student to populate required denormalized fields (e.g., student_name)
            student_name = ""
            if student_id:
                student = await self.db.get_student(student_id)
                student_name = (student or {}).get("student_name") or (student or {}).get("name") or ""

            question_details = grading_result.get("question_details", [])
            stored_submission_data = self._build_stored_submission_data(
                grading_result=grading_result,
                total_marks=total_marks,
                question_details=question_details,
                ocr_confidence=combined_result.get("overall_confidence", 0.75),
                images_processed=len(answer_sheet_images),
                grading_mode=grading_mode,
                strictness=strictness,
            )

            # Create submission record
            submission_data = {
                "paper_id": paper_id,
                "student_id": student_id,
                "student_name": student_name,
                "ocr_text": combined_text,
                "submission_data": stored_submission_data,
                "total_score": grading_result["total_score"],
                "grade_percentage": grading_result["grade_percentage"],
                "feedback": grading_result["overall_feedback"],
                "grading_status": "completed",
                "images_processed": len(answer_sheet_images),
                "ocr_confidence": combined_result.get("overall_confidence", 0.75)
            }
            
            submission = await self.db.create_submission(submission_data)
            if not submission:
                raise ValueError("Failed to save graded submission")
            
            return {
                "submission_id": submission["id"],
                "total_score": grading_result["total_score"],
                "score": grading_result["total_score"],
                "max_score": total_marks,
                "total_marks": total_marks,
                "grade_percentage": grading_result["grade_percentage"],
                "grade": self._grade_label(grading_result["grade_percentage"]),
                "feedback": grading_result["overall_feedback"],
                "ai_feedback": grading_result["overall_feedback"],
                "question_scores": question_details,
                "question_details": question_details,
                "grading_details": question_details,
                "confidence_score": grading_result.get("confidence", 0.75),
                "images_processed": len(answer_sheet_images),
                "ocr_confidence": combined_result.get("overall_confidence", 0.75)
            }
            
        except Exception as e:
            logger.error(f"Error processing multiple answer sheets: {e}")
            return None

    async def process_answer_sheet(
        self, 
        paper_id: str,
        student_id: Optional[str],
        answer_sheet_image: str,  # Base64 encoded image
        grading_mode: str = "auto",
        strictness: str = "medium"
    ) -> Optional[Dict[str, Any]]:
        """
        Process uploaded answer sheet and grade it
        """
        try:
            logger.info(f"Processing answer sheet for paper {paper_id}, student {student_id}")
            
            # Extract text from single image
            ocr_result = await self.ocr_service.extract_text_from_base64(answer_sheet_image)
            if not ocr_result:
                raise ValueError("Failed to extract text from image")
            
            ocr_text = ocr_result["text"]
            ocr_confidence = ocr_result["confidence"]

            logger.info(f"OCR extracted {len(ocr_text)} characters with confidence {ocr_confidence:.2f}")
            
            # Get paper details and answer key
            paper = await self._get_paper_details(paper_id)
            if not paper:
                raise ValueError("Paper not found")
            
            # Per-question grading: single image OCR + answer key
            total_marks = self._resolve_total_marks(paper)
            grading_result = await self.llm_service.grade_paper_by_question(
                ocr_text_combined=ocr_text,
                answer_key=paper.get("answer_key", {}),
                questions=paper.get("questions", []),
                total_marks=total_marks,
                strictness=strictness,
            )
            if not grading_result:
                raise ValueError("Per-question grading failed")
            
            # Ensure database is initialized
            if self.db is None:
                self.db = await get_database()
            
            # Lookup student to populate required denormalized fields (e.g., student_name)
            student_name = ""
            if student_id:
                student = await self.db.get_student(student_id)
                student_name = (student or {}).get("student_name") or (student or {}).get("name") or ""

            question_details = grading_result.get("question_details", [])
            stored_submission_data = self._build_stored_submission_data(
                grading_result=grading_result,
                total_marks=total_marks,
                question_details=question_details,
                ocr_confidence=ocr_confidence,
                images_processed=1,
                grading_mode=grading_mode,
                strictness=strictness,
            )

            # Create submission record
            submission_data = {
                "paper_id": paper_id,
                "student_id": student_id,
                "student_name": student_name,
                "ocr_text": ocr_text,
                "submission_data": stored_submission_data,
                "total_score": grading_result["total_score"],
                "grade_percentage": grading_result["grade_percentage"],
                "feedback": grading_result["overall_feedback"],
                "grading_status": "completed",
                "images_processed": 1,
                "ocr_confidence": ocr_confidence
            }
            
            submission = await self.db.create_submission(submission_data)
            if not submission:
                raise ValueError("Failed to save graded submission")
            
            return {
                "submission_id": submission["id"],
                "total_score": grading_result["total_score"],
                "score": grading_result["total_score"],
                "max_score": total_marks,
                "total_marks": total_marks,
                "grade_percentage": grading_result["grade_percentage"],
                "grade": self._grade_label(grading_result["grade_percentage"]),
                "feedback": grading_result["overall_feedback"],
                "ai_feedback": grading_result["overall_feedback"],
                "question_scores": question_details,
                "question_details": question_details,
                "grading_details": question_details,
                "confidence_score": grading_result.get("confidence", 0.75),
                "images_processed": 1,
                "ocr_confidence": ocr_confidence
            }
            
        except Exception as e:
            logger.error(f"Error processing answer sheet: {e}")
            return None
    
    def _decode_base64_image(self, base64_string: str) -> Optional[bytes]:
        """Decode base64 image string"""
        try:
            # Remove data URL prefix if present
            if base64_string.startswith('data:image'):
                base64_string = base64_string.split(',')[1]
            
            return base64.b64decode(base64_string)
        except Exception as e:
            logger.error(f"Error decoding base64 image: {e}")
            return None
    
    def _preprocess_image(self, image_data: bytes) -> np.ndarray:
        """Preprocess image for better OCR results.

        Uses CLAHE contrast enhancement which preserves handwriting detail
        better than aggressive binarization.
        """
        try:
            pil_image = Image.open(io.BytesIO(image_data)).convert('RGB')

            # Upscale small images for better Tesseract accuracy
            w, h = pil_image.size
            if max(w, h) < 1500:
                scale = 1500 / max(w, h)
                pil_image = pil_image.resize(
                    (int(w * scale), int(h * scale)), Image.LANCZOS
                )

            cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)

            # CLAHE contrast enhancement - keeps more detail than thresholding
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)

            return enhanced

        except Exception as e:
            logger.error(f"Error preprocessing image: {e}")
            return np.array(Image.open(io.BytesIO(image_data)))
    
    def _extract_text_from_image(self, image: np.ndarray) -> str:
        """Extract text from preprocessed image using OCR.

        No character whitelist - we need ALL characters including digits,
        punctuation, and symbols that appear in handwritten answer sheets.
        """
        best_text = ""
        for psm in [6, 4, 3]:
            try:
                config = f"--oem 3 --psm {psm}"
                text = pytesseract.image_to_string(image, config=config)
                text = text.strip()
                if len(text) > len(best_text):
                    best_text = text
            except Exception as e:
                logger.warning(f"Tesseract PSM {psm} failed: {e}")
        return best_text
    
    async def _get_paper_details(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """Get paper details (questions, answer_key, total_marks) from database"""
        try:
            # Ensure database is initialized
            if self.db is None:
                self.db = await get_database()
            
            paper = await self.db.get_paper(paper_id)
            if not paper:
                logger.error(f"Paper {paper_id} not found in database")
                return None

            # Ensure required fields exist and are decoded
            import json as _json
            questions = paper.get("questions", []) or []
            if isinstance(questions, str):
                try:
                    questions = _json.loads(questions) or []
                except Exception:
                    questions = []
            answer_key = paper.get("answer_key", {}) or {}
            if isinstance(answer_key, str):
                try:
                    answer_key = _json.loads(answer_key) or {}
                except Exception:
                    answer_key = {}
            total_marks = paper.get("total_marks")
            if total_marks is None:
                total_marks = sum((q.get("max_score", 5) if isinstance(q, dict) else 0) for q in questions)

            # Warn if empty
            if not questions:
                logger.warning(f"Paper {paper_id} has no questions")
            if not answer_key:
                logger.warning(f"Paper {paper_id} has empty answer_key")

            return {
                "id": paper_id,
                "questions": questions,
                "answer_key": answer_key,
                "total_marks": total_marks,
            }
        except Exception as e:
            logger.error(f"Error getting paper details: {e}")
            return None

    def _resolve_total_marks(self, paper: Dict[str, Any]) -> float:
        """Resolve paper max marks from stored total or question marks."""
        total_marks = paper.get("total_marks")
        try:
            total_marks = float(total_marks or 0)
        except (TypeError, ValueError):
            total_marks = 0.0

        if total_marks > 0:
            return total_marks

        total = 0.0
        for question in paper.get("questions", []) or []:
            if not isinstance(question, dict):
                continue
            marks = question.get("max_marks") or question.get("max_score") or question.get("marks") or 0
            try:
                total += float(marks or 0)
            except (TypeError, ValueError):
                continue
        return total or 100.0

    def _build_stored_submission_data(
        self,
        grading_result: Dict[str, Any],
        total_marks: float,
        question_details: List[Dict[str, Any]],
        ocr_confidence: float,
        images_processed: int,
        grading_mode: str,
        strictness: str,
    ) -> Dict[str, Any]:
        """Build the JSON blob used by serializers and result pages."""
        return {
            "score": grading_result.get("total_score", 0),
            "total_score": grading_result.get("total_score", 0),
            "max_score": total_marks,
            "total_marks": total_marks,
            "grade_percentage": grading_result.get("grade_percentage", 0),
            "grade": self._grade_label(grading_result.get("grade_percentage", 0)),
            "feedback": grading_result.get("overall_feedback", ""),
            "ai_feedback": grading_result.get("overall_feedback", ""),
            "question_details": question_details,
            "grading_details": question_details,
            "ocr_confidence": ocr_confidence,
            "images_processed": images_processed,
            "grading_mode": grading_mode,
            "strictness": strictness,
            "grading_method": "llm_per_question",
            "confidence_score": grading_result.get("confidence", 0.75),
        }

    def _grade_label(self, percentage: float) -> str:
        """Convert a percentage into the label used by the frontend."""
        try:
            pct = float(percentage or 0)
        except (TypeError, ValueError):
            pct = 0.0
        if pct >= 90:
            return "A+"
        if pct >= 80:
            return "A"
        if pct >= 70:
            return "B"
        if pct >= 60:
            return "C"
        if pct >= 50:
            return "D"
        return "F"
    
    def _parse_student_answers(self, ocr_text: str, questions: List[Dict[str, Any]]) -> Dict[str, str]:
        """Parse student answers from OCR text"""
        try:
            # Use OCR service's answer extraction method
            extracted_answers = self.ocr_service.extract_answers_from_text(ocr_text, len(questions))
            
            # Map extracted answers to question IDs
            answers = {}
            for i, question in enumerate(questions):
                question_id = question["id"]
                
                # Try to find answer by question number or ID
                question_key = f"Q{i+1}"
                if question_key in extracted_answers:
                    answers[question_id] = extracted_answers[question_key]
                elif question_id in extracted_answers:
                    answers[question_id] = extracted_answers[question_id]
                else:
                    # Fallback: try to extract from lines
                    lines = ocr_text.split('\n')
                    if i < len(lines):
                        answers[question_id] = lines[i].strip()
                    else:
                        answers[question_id] = ""
            
            return answers
            
        except Exception as e:
            logger.error(f"Error parsing student answers: {e}")
            return {}
    
    async def _grade_answers(
        self,
        questions: List[Dict[str, Any]],
        answer_key: Dict[str, str],
        student_answers: Dict[str, str],
        grading_mode: str,
        strictness: str
    ) -> Dict[str, Any]:
        """Grade student answers using AI"""
        try:
            total_score = 0
            max_total_score = sum(q.get("max_score", 5) for q in questions)
            detailed_results = []
            
            for question in questions:
                question_id = question["id"]
                question_text = question["question_text"]
                question_type = question["question_type"]
                max_score = question.get("max_score", 5)
                
                student_answer = student_answers.get(question_id, "")
                correct_answer = answer_key.get(question_id, "")
                
                # Grade based on question type
                if question_type == "mcq":
                    score, feedback = self._grade_mcq(student_answer, correct_answer, max_score)
                elif question_type == "true_false":
                    score, feedback = self._grade_true_false(student_answer, correct_answer, max_score)
                else:
                    # Use AI for open-ended questions
                    grade_result = await self.llm_service.grade_answer(
                        question_text, correct_answer, student_answer, question_type
                    )
                    score = grade_result.get("score", 0) * max_score / 100
                    feedback = grade_result.get("feedback", "No feedback available")
                
                total_score += score
                
                detailed_results.append({
                    "question_id": question_id,
                    "question_text": question_text,
                    "student_answer": student_answer,
                    "correct_answer": correct_answer,
                    "score": score,
                    "max_score": max_score,
                    "feedback": feedback
                })
            
            grade_percentage = (total_score / max_total_score) * 100 if max_total_score > 0 else 0
            
            # Generate overall feedback
            overall_feedback = await self._generate_overall_feedback(
                grade_percentage, detailed_results, strictness
            )
            
            return {
                "total_score": total_score,
                "grade_percentage": grade_percentage,
                "overall_feedback": overall_feedback,
                "detailed_results": detailed_results,
                "confidence_score": 0.85  # Placeholder confidence score
            }
            
        except Exception as e:
            logger.error(f"Error grading answers: {e}")
            return {
                "total_score": 0,
                "grade_percentage": 0,
                "overall_feedback": "Error occurred during grading",
                "detailed_results": [],
                "confidence_score": 0.0
            }
    
    def _grade_mcq(self, student_answer: str, correct_answer: str, max_score: int) -> tuple:
        """Grade multiple choice question"""
        student_clean = student_answer.strip().upper()
        correct_clean = correct_answer.strip().upper()
        
        if student_clean == correct_clean:
            return max_score, "Correct answer!"
        else:
            return 0, f"Incorrect. The correct answer is {correct_answer}"
    
    def _grade_true_false(self, student_answer: str, correct_answer: str, max_score: int) -> tuple:
        """Grade true/false question"""
        student_clean = student_answer.strip().upper()
        correct_clean = correct_answer.strip().upper()
        
        if student_clean == correct_clean:
            return max_score, "Correct!"
        else:
            return 0, f"Incorrect. The correct answer is {correct_answer}"
    
    async def _generate_overall_feedback(
        self, 
        grade_percentage: float, 
        detailed_results: List[Dict[str, Any]], 
        strictness: str
    ) -> str:
        """Generate overall feedback for the student"""
        try:
            if grade_percentage >= 90:
                return "Excellent work! You have a strong understanding of the material."
            elif grade_percentage >= 80:
                return "Good job! You understand most of the concepts well."
            elif grade_percentage >= 70:
                return "Satisfactory work. Review the areas where you lost points."
            elif grade_percentage >= 60:
                return "You're on the right track, but need more practice in several areas."
            else:
                return "Please review the material and consider seeking additional help."
                
        except Exception as e:
            logger.error(f"Error generating overall feedback: {e}")
            return "Feedback generation error occurred."


# Global instance
answer_sheet_grading_service = AnswerSheetGradingService()


def get_answer_sheet_grading_service() -> AnswerSheetGradingService:
    """Get answer sheet grading service instance"""
    return answer_sheet_grading_service
