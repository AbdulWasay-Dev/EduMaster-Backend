"""
Groq LLM Service — fast, free inference via Groq Cloud.
Default model: llama-3.3-70b-versatile (best free model on Groq)
"""
import json
import logging
import asyncio
import re
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
            self.api_keys = settings.all_groq_keys
            if not self.api_keys:
                self.api_keys = [settings.groq_api_key]
            self.current_key_idx = 0
            self.client = AsyncGroq(api_key=self.api_keys[self.current_key_idx])
            logger.info(f"✅ Groq LLM service initialized — model: {self.model_name}, loaded {len(self.api_keys)} keys")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Groq LLM service: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal helper: single unified LLM call
    # ------------------------------------------------------------------

    async def _chat(self, prompt: str, max_tokens: int = 2048) -> Optional[str]:
        """Send a prompt to Groq and return the text response."""
        attempts = 0
        max_attempts = len(self.api_keys)
        
        while attempts < max_attempts:
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return resp.choices[0].message.content
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Groq API error on key index {self.current_key_idx}: {error_msg}")
                # Check for rate limit error (429)
                if "429" in error_msg or "rate_limit_exceeded" in error_msg.lower():
                    attempts += 1
                    if attempts < max_attempts:
                        self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
                        logger.warning(f"Rate limit hit. Switching to Groq API key index {self.current_key_idx}")
                        self.client = AsyncGroq(api_key=self.api_keys[self.current_key_idx])
                        continue
                return None
        logger.error("All Groq API keys exhausted or failed.")
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

    async def generate_general_response(self, question: str) -> Optional[Dict[str, Any]]:
        """Generate a normal LLM response without document retrieval."""
        try:
            prompt = f"""
You are EduMaster AI, a helpful assistant for teachers. Answer the teacher's question directly.

Instructions:
1. Be clear, practical, and concise.
2. You may use general knowledge because no uploaded document context was selected.
3. If the teacher asks for lesson ideas, explanations, examples, rubrics, or classroom wording, make the answer ready to use.
4. Do not claim that your answer came from uploaded documents.

Question: {question}

Answer:
"""
            text = await self._chat(prompt)
            if not text:
                logger.warning("Empty response from LLM for general chat")
                return None
            return {
                "answer": text.strip(),
                "sources": [],
                "confidence": 0.75,
            }
        except Exception as e:
            logger.error(f"Error generating general response: {e}")
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

    async def grade_paper_by_question(
        self,
        ocr_text_combined: str,
        answer_key: Dict[str, Any],
        questions: List[Dict[str, Any]] | None = None,
        total_marks: float | int = 100,
        strictness: str = "medium",
    ) -> Optional[Dict[str, Any]]:
        """Grade a full OCR'd paper question-by-question against the answer key."""
        try:
            normalized_questions = self._build_grading_questions(questions or [], answer_key or {})
            if not normalized_questions:
                logger.warning("No questions available for per-question grading")
                return None

            resolved_total = float(total_marks or 0)
            if resolved_total <= 0:
                resolved_total = sum(float(q.get("max_marks", 0)) for q in normalized_questions)
            if resolved_total <= 0:
                resolved_total = 100.0

            def slice_ocr(text: str, head: int, tail: int) -> str:
                if not text:
                    return ""
                text = text.strip()
                if len(text) <= head + tail + 100:
                    return text
                return text[:head] + "\n... [OCR content truncated] ...\n" + text[-tail:]

            q_json = json.dumps(normalized_questions, ensure_ascii=False)

            for head, tail in [(7000, 3000), (4500, 1500), (3000, 800)]:
                ocr_sliced = slice_ocr(ocr_text_combined, head, tail)
                prompt = f"""You are an experienced, fair examiner grading a student's scanned answer sheet.

The student wrote answers BY HAND and the text below was extracted via OCR.
OCR is inherently noisy: expect misspellings, missing spaces, merged lines,
number–letter confusion (0/O, 1/l/I, 5/S), and formatting artifacts.
Do your best to understand what the student actually wrote.

STUDENT_ANSWERS_TEXT (raw OCR — may be noisy):
{ocr_sliced}

QUESTIONS_AND_ANSWER_KEY_JSON:
{q_json}

GRADING_RULES — follow these EXACTLY:
1. Grade EVERY question listed in QUESTIONS_AND_ANSWER_KEY_JSON independently.
2. For each question, search the STUDENT_ANSWERS_TEXT for the student's
   response by looking for question numbers ("1.", "Q1", "1)", etc.),
   keywords from the question, and nearby handwritten content.
3. OCR may merge questions or split them across lines. Use context and
   surrounding text to determine where one answer ends and the next begins.
4. Do NOT copy, paraphrase, or infer a student answer from the answer key.
5. If the student genuinely attempted a question, set "attempted": true
   even if their answer is wrong.
6. If a question has NO student response anywhere in the OCR text,
   set student_answer to "", evidence_quote to "", attempted to false,
   and award 0 marks.
7. For MCQ / true-false: accept clear equivalent answers ("A", "a",
   option text, or similar) even through OCR noise.
8. For short-answer / essay / fill-blank: award partial credit based on
   how close the student's response is to the correct answer.
9. For every non-zero score, provide a short evidence_quote — a snippet
   from STUDENT_ANSWERS_TEXT showing what the student wrote.
10. Strictness level: {strictness}.
11. Compute the total from summing per-question marks_awarded.
    The paper is out of {resolved_total} marks.
12. Keep ai_comment short (one sentence).

OUTPUT STRICT JSON ONLY (no markdown, no explanation outside JSON):
{{
  "question_details": [
    {{
      "question_id": "<same id from input>",
      "student_answer": "<what the student wrote, extracted from OCR, or empty>",
      "evidence_quote": "<short snippet from STUDENT_ANSWERS_TEXT, or empty>",
      "marks_awarded": <number between 0 and max_marks>,
      "max_marks": <number>,
      "is_correct": <true|false>,
      "attempted": <true|false>,
      "ai_comment": "<one-sentence reason>",
      "confidence": <0.0-1.0>
    }}
  ],
  "overall_feedback": "<2-4 sentence summary>",
  "confidence": <0.0-1.0>
}}"""

                resp_text = await self._chat(prompt, max_tokens=4096)
                if not resp_text:
                    continue

                parsed = self._parse_question_grading_response(
                    resp_text=resp_text,
                    questions=normalized_questions,
                    total_marks=resolved_total,
                    ocr_text=ocr_text_combined,
                )
                if parsed:
                    return parsed

            logger.error("Per-question grading failed after all retries")
            return None
        except Exception as e:
            logger.error(f"Error in per-question grading: {e}")
            return None

    def _build_grading_questions(
        self,
        questions: List[Dict[str, Any]],
        answer_key: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Normalize stored paper questions into the compact shape sent for grading."""
        normalized: List[Dict[str, Any]] = []

        for index, question in enumerate(questions or [], start=1):
            if not isinstance(question, dict):
                continue

            question_id = str(question.get("id") or f"q{index}")
            max_marks = (
                question.get("max_marks")
                or question.get("max_score")
                or question.get("marks")
                or 1
            )
            try:
                max_marks = float(max_marks)
            except (TypeError, ValueError):
                max_marks = 1.0

            correct_answer = (
                answer_key.get(question_id)
                or answer_key.get(str(index))
                or answer_key.get(f"q{index}")
                or question.get("correct_answer")
                or ""
            )

            normalized.append({
                "question_id": question_id,
                "question_number": question.get("question_number") or index,
                "question_text": question.get("question_text") or question.get("text") or "",
                "question_type": question.get("question_type") or question.get("type") or "short_answer",
                "max_marks": max_marks,
                "correct_answer": correct_answer,
                "options": question.get("options") or [],
            })

        if normalized:
            return normalized

        for index, (question_id, correct_answer) in enumerate((answer_key or {}).items(), start=1):
            normalized.append({
                "question_id": str(question_id),
                "question_number": index,
                "question_text": "",
                "question_type": "short_answer",
                "max_marks": 1.0,
                "correct_answer": correct_answer,
                "options": [],
            })

        return normalized

    def _parse_question_grading_response(
        self,
        resp_text: str,
        questions: List[Dict[str, Any]],
        total_marks: float,
        ocr_text: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Parse and normalize per-question grading JSON from the LLM.

        Important: We trust the LLM's grading judgment more than rigid
        string-matching evidence validation.  OCR text is inherently noisy
        and fuzzy matching frequently produces false negatives, causing
        legitimate marks to be zeroed out.  Instead we only zero a score
        when the LLM itself returned no student_answer AND no evidence.
        """
        try:
            start_idx = resp_text.find('{')
            end_idx = resp_text.rfind('}') + 1
            if start_idx == -1 or end_idx == 0:
                return None

            data = json.loads(resp_text[start_idx:end_idx])
            raw_details = data.get("question_details") or data.get("grading_details") or []
            if not isinstance(raw_details, list):
                return None

            details_by_id = {
                str(item.get("question_id")): item
                for item in raw_details
                if isinstance(item, dict) and item.get("question_id") is not None
            }

            normalized_details: List[Dict[str, Any]] = []
            total_score = 0.0

            for question in questions:
                question_id = str(question["question_id"])
                raw = details_by_id.get(question_id, {})
                max_marks = float(question.get("max_marks", 0) or 0)

                marks_awarded = (
                    raw.get("marks_awarded")
                    if isinstance(raw, dict) else 0
                )
                if marks_awarded is None and isinstance(raw, dict):
                    marks_awarded = raw.get("score", raw.get("scored_marks", 0))
                try:
                    marks_awarded = float(marks_awarded or 0)
                except (TypeError, ValueError):
                    marks_awarded = 0.0
                student_answer = str(raw.get("student_answer") or raw.get("student_answer_text") or "") if isinstance(raw, dict) else ""
                evidence_quote = str(raw.get("evidence_quote") or raw.get("ocr_evidence") or "") if isinstance(raw, dict) else ""
                ai_comment = str(raw.get("ai_comment") or raw.get("ai_feedback") or raw.get("feedback") or "") if isinstance(raw, dict) else ""

                # Determine whether the student attempted this question.
                # We trust the LLM: if it returned a non-empty student_answer
                # or a non-empty evidence_quote, the student attempted it.
                attempted_raw = raw.get("attempted") if isinstance(raw, dict) else None
                attempted = bool(student_answer.strip()) or bool(evidence_quote.strip())
                if attempted_raw is not None:
                    attempted = bool(attempted_raw)

                # Soft evidence check: only zero out when the LLM itself
                # says the student didn't answer (empty student_answer AND
                # empty evidence_quote).  This avoids false negatives from
                # fuzzy string matching against noisy OCR.
                if marks_awarded > 0 and not student_answer.strip() and not evidence_quote.strip():
                    marks_awarded = 0.0
                    attempted = False
                    ai_comment = (ai_comment + " No student answer found in OCR text.").strip()

                marks_awarded = max(0.0, min(marks_awarded, max_marks))
                total_score += marks_awarded

                confidence = raw.get("confidence", raw.get("ai_confidence", 0.75)) if isinstance(raw, dict) else 0.75
                try:
                    confidence = max(0.0, min(float(confidence), 1.0))
                except (TypeError, ValueError):
                    confidence = 0.75

                is_correct = raw.get("is_correct") if isinstance(raw, dict) else None
                if is_correct is None:
                    is_correct = max_marks > 0 and marks_awarded >= max_marks
                if marks_awarded == 0:
                    is_correct = False

                normalized_details.append({
                    "question_id": question_id,
                    "question_text": question.get("question_text", ""),
                    "question_type": question.get("question_type", "short_answer"),
                    "student_answer": student_answer,
                    "student_answer_text": student_answer,
                    "evidence_quote": evidence_quote,
                    "correct_answer": question.get("correct_answer", ""),
                    "marks_awarded": marks_awarded,
                    "scored_marks": marks_awarded,
                    "max_marks": max_marks,
                    "score": marks_awarded,
                    "max_score": max_marks,
                    "is_correct": bool(is_correct),
                    "attempted": attempted,
                    "ai_comment": ai_comment,
                    "ai_feedback": ai_comment,
                    "confidence": confidence,
                    "ai_confidence": confidence,
                    "evidence_found": bool(evidence_quote.strip()),
                })

            grade_percentage = (total_score / total_marks) * 100 if total_marks > 0 else 0.0
            overall_confidence = data.get("confidence", 0.75)
            try:
                overall_confidence = max(0.0, min(float(overall_confidence), 1.0))
            except (TypeError, ValueError):
                overall_confidence = 0.75

            return {
                "total_score": round(total_score, 2),
                "max_score": round(total_marks, 2),
                "grade_percentage": round(grade_percentage, 2),
                "overall_feedback": str(data.get("overall_feedback") or data.get("feedback") or ""),
                "confidence": overall_confidence,
                "question_details": normalized_details,
            }
        except Exception as e:
            logger.error(f"Error parsing per-question grading result: {e}")
            return None

    def _has_ocr_evidence(self, ocr_text: str, evidence_quote: str) -> bool:
        """Return true only when a direct evidence quote appears in the OCR text."""
        if not ocr_text or not evidence_quote:
            return False

        normalized_ocr = self._normalize_evidence_text(ocr_text)
        normalized_quote = self._normalize_evidence_text(evidence_quote)

        if len(normalized_quote) < 3:
            return False
        if normalized_quote in normalized_ocr:
            return True

        # Allow short OCR spacing/punctuation drift, but require enough overlap to
        # avoid accepting answers copied from the answer key.
        quote_words = normalized_quote.split()
        if len(quote_words) <= 2:
            return False

        window_size = min(len(quote_words), 8)
        for start in range(0, len(quote_words) - window_size + 1):
            window = " ".join(quote_words[start:start + window_size])
            if len(window) >= 12 and window in normalized_ocr:
                return True

        return False

    def _has_student_answer_evidence(
        self,
        ocr_text: str,
        evidence_quote: str,
        student_answer: str,
        question_text: str,
    ) -> bool:
        """Require OCR evidence that supports the extracted student answer itself."""
        if not self._has_ocr_evidence(ocr_text, evidence_quote):
            return False

        normalized_quote = self._normalize_evidence_text(evidence_quote)
        normalized_answer = self._normalize_evidence_text(student_answer)
        normalized_question = self._normalize_evidence_text(question_text)

        if not normalized_answer:
            return False

        if self._quote_is_question_only(normalized_quote, normalized_question, normalized_answer):
            return False

        return self._answer_supported_by_text(normalized_answer, normalized_quote)

    def _quote_is_question_only(self, quote: str, question: str, answer: str) -> bool:
        if not quote or not question:
            return False

        quote_tokens = self._meaningful_tokens(quote)
        question_tokens = set(self._meaningful_tokens(question))
        answer_tokens = set(self._meaningful_tokens(answer))

        if not quote_tokens or not question_tokens:
            return False

        question_hits = sum(1 for token in quote_tokens if token in question_tokens)
        answer_hits = sum(1 for token in quote_tokens if token in answer_tokens)

        question_ratio = question_hits / max(len(quote_tokens), 1)
        answer_ratio = answer_hits / max(len(answer_tokens), 1) if answer_tokens else 0.0

        return question_ratio >= 0.75 and answer_ratio < 0.5

    def _answer_supported_by_text(self, answer: str, text: str) -> bool:
        if not answer or not text:
            return False

        if len(answer) >= 3 and answer in text:
            return True

        answer_tokens = self._meaningful_tokens(answer)
        text_tokens = set(self._meaningful_tokens(text))
        if not answer_tokens or not text_tokens:
            return False

        if len(answer_tokens) == 1:
            token = answer_tokens[0]
            return len(token) >= 3 and token in text_tokens

        hits = sum(1 for token in answer_tokens if token in text_tokens)
        required_ratio = 1.0 if len(answer_tokens) <= 3 else 0.7
        return (hits / len(answer_tokens)) >= required_ratio

    def _meaningful_tokens(self, value: str) -> List[str]:
        stop_words = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
            "in", "is", "it", "of", "on", "or", "the", "to", "was", "were",
            "what", "when", "where", "which", "who", "why", "how", "define",
            "explain", "describe", "question", "q",
        }
        return [token for token in value.split() if token not in stop_words]

    def _normalize_evidence_text(self, value: str) -> str:
        value = value.lower()
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())
    
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
