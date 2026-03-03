"""
Groq LLM Service — fast, free inference via Groq Cloud.
Default model: llama-3.3-70b-versatile (best free model on Groq)
"""
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional
from groq import AsyncGroq
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    """Service for interacting with Groq LLM API"""

    def __init__(self):
        """Initialize Groq async client"""
        try:
            self.model_name = settings.groq_llm_model
            self.client = AsyncGroq(api_key=settings.groq_api_key)
            logger.info(f"✅ Groq LLM service initialized — model: {self.model_name}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Groq LLM service: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal helper: single unified LLM call
    # ------------------------------------------------------------------

    async def _chat(self, prompt: str, max_tokens: int = 2048) -> Optional[str]:
        """Send a prompt to Groq and return the text response."""
        try:
            resp = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return None
    
    async def generate_answer(
        self,
        question: str,
        context: List[str],
        question_type: str = "general"
    ) -> Optional[Dict[str, Any]]:
        """Generate answer using RAG context"""
        try:
            context_text = "\n\n".join(context) if context else ""
            prompt = self._create_rag_prompt(question, context_text, question_type)
            text = await self._chat(prompt)
            if not text:
                logger.warning("Empty response from LLM")
                return None
            return {
                "answer": text.strip(),
                "sources": self._extract_sources(context),
                "confidence": self._calculate_confidence(text, context_text)
            }
        except Exception as e:
            logger.error(f"Error generating answer: {e}")
            return None
    
    async def generate_questions(
        self,
        content: str,
        question_count: int = 5,
        question_types: List[str] = None,
        difficulty_level: str = "medium"
    ) -> Optional[List[Dict[str, Any]]]:
        """Generate questions from content"""
        try:
            if question_types is None:
                question_types = ["mcq", "short_answer", "essay"]
            prompt = self._create_question_generation_prompt(
                content, question_count, question_types, difficulty_level
            )
            text = await self._chat(prompt)
            if not text:
                logger.warning("Empty response from LLM for question generation")
                return None
            return self._parse_generated_questions(text)
        except Exception as e:
            logger.error(f"Error generating questions: {e}")
            return None
    
    async def generate_questions_from_rag_content(
        self,
        organized_content: Dict[str, List[str]],
        question_count: int = 5,
        question_types: List[str] = None,
        difficulty_level: str = "medium",
        subject_id: str = None,
        question_type_counts: Dict[str, int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Generate questions from RAG-organized content with timeout handling"""
        try:
            if question_types is None:
                question_types = ["mcq", "short_answer", "essay"]
            
            # Limit content to avoid timeouts - take only first few chunks from each category
            max_chunks_per_category = 3  # Reduced from default
            limited_content = {}
            
            for category, chunks in organized_content.items():
                if chunks:
                    # Take only first few chunks and limit their length
                    limited_chunks = []
                    for chunk in chunks[:max_chunks_per_category]:
                        # Limit each chunk to 500 characters to avoid token limits
                        limited_chunk = chunk[:500] + "..." if len(chunk) > 500 else chunk
                        limited_chunks.append(limited_chunk)
                    limited_content[category] = limited_chunks
            
            # Create content sections with limited content
            content_sections = []
            
            if limited_content.get("definitions"):
                content_sections.append("DEFINITIONS:\n" + "\n\n".join(limited_content["definitions"]))
            
            if limited_content.get("key_concepts"):
                content_sections.append("KEY CONCEPTS:\n" + "\n\n".join(limited_content["key_concepts"]))
            
            if limited_content.get("examples"):
                content_sections.append("EXAMPLES:\n" + "\n\n".join(limited_content["examples"]))
            
            if limited_content.get("main_content"):
                content_sections.append("MAIN CONTENT:\n" + "\n\n".join(limited_content["main_content"]))
            
            combined_content = "\n\n".join(content_sections)
            
            # Limit total content length to avoid timeouts
            if len(combined_content) > 3000:
                combined_content = combined_content[:3000] + "\n\n[Content truncated for processing...]"
                logger.warning(f"Content truncated to 3000 characters to avoid timeout")
            
            logger.info(f"Sending {len(combined_content)} characters to LLM for question generation")

            prompt = self._create_rag_question_generation_prompt(
                combined_content, question_count, question_types, difficulty_level, subject_id,
                question_type_counts=question_type_counts
            )

            text: Optional[str] = None
            max_retries = 2
            for attempt in range(max_retries):
                logger.info(f"Attempting question generation (attempt {attempt + 1}/{max_retries})")
                text = await self._chat(prompt)
                if text:
                    break
                logger.warning(f"Empty response on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)

            if not text:
                logger.warning("Empty response from LLM for RAG question generation")
                return None

            questions = self._parse_generated_questions(text)
            
            # Add metadata about content sources
            for question in questions:
                question["content_categories"] = list(organized_content.keys())
                question["rag_generated"] = True
            
            logger.info(f"Successfully generated {len(questions)} questions")
            return questions
            
        except Exception as e:
            logger.error(f"Error generating questions from RAG content: {e}")
            return None
    
    async def process_question_sheet_text(
        self,
        text: str,
        subject_id: str = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Process OCR text from question sheet to extract structured questions"""
        try:
            prompt = self._create_question_sheet_processing_prompt(text, subject_id)
            resp_text = await self._chat(prompt)
            if not resp_text:
                logger.warning("Empty response from LLM for question sheet processing")
                return None
            questions = self._parse_generated_questions(resp_text)
            for question in questions:
                question["source"] = "question_sheet"
                question["extracted_from_ocr"] = True
            return questions
        except Exception as e:
            logger.error(f"Error processing question sheet text: {e}")
            return None
    
    async def grade_answer(
        self,
        question: str,
        correct_answer: str,
        student_answer: str,
        question_type: str = "short_answer"
    ) -> Optional[Dict[str, Any]]:
        """Grade student answer"""
        try:
            prompt = self._create_grading_prompt(
                question, correct_answer, student_answer, question_type
            )
            resp_text = await self._chat(prompt)
            if not resp_text:
                logger.warning("Empty response from LLM for grading")
                return None
            return self._parse_grading_result(resp_text)
        except Exception as e:
            logger.error(f"Error grading answer: {e}")
            return None

    async def grade_paper_holistic(
        self,
        ocr_text_combined: str,
        answer_key: Dict[str, Any],
        questions: List[Dict[str, Any]] | None = None,
        total_marks: float | int = 100,
    ) -> Optional[Dict[str, Any]]:
        """Holistically grade a full paper using combined OCR text and the paper's answer key.

        Returns a dict with total_score, grade_percentage, overall_feedback, confidence.
        """
        try:
            def slice_ocr(text: str, head: int, tail: int) -> str:
                if not text:
                    return ""
                text = text.strip()
                if len(text) <= head + tail + 100:
                    return text
                return text[:head] + "\n... [OCR content truncated] ...\n" + text[-tail:]

            ak_json = json.dumps(answer_key or {}, ensure_ascii=False)
            qs_json = json.dumps(questions or [], ensure_ascii=False)

            # Retry with progressively smaller OCR slices
            for head, tail in [(4000, 2000), (3000, 1000), (2000, 500)]:
                ocr_sliced = slice_ocr(ocr_text_combined, head, tail)
                prompt = f"""You are an experienced examiner. Grade the student's entire paper holistically.

STUDENT_ANSWERS_TEXT (raw OCR, possibly noisy):
{ocr_sliced}

ANSWER_KEY (JSON keyed by question id):
{ak_json}

QUESTIONS (JSON array; may include question_text, type, max_score):
{qs_json}

INSTRUCTIONS:
- Infer the student's answers from the OCR text.
- Compare with the answer key at a high level.
- Award a single total score out of {total_marks} without per-question breakdowns.
- Provide 2-4 lines of overall feedback only.
- Be strict but fair; ignore layout headers and non-answer text.

OUTPUT STRICT JSON ONLY:
{{
  "total_score": <number>,
  "grade_percentage": <0-100 number>,
  "overall_feedback": "<short feedback>",
  "confidence": <0.0-1.0 number>
}}"""

                resp_text = await self._chat(prompt, max_tokens=512)
                if not resp_text:
                    continue

                start_idx = resp_text.find('{')
                end_idx = resp_text.rfind('}') + 1
                if start_idx == -1 or end_idx == 0:
                    continue
                try:
                    result = json.loads(resp_text[start_idx:end_idx])
                except Exception:
                    continue

                return {
                    "total_score": float(result.get("total_score", 0)),
                    "grade_percentage": float(result.get("grade_percentage", 0)),
                    "overall_feedback": str(result.get("overall_feedback", "")),
                    "confidence": float(result.get("confidence", 0.75)),
                }

            logger.error("Holistic grading failed after all retries")
            return None
        except Exception as e:
            logger.error(f"Error in holistic grading: {e}")
            return None
    
    def _create_rag_prompt(self, question: str, context: str, question_type: str) -> str:
        """Create prompt for RAG answer generation"""
        base_prompt = f"""
You are an expert educational assistant. Answer the following question based on the provided context.

Context:
{context}

Question: {question}

Instructions:
1. Provide a clear, accurate, and comprehensive answer
2. Base your answer strictly on the provided context
3. If the context doesn't contain enough information, say so
4. Include relevant examples or explanations when helpful
5. Structure your answer clearly with proper formatting

Answer:
"""
        
        # Add specific instructions based on question type
        if question_type == "explanation":
            base_prompt += "\nFocus on providing a detailed explanation with examples."
        elif question_type == "definition":
            base_prompt += "\nProvide a clear, concise definition."
        elif question_type == "comparison":
            base_prompt += "\nCompare and contrast the relevant concepts."
        
        return base_prompt
    
    def _create_question_generation_prompt(
        self, 
        content: str, 
        count: int, 
        types: List[str], 
        difficulty: str
    ) -> str:
        """Create prompt for question generation"""
        return f"""
You are an expert educator creating assessment questions. Generate {count} questions based on the following content.

Content:
{content}

Requirements:
- Question types: {', '.join(types)}
- Difficulty level: {difficulty}
- Ensure questions test understanding, not just memorization
- Include answer keys for each question
- For MCQs, provide 4 options with only one correct answer
- For essay questions, provide a rubric

Format your response as JSON with the following structure:
{{
    "questions": [
        {{
            "question_text": "Question here",
            "question_type": "mcq|short_answer|essay|true_false",
            "difficulty_level": 1-5,
            "options": ["A", "B", "C", "D"] (for MCQs only),
            "correct_answer": "Correct answer",
            "explanation": "Why this is correct",
            "rubric": {{}} (for essay questions)
        }}
    ]
}}

Generate the questions now:
"""
    
    def _create_rag_question_generation_prompt(
        self,
        content: str,
        count: int,
        types: List[str],
        difficulty: str,
        subject_id: str = None,
        question_type_counts: Dict[str, int] = None
    ) -> str:
        """Create simplified prompt for RAG-based question generation"""
        if question_type_counts:
            type_spec = ", ".join(
                f"exactly {v} {k.replace('_', ' ')}" for k, v in question_type_counts.items() if v > 0
            )
            count_line = f"Generate {count} questions total: {type_spec}."
        else:
            count_line = f"Create {count} questions from this content. Types: {', '.join(types)}."

        return f"""
{count_line} Difficulty: {difficulty}.

CONTENT:
{content}

REQUIREMENTS:
- Base questions strictly on the content above
- For MCQ: provide exactly 4 options (plain text, no letter prefix) with 1 correct answer
- Include correct answers for all question types
- For essay/long_answer: provide a model answer
- Make questions clear and specific
- Use difficulty: {difficulty}

FORMAT (return ONLY valid JSON, no extra text):
{{
    "questions": [
        {{
            "question_text": "Your question here?",
            "question_type": "mcq|short_answer|long_answer|essay|true_false|fill_blank",
            "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
            "correct_answer": "Exact correct option text or answer",
            "explanation": "Brief explanation",
            "marks": 5
        }}
    ]
}}

Generate {count} questions now:
"""
    
    def _create_question_sheet_processing_prompt(
        self,
        text: str,
        subject_id: str = None
    ) -> str:
        """Create prompt for processing question sheet OCR text"""
        return f"""
You are an expert educator processing a question sheet that was extracted using OCR. 
Extract and structure the questions from the following text, which may contain formatting issues or OCR errors.

OCR Text from Question Sheet:
{text}

Instructions:
1. Identify all questions in the text
2. Correct any OCR errors or formatting issues
3. Structure each question properly
4. Determine the question type (MCQ, short answer, essay, true/false)
5. Extract or infer the correct answers
6. Provide appropriate options for MCQs
7. Estimate difficulty level (1-5)
8. Add explanations where possible

Format your response as JSON with the following structure:
{{
    "questions": [
        {{
            "question_text": "Corrected and properly formatted question",
            "question_type": "mcq|short_answer|essay|true_false",
            "difficulty_level": 1-5,
            "options": ["A", "B", "C", "D"] (for MCQs only),
            "correct_answer": "Correct answer",
            "explanation": "Why this is correct",
            "max_score": 5,
            "ocr_corrections": "What was corrected from the original text"
        }}
    ]
}}

Process the question sheet now:
"""
    
    def _create_grading_prompt(
        self, 
        question: str, 
        correct_answer: str, 
        student_answer: str,
        question_type: str
    ) -> str:
        """Create prompt for grading"""
        return f"""
You are an expert educator grading student responses. Grade the following answer.

Question: {question}
Correct Answer: {correct_answer}
Student Answer: {student_answer}
Question Type: {question_type}

Instructions:
1. Grade the answer on a scale of 0-100
2. Provide specific feedback
3. Identify what the student did well
4. Suggest areas for improvement
5. Be encouraging but honest

Format your response as JSON:
{{
    "score": 0-100,
    "feedback": "Detailed feedback here",
    "strengths": ["What student did well"],
    "improvements": ["Areas to improve"],
    "confidence": 0.0-1.0
}}

Grade the answer:
"""
    
    def _extract_sources(self, context: List[str]) -> List[str]:
        """Extract source information from context"""
        sources = []
        for i, chunk in enumerate(context):
            # This is a simplified extraction - in practice, you'd want more sophisticated source tracking
            sources.append(f"Source {i+1}: {chunk[:100]}...")
        return sources
    
    def _calculate_confidence(self, answer: str, context: str) -> float:
        """Calculate confidence score for the answer"""
        # Simple confidence calculation based on answer length and context relevance
        if not answer or not context:
            return 0.0
        
        # Basic heuristic - in practice, you'd want more sophisticated confidence scoring
        answer_length = len(answer.split())
        context_length = len(context.split())
        
        if answer_length < 10:
            return 0.3
        elif answer_length < 50:
            return 0.7
        else:
            return 0.9
    
    def _parse_generated_questions(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse generated questions from LLM response with enhanced structure"""
        try:
            import json
            # Try to extract JSON from response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            
            if start_idx != -1 and end_idx != -1:
                json_str = response_text[start_idx:end_idx]
                data = json.loads(json_str)
                
                questions = data.get('questions', [])
                
                # Enhance questions with additional metadata
                for i, question in enumerate(questions):
                    # Ensure required fields exist
                    if 'id' not in question:
                        question['id'] = f"q{i+1}"
                    if 'question_number' not in question:
                        question['question_number'] = i + 1
                    # Normalize marks: support both 'marks' and 'max_score' fields
                    if 'marks' not in question:
                        question['marks'] = question.get('max_score', 5)
                    if 'max_score' not in question:
                        question['max_score'] = question.get('marks', 5)
                    if 'time_estimate' not in question:
                        question['time_estimate'] = "2-3 minutes"
                    if 'printable_format' not in question:
                        question['printable_format'] = self._format_question_for_print(question)
                    # Add difficulty string if not present
                    if 'difficulty' not in question:
                        question['difficulty'] = 'medium'
                    # Ensure question text is properly formatted
                    if 'question_text' in question:
                        question['question_text'] = self._clean_question_text(question['question_text'])
                
                return questions
        except Exception as e:
            logger.error(f"Error parsing generated questions: {e}")
        
        # Fallback: return empty list
        return []
    
    def _format_question_for_print(self, question: Dict[str, Any]) -> str:
        """Format question for printable output"""
        q_num = question.get('question_number', 1)
        q_text = question.get('question_text', '')
        q_type = question.get('question_type', 'short_answer')
        max_score = question.get('max_score', 5)
        
        formatted = f"Q{q_num}. {q_text} [{max_score} marks]\n"
        
        if q_type == 'mcq' and 'options' in question:
            options = question['options']
            for i, option in enumerate(options):
                letter = chr(65 + i)  # A, B, C, D
                formatted += f"   {letter}) {option}\n"
        
        return formatted
    
    def _clean_question_text(self, text: str) -> str:
        """Clean and format question text"""
        if not text:
            return ""
        
        # Remove extra whitespace
        text = ' '.join(text.split())
        
        # Ensure proper capitalization
        if text and not text[0].isupper():
            text = text[0].upper() + text[1:]
        
        # Ensure question ends with proper punctuation
        if text and not text.endswith(('?', '.', '!')):
            text += '?'
        
        return text
    
    def _parse_grading_result(self, response_text: str) -> Dict[str, Any]:
        """Parse grading result from LLM response"""
        try:
            import json
            # Try to extract JSON from response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            
            if start_idx != -1 and end_idx != -1:
                json_str = response_text[start_idx:end_idx]
                data = json.loads(json_str)
                return data
        except Exception as e:
            logger.error(f"Error parsing grading result: {e}")
        
        # Fallback: return default grading result
        return {
            "score": 0,
            "feedback": "Unable to grade this answer",
            "strengths": [],
            "improvements": ["Please provide a more detailed answer"],
            "confidence": 0.0
        }


# Global singleton
llm_service = LLMService()


def get_llm_service() -> LLMService:
    """Return the global LLM service instance."""
    return llm_service
