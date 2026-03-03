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
        student_id: str,
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
            
            # Get paper details and answer key
            paper = await self._get_paper_details(paper_id)
            if not paper:
                raise ValueError("Paper not found")
            
            # Holistic grading: send combined OCR and answer key to LLM
            total_marks = paper.get("total_marks", sum(q.get("max_score", 5) for q in paper["questions"]))
            holistic = await self.llm_service.grade_paper_holistic(
                ocr_text_combined=combined_text,
                answer_key=paper.get("answer_key", {}),
                questions=paper.get("questions", []),
                total_marks=total_marks,
            )
            if not holistic:
                raise ValueError("Holistic grading failed")
            
            # Ensure database is initialized
            if self.db is None:
                self.db = await get_database()
            
            # Lookup student to populate required denormalized fields (e.g., student_name)
            student = await self.db.get_student(student_id)
            student_name = (student or {}).get("student_name") or (student or {}).get("name") or ""
            
            # Create submission record
            submission_data = {
                "paper_id": paper_id,
                "student_id": student_id,
                "student_name": student_name,
                "ocr_text": combined_text,
                "total_score": holistic["total_score"],
                "grade_percentage": holistic["grade_percentage"],
                "feedback": holistic["overall_feedback"],
                "grading_status": "completed",
                "images_processed": len(answer_sheet_images),
                "ocr_confidence": combined_result.get("overall_confidence", 0.75)
            }
            
            submission = await self.db.create_submission(submission_data)
            
            return {
                "submission_id": submission["id"],
                "total_score": holistic["total_score"],
                "grade_percentage": holistic["grade_percentage"],
                "feedback": holistic["overall_feedback"],
                "confidence_score": holistic.get("confidence", 0.75),
                "images_processed": len(answer_sheet_images),
                "ocr_confidence": combined_result.get("overall_confidence", 0.75)
            }
            
        except Exception as e:
            logger.error(f"Error processing multiple answer sheets: {e}")
            return None

    async def process_answer_sheet(
        self, 
        paper_id: str,
        student_id: str,
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
            
            # Get paper details and answer key
            paper = await self._get_paper_details(paper_id)
            if not paper:
                raise ValueError("Paper not found")
            
            # Holistic grading: single image text + answer key
            total_marks = paper.get("total_marks", sum(q.get("max_score", 5) for q in paper["questions"]))
            holistic = await self.llm_service.grade_paper_holistic(
                ocr_text_combined=ocr_text,
                answer_key=paper.get("answer_key", {}),
                questions=paper.get("questions", []),
                total_marks=total_marks,
            )
            if not holistic:
                raise ValueError("Holistic grading failed")
            
            # Ensure database is initialized
            if self.db is None:
                self.db = await get_database()
            
            # Lookup student to populate required denormalized fields (e.g., student_name)
            student = await self.db.get_student(student_id)
            student_name = (student or {}).get("student_name") or (student or {}).get("name") or ""
            
            # Create submission record
            submission_data = {
                "paper_id": paper_id,
                "student_id": student_id,
                "student_name": student_name,
                "ocr_text": ocr_text,
                "total_score": holistic["total_score"],
                "grade_percentage": holistic["grade_percentage"],
                "feedback": holistic["overall_feedback"],
                "grading_status": "completed",
                "images_processed": 1,
                "ocr_confidence": ocr_confidence
            }
            
            submission = await self.db.create_submission(submission_data)
            
            return {
                "submission_id": submission["id"],
                "total_score": holistic["total_score"],
                "grade_percentage": holistic["grade_percentage"],
                "feedback": holistic["overall_feedback"],
                "confidence_score": holistic.get("confidence", 0.75),
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
        """Preprocess image for better OCR results"""
        try:
            # Convert bytes to PIL Image
            pil_image = Image.open(io.BytesIO(image_data))
            
            # Convert to OpenCV format
            cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            
            # Convert to grayscale
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            
            # Apply Gaussian blur to reduce noise
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # Apply adaptive thresholding
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            
            # Morphological operations to clean up
            kernel = np.ones((1, 1), np.uint8)
            cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Error preprocessing image: {e}")
            return np.array(Image.open(io.BytesIO(image_data)))
    
    def _extract_text_from_image(self, image: np.ndarray) -> str:
        """Extract text from preprocessed image using OCR"""
        try:
            # Configure Tesseract for better handwriting recognition
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,!?()[]{}:;"\' '
            
            text = pytesseract.image_to_string(image, config=custom_config)
            return text.strip()
            
        except Exception as e:
            logger.error(f"Error extracting text from image: {e}")
            return ""
    
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

            # Ensure required fields exist
            questions = paper.get("questions", []) or []
            answer_key = paper.get("answer_key", {}) or {}
            total_marks = paper.get("total_marks")
            if total_marks is None:
                total_marks = sum(q.get("max_score", 5) for q in questions)

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
