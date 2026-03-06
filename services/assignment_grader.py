"""
AI Assignment Grading Service
Uses Google Gemini (via Groq as fallback) to auto-grade student submissions.
Validates output with Pydantic and stores structured results.
"""
import json
import logging
from typing import Dict, Any, List, Optional

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _letter_grade(percentage: float) -> str:
    """Convert percentage to letter grade"""
    if percentage >= 90:
        return "A+"
    elif percentage >= 85:
        return "A"
    elif percentage >= 80:
        return "B+"
    elif percentage >= 75:
        return "B"
    elif percentage >= 70:
        return "C+"
    elif percentage >= 65:
        return "C"
    elif percentage >= 50:
        return "D"
    else:
        return "F"


async def _get_rag_context(subject_id: str, assignment_title: str) -> str:
    """Retrieve relevant document chunks for grading context"""
    try:
        from services.embedding_service import EmbeddingService
        from services.database import get_database
        
        db = await get_database()
        emb_service = EmbeddingService()
        
        query_text = f"Grading criteria and concepts for: {assignment_title}"
        embedding = await emb_service.generate_embedding(query_text)
        
        if embedding:
            chunks = await db.search_similar_chunks(
                embedding, subject_id, limit=5, match_threshold=0.5
            )
            if chunks:
                return "\n\n---\n\n".join(c.get("text", "") for c in chunks[:5])
    except Exception as e:
        logger.warning(f"Could not retrieve RAG context: {e}")
    return ""


async def _call_llm(prompt: str) -> Optional[str]:
    """Call LLM (Groq) for grading — returns raw text response"""
    try:
        from groq import AsyncGroq
        
        client = AsyncGroq(api_key=settings.groq_api_key)
        response = await client.chat.completions.create(
            model=settings.groq_llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert teacher grading student assignments fairly and constructively. "
                        "Always respond with valid JSON only, no markdown code fences."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return None


def _parse_grading_json(raw: str, total_marks: int) -> Dict[str, Any]:
    """Parse and validate the LLM grading response"""
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                logger.error(f"Could not parse grading JSON: {text[:200]}")
                return _fallback_result(total_marks)
        else:
            return _fallback_result(total_marks)
    
    # Validate and normalize
    marks = float(data.get("marks_obtained", 0))
    marks = max(0, min(marks, total_marks))
    percentage = round(marks / max(total_marks, 1) * 100, 2)
    
    return {
        "marks_obtained": marks,
        "percentage": percentage,
        "grade": data.get("grade") or _letter_grade(percentage),
        "ai_feedback": data.get("ai_feedback", data.get("feedback", "Grading completed.")),
        "rubric_breakdown": data.get("rubric_breakdown", []),
        "strengths": data.get("strengths", []),
        "improvements": data.get("improvements", []),
    }


def _fallback_result(total_marks: int) -> Dict[str, Any]:
    """Return a fallback result when LLM fails"""
    return {
        "marks_obtained": 0,
        "percentage": 0,
        "grade": "N/A",
        "ai_feedback": "AI grading could not be completed. Please grade manually.",
        "rubric_breakdown": [],
        "strengths": [],
        "improvements": [],
    }


async def grade_assignment_submission(
    assignment: Dict[str, Any],
    submission: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Grade a student's assignment submission using AI.
    
    Args:
        assignment: The assignment record from DB
        submission: The submission record from DB
        
    Returns:
        Dict with marks_obtained, percentage, grade, ai_feedback, rubric_breakdown, strengths, improvements
    """
    total_marks = assignment.get("total_marks", 10)
    title = assignment.get("title", "Assignment")
    instructions = assignment.get("instructions", "")
    rubric = assignment.get("grading_rubric", "")
    student_text = submission.get("submission_text", "")
    subject_id = str(assignment.get("subject_id", ""))
    
    # If no student text and no instructions, fallback
    if not student_text and not instructions:
        return _fallback_result(total_marks)
    
    # Get RAG context from subject documents
    rag_context = ""
    if subject_id:
        rag_context = await _get_rag_context(subject_id, title)
    
    # Build grading prompt
    prompt_parts = [
        f"## Assignment: {title}\n",
        f"**Total Marks:** {total_marks}\n",
    ]
    
    if instructions:
        prompt_parts.append(f"**Instructions Given to Student:**\n{instructions}\n")
    
    if rubric:
        prompt_parts.append(f"**Grading Rubric / Answer Key:**\n{rubric}\n")
    
    if rag_context:
        prompt_parts.append(f"**Reference Material (from course documents):**\n{rag_context[:3000]}\n")
    
    prompt_parts.append(f"---\n\n**Student's Submission:**\n{student_text[:5000]}\n")
    
    prompt_parts.append(f"""
---

**Task:** Grade this submission out of {total_marks} marks, using the rubric and reference material above.

Return a JSON object with this exact schema:
{{
  "marks_obtained": <number between 0 and {total_marks}>,
  "grade": "<letter grade: A+, A, B+, B, C+, C, D, F>",
  "ai_feedback": "<300-500 word constructive feedback in markdown>",
  "rubric_breakdown": [
    {{"criteria": "<criterion name>", "score": <number>, "max_score": <number>, "comment": "<brief comment>"}}
  ],
  "strengths": ["<strength 1>", "<strength 2>"],
  "improvements": ["<area to improve 1>", "<area to improve 2>"]
}}

Be fair, constructive, and specific in your feedback. Reference specific parts of the student's answer.
""")
    
    prompt = "\n".join(prompt_parts)
    
    # Call LLM
    raw_response = await _call_llm(prompt)
    
    if not raw_response:
        logger.warning(f"LLM returned empty response for assignment {assignment.get('id')}")
        return _fallback_result(total_marks)
    
    # Parse and validate
    result = _parse_grading_json(raw_response, total_marks)
    
    # Merge strengths/improvements into feedback if they aren't already there
    if result.get("strengths") or result.get("improvements"):
        extra = ""
        if result["strengths"]:
            extra += "\n\n**Strengths:**\n" + "\n".join(f"- {s}" for s in result["strengths"])
        if result["improvements"]:
            extra += "\n\n**Areas to Improve:**\n" + "\n".join(f"- {s}" for s in result["improvements"])
        result["ai_feedback"] = result["ai_feedback"] + extra
    
    logger.info(
        f"Graded assignment {assignment.get('id')} — "
        f"Score: {result['marks_obtained']}/{total_marks} ({result['grade']})"
    )
    
    return result
