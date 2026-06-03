"""
Assignments API — CRUD + publish/close + AI generation + submissions + grading
+ Email integration (IMAP) + Manual upload
NOTE: Static routes (email/*, generate-content) MUST come before /{assignment_id}
"""
import logging, os, uuid, json, re
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from utils.security import require_teacher
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Models ───────────────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    title: str
    subject_id: str
    class_id: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    total_marks: int = 10
    due_date: Optional[str] = None
    grading_rubric: Optional[str] = None
    auto_grade: bool = True
    status: str = "draft"
    attachment_url: Optional[str] = None
    attachment_filename: Optional[str] = None
    generate_pdf: bool = True
    generated_outline: Optional[Dict[str, Any]] = None

class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    total_marks: Optional[int] = None
    due_date: Optional[str] = None
    grading_rubric: Optional[str] = None
    auto_grade: Optional[bool] = None
    status: Optional[str] = None

class OverrideRequest(BaseModel):
    teacher_override_marks: Optional[float] = None
    teacher_remarks: Optional[str] = None

class EmailConfigRequest(BaseModel):
    email_address: str
    app_password: str
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_name: Optional[str] = None
    is_active: bool = True

class GenerateContentRequest(BaseModel):
    title: str
    subject_name: str
    class_name: Optional[str] = None
    total_marks: int = 10
    topic_hint: Optional[str] = None
    assignment_type: str = "worksheet"
    difficulty_level: str = "medium"
    estimated_duration: Optional[str] = None
    deliverables: Optional[List[str]] = None
    requirements: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _assignment_email_code(assignment_id: str) -> str:
    clean = re.sub(r"[^a-fA-F0-9]", "", assignment_id or "")
    suffix = (clean[:8] or uuid.uuid4().hex[:8]).upper()
    return f"ASG-{suffix}"


def _assignment_email_subject(title: str, assignment_id: str) -> str:
    return f"[{_assignment_email_code(assignment_id)}] {title}".strip()


def _normalize_email(value: Any) -> str:
    parsed = parseaddr(str(value or ""))[1]
    return (parsed or str(value or "")).strip().lower()


def _clean_email_submission_copy(value: Any) -> str:
    """Normalize stale email-submission instructions in generated assignment copy."""
    text = str(value or "").strip()
    if not text:
        return ""

    cleaned = re.sub(
        r"\[\s*(ASG-[A-Fa-f0-9]{8}|ASG-CODE)\s+(?:ROLL|RN|ROLL\s*(?:NO|NUMBER))[^\]\n]*\]",
        r"[\1]",
        text,
        flags=re.IGNORECASE,
    )
    chunks = re.split(r"(?<=[.!?])\s+|\r?\n+", cleaned)
    kept: list[str] = []
    removed_stale_submission_rule = False
    for chunk in chunks:
        line = chunk.strip()
        if not line:
            continue
        lowered = line.lower()
        mentions_submission = any(
            token in lowered
            for token in ("email", "subject", "assignment code", " code", "submission", "submit")
        )
        if "roll" in lowered and mentions_submission:
            removed_stale_submission_rule = True
            continue
        kept.append(line)

    cleaned = "\n".join(kept)
    if removed_stale_submission_rule:
        canonical = (
            "Email submissions must be sent from the email address your teacher added to the class roster "
            "and use the exact assignment code in the subject."
        )
        if canonical.lower() not in cleaned.lower():
            cleaned = f"{cleaned}\n{canonical}".strip()
    return cleaned


def _ser(a: dict) -> dict:
    assignment_id = str(a["id"])
    return {
        "id": assignment_id,
        "teacher_id": str(a["teacher_id"]),
        "subject_id": str(a["subject_id"]),
        "subject_name": a.get("subject_name"),
        "class_id": str(a["class_id"]),
        "class_name": a.get("class_name"),
        "title": a.get("title", ""),
        "description": a.get("description"),
        "instructions": _clean_email_submission_copy(a.get("instructions")),
        "total_marks": a.get("total_marks", 10),
        "due_date": str(a["due_date"]) if a.get("due_date") else None,
        "attachment_url": a.get("attachment_url"),
        "attachment_filename": a.get("attachment_filename"),
        "email_submission_code": _assignment_email_code(assignment_id),
        "email_subject_syntax": _assignment_email_subject(a.get("title", ""), assignment_id),
        "grading_rubric": a.get("grading_rubric"),
        "auto_grade": a.get("auto_grade", True),
        "status": a.get("status", "draft"),
        "created_at": str(a["created_at"]),
        "updated_at": str(a["updated_at"]) if a.get("updated_at") else None,
    }

def _ser_sub(s: dict) -> dict:
    files = s.get("submission_files", [])
    if isinstance(files, str):
        try: files = json.loads(files)
        except: files = []
    rubric = s.get("ai_rubric_breakdown")
    if isinstance(rubric, str):
        try: rubric = json.loads(rubric)
        except: rubric = None
    return {
        "id": str(s["id"]),
        "assignment_id": str(s["assignment_id"]),
        "assignment_title": s.get("assignment_title"),
        "assignment_due_date": str(s["assignment_due_date"]) if s.get("assignment_due_date") else None,
        "student_id": str(s["student_id"]) if s.get("student_id") else None,
        "student_name": s.get("student_name", ""),
        "student_email": s.get("student_email", ""),
        "roll_number": s.get("roll_number"),
        "class_id": str(s["class_id"]),
        "class_name": s.get("class_name"),
        "subject_id": str(s["subject_id"]) if s.get("subject_id") else None,
        "subject_name": s.get("subject_name"),
        "submission_text": s.get("submission_text"),
        "submission_files": files,
        "marks_obtained": float(s["marks_obtained"]) if s.get("marks_obtained") is not None else None,
        "max_marks": s.get("max_marks"),
        "percentage": float(s["percentage"]) if s.get("percentage") is not None else None,
        "grade": s.get("grade"),
        "ai_feedback": s.get("ai_feedback"),
        "ai_rubric_breakdown": rubric,
        "teacher_remarks": s.get("teacher_remarks"),
        "teacher_override_marks": float(s["teacher_override_marks"]) if s.get("teacher_override_marks") is not None else None,
        "status": s.get("status", "pending"),
        "submitted_at": str(s["submitted_at"]) if s.get("submitted_at") else None,
        "graded_at": str(s["graded_at"]) if s.get("graded_at") else None,
        "created_at": str(s["created_at"]),
        "source": s.get("source", "manual"),
    }

def _ser_email_log(log: dict) -> dict:
    attachments = log.get("attachment_paths", [])
    if isinstance(attachments, str):
        try:
            attachments = json.loads(attachments)
        except Exception:
            attachments = []
    return {
        "id": str(log["id"]),
        "assignment_id": str(log["assignment_id"]) if log.get("assignment_id") else None,
        "assignment_title": log.get("assignment_title"),
        "assignment_code": _assignment_email_code(str(log["assignment_id"])) if log.get("assignment_id") else None,
        "class_id": str(log["class_id"]) if log.get("class_id") else None,
        "class_name": log.get("class_name"),
        "subject_id": str(log["subject_id"]) if log.get("subject_id") else None,
        "subject_name": log.get("subject_name"),
        "student_id": str(log["student_id"]) if log.get("student_id") else None,
        "student_name": log.get("student_name"),
        "student_email": log.get("student_email"),
        "student_roll_number": log.get("student_roll_number") or log.get("roll_number"),
        "email_from": log.get("email_from"),
        "email_subject": log.get("email_subject"),
        "email_body": log.get("email_body"),
        "attachment_paths": attachments,
        "processed_at": str(log["processed_at"]) if log.get("processed_at") else None,
        "status": log.get("status", "processed"),
        "notes": log.get("notes"),
    }

def _parse_due(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None


def _safe_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "assignment").strip("._-")
    return clean[:80] or "assignment"


def _as_text_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        items: List[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("title") or item.get("details") or item.get("description") or ""
            else:
                text = str(item)
            text = text.strip()
            if text:
                items.append(text)
        return items
    if isinstance(value, str):
        return [line.strip(" -\t") for line in value.splitlines() if line.strip(" -\t")]
    return [str(value)]


def _normalize_generated_payload(data: dict, req: GenerateContentRequest) -> dict:
    raw_tasks = data.get("tasks") or []
    if not isinstance(raw_tasks, list):
        raw_tasks = []

    tasks = []
    for idx, item in enumerate(raw_tasks[:8], start=1):
        if isinstance(item, dict):
            title = str(item.get("title") or f"Task {idx}").strip()
            details = str(item.get("details") or item.get("description") or "").strip()
            marks = item.get("marks")
        else:
            title = f"Task {idx}"
            details = str(item).strip()
            marks = None
        tasks.append({"title": title or f"Task {idx}", "details": details, "marks": marks})

    deliverables = _as_text_list(data.get("deliverables")) or _as_text_list(req.deliverables)
    objectives = _as_text_list(data.get("learning_objectives") or data.get("objectives"))
    instructions = str(data.get("instructions") or "").strip()
    if not instructions and tasks:
        instructions = "\n".join(
            f"{i}. {task['title']}: {task['details']}" for i, task in enumerate(tasks, start=1)
        )

    return {
        "assignment_name": str(data.get("assignment_name") or req.title).strip(),
        "description": str(data.get("description") or "").strip(),
        "instructions": _clean_email_submission_copy(instructions),
        "grading_rubric": str(data.get("grading_rubric") or data.get("rubric") or "").strip(),
        "learning_objectives": objectives,
        "tasks": tasks,
        "deliverables": deliverables,
        "submission_format": _clean_email_submission_copy(str(
            data.get("submission_format") or "Submit one PDF or document file with your completed work."
        ).strip()),
        "email_subject_syntax": str(data.get("email_subject_syntax") or f"[ASG-CODE] {req.title}").strip(),
        "assignment_type": req.assignment_type,
        "difficulty_level": req.difficulty_level,
        "estimated_duration": req.estimated_duration,
    }


def _allocate_marks(total_marks: int, parts: int) -> List[int]:
    total = max(int(total_marks or 1), 1)
    count = max(parts, 1)
    base = total // count
    marks = [base for _ in range(count)]
    for idx in range(total % count):
        marks[idx] += 1
    return marks


def _fallback_generated_payload(req: GenerateContentRequest, reason: str = "") -> dict:
    class_label = req.class_name or "the selected class"
    topic = (req.topic_hint or req.title or req.subject_name).strip()
    assignment_type = (req.assignment_type or "assignment").replace("_", " ").strip()
    difficulty = (req.difficulty_level or "medium").replace("_", " ").strip()
    deliverables = _as_text_list(req.deliverables) or [
        "Completed assignment document or PDF",
        "Supporting calculations, references, diagrams, or evidence where required",
        "Short conclusion or reflection summarizing what was learned",
    ]
    if req.requirements:
        deliverables.append(f"Teacher requirement: {req.requirements.strip()}")

    marks = _allocate_marks(req.total_marks, 4)
    tasks = [
        {
            "title": "Concept Understanding",
            "details": f"Explain the key ideas related to {topic} in your own words. Include definitions, important terms, and the connection to {req.subject_name}.",
            "marks": marks[0],
        },
        {
            "title": "Applied Work",
            "details": f"Solve or complete a practical activity based on {topic}. Show clear working, reasoning, diagrams, code, or examples as appropriate for the subject.",
            "marks": marks[1],
        },
        {
            "title": "Analysis and Discussion",
            "details": "Interpret your results and explain why your approach is valid. Compare alternatives, identify patterns, and mention limitations where relevant.",
            "marks": marks[2],
        },
        {
            "title": "Presentation and Submission Quality",
        "details": "Organize the final work neatly with headings, readable formatting, student name, class-roster email, and all requested deliverables attached in one submission.",
            "marks": marks[3],
        },
    ]

    instructions = [
        f"Complete this {assignment_type} for {class_label} in {req.subject_name}.",
        f"Focus your work on: {topic}.",
        f"Difficulty level: {difficulty}.",
        "Read every task before starting and keep your answers organized under matching headings.",
        "Submit one final PDF or document file. If submitting by email, send it from the email address your teacher added to the class roster and use the exact assignment code in the subject shown below.",
        "The system maps email submissions by class-roster sender email plus assignment code.",
    ]
    if req.estimated_duration:
        instructions.insert(3, f"Expected time: {req.estimated_duration}.")
    if req.requirements:
        instructions.insert(4, f"Additional teacher requirements: {req.requirements.strip()}")

    rubric_lines = [
        f"Concept accuracy and subject understanding: {marks[0]} marks",
        f"Quality of applied work and method: {marks[1]} marks",
        f"Analysis, reasoning, and explanation: {marks[2]} marks",
        f"Presentation, completeness, and submission format: {marks[3]} marks",
        f"Total: {sum(marks)} marks",
    ]

    if reason:
        logger.warning("Using local assignment generation fallback: %s", reason)

    return {
        "assignment_name": req.title,
        "description": (
            f"This {assignment_type} is designed for {class_label} in {req.subject_name}. "
            f"Students will demonstrate understanding of {topic}, apply the concept through structured work, "
            "and submit a complete assignment that can be downloaded as a PDF and mapped through the email code."
        ),
        "instructions": "\n".join(f"{idx}. {text}" for idx, text in enumerate(instructions, start=1)),
        "grading_rubric": "\n".join(rubric_lines),
        "learning_objectives": [
            f"Explain the core concepts of {topic} using correct {req.subject_name} vocabulary.",
            "Apply the topic to a structured task with clear steps, evidence, and reasoning.",
            "Present final work in a complete, organized format suitable for grading and email submission.",
        ],
        "tasks": tasks,
        "deliverables": deliverables,
        "submission_format": "Submit one PDF or document file. Email submissions must be sent from the student's class-roster email address and use the exact assignment code in the subject.",
        "email_subject_syntax": f"[ASG-CODE] {req.title}",
        "assignment_type": req.assignment_type,
        "difficulty_level": req.difficulty_level,
        "estimated_duration": req.estimated_duration,
    }


def _build_assignment_pdf(
    assignment: dict,
    *,
    class_name: str = "",
    subject_name: str = "",
    teacher_name: str = "",
    outline: Optional[Dict[str, Any]] = None,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape
    import io

    outline = outline or {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.72 * inch,
        leftMargin=0.72 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.72 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AssignmentTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0f172a"),
    )
    section_style = ParagraphStyle(
        "AssignmentSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        spaceBefore=10,
        spaceAfter=6,
        textColor=colors.HexColor("#0A66C2"),
    )
    body_style = ParagraphStyle(
        "AssignmentBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1f2937"),
    )

    assignment_id = str(assignment["id"])
    title = assignment.get("title") or "Assignment"
    code = _assignment_email_code(assignment_id)
    due_date = assignment.get("due_date")
    due_text = due_date.strftime("%b %d, %Y %I:%M %p") if hasattr(due_date, "strftime") else (str(due_date) if due_date else "No deadline")

    def p(text: Any, style=body_style):
        escaped = escape(str(text or "")).replace("\n", "<br/>")
        return Paragraph(escaped, style)

    story = [
        Paragraph(
            "ASSIGNMENT SHEET",
            ParagraphStyle(
                "AssignmentKicker",
                parent=styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=10,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#0A66C2"),
                spaceAfter=5,
            ),
        ),
        Paragraph(escape(title), title_style),
        Spacer(1, 12),
    ]

    info_rows = [
        [p("Class"), p(class_name or assignment.get("class_name") or "Class not set"), p("Subject"), p(subject_name or assignment.get("subject_name") or "Subject not set")],
        [p("Total Marks"), p(assignment.get("total_marks", 10)), p("Deadline"), p(due_text)],
        [p("Assignment Code"), p(code), p("Teacher"), p(teacher_name or "Teacher")],
        [p("Email Subject"), p(_assignment_email_subject(title, assignment_id)), "", ""],
    ]
    info_table = Table(info_rows, colWidths=[1.15 * inch, 2.05 * inch, 1.15 * inch, 2.05 * inch])
    info_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("SPAN", (1, 3), (3, 3)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([info_table, Spacer(1, 10)])

    description = assignment.get("description") or outline.get("description")
    if description:
        story.extend([Paragraph("Overview", section_style), p(description)])

    objectives = _as_text_list(outline.get("learning_objectives") or outline.get("objectives"))
    if objectives:
        story.append(Paragraph("Learning Objectives", section_style))
        for item in objectives:
            story.append(p(f"- {item}"))

    tasks = outline.get("tasks") if isinstance(outline.get("tasks"), list) else []
    if tasks:
        story.append(Paragraph("Assignment Tasks", section_style))
        rows = [[p("#"), p("Task"), p("Requirements"), p("Marks")]]
        for idx, task in enumerate(tasks, start=1):
            if isinstance(task, dict):
                task_title = task.get("title") or f"Task {idx}"
                details = task.get("details") or task.get("description") or ""
                marks = task.get("marks") or ""
            else:
                task_title = f"Task {idx}"
                details = str(task)
                marks = ""
            rows.append([p(idx), p(task_title), p(details), p(marks)])
        task_table = Table(rows, colWidths=[0.35 * inch, 1.5 * inch, 3.65 * inch, 0.7 * inch], repeatRows=1)
        task_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf3fc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(task_table)

    instructions = _clean_email_submission_copy(assignment.get("instructions") or outline.get("instructions"))
    if instructions:
        story.extend([Paragraph("Instructions", section_style), p(instructions)])

    deliverables = _as_text_list(outline.get("deliverables"))
    if deliverables:
        story.append(Paragraph("Deliverables", section_style))
        for item in deliverables:
            story.append(p(f"- {item}"))

    rubric = assignment.get("grading_rubric") or outline.get("grading_rubric")
    if rubric:
        story.extend([Paragraph("Grading Rubric", section_style), p(rubric)])

    story.extend([
        Paragraph("Email Submission", section_style),
        p(f"Email submission subject format: {_assignment_email_subject(title, assignment_id)}. Send the email from the email address your teacher added to the class roster and attach one completed PDF or document. The system uses that roster email address and this assignment code to map your submission to the correct student, assignment, class, and subject."),
        Spacer(1, 12),
        p("Student Name: ________________________________     Registered Email: ________________________________"),
    ])

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


def _save_assignment_pdf(assignment: dict, current_user: dict, outline: Optional[Dict[str, Any]] = None) -> dict:
    assignment_id = str(assignment["id"])
    title = assignment.get("title") or "Assignment"
    filename = f"{_safe_filename(title)}_{_assignment_email_code(assignment_id)}.pdf"
    save_dir = os.path.join("uploads", "assignments", assignment_id)
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, filename)
    pdf_bytes = _build_assignment_pdf(
        assignment,
        class_name=assignment.get("class_name") or "",
        subject_name=assignment.get("subject_name") or "",
        teacher_name=current_user.get("name") or "Teacher",
        outline=outline,
    )
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    return {
        "attachment_url": f"/static/uploads/assignments/{assignment_id}/{filename}",
        "attachment_filename": filename,
    }

async def _validate_assignment_scope(db, user, class_id: str, subject_id: str):
    cls = await db.get_class(class_id)
    if not cls or str(cls.get("teacher_id")) != user["id"]:
        raise HTTPException(403, "Access denied to this class")

    subject = await db.get_subject(subject_id)
    if not subject or str(subject.get("teacher_id")) != user["id"]:
        raise HTTPException(403, "Access denied to this subject")

    subject_class_id = str(subject.get("class_id")) if subject.get("class_id") else None
    if subject_class_id and subject_class_id != class_id:
        raise HTTPException(400, "Selected subject does not belong to the selected class")

    return cls, subject


async def _resolve_roster_student_for_submission(db, class_id: str, student_ref_id: str) -> dict:
    roster_student = await db.get_student(student_ref_id)
    if roster_student and str(roster_student.get("class_id")) == class_id:
        return roster_student

    raise HTTPException(400, "Selected student was not found in this assignment class roster")


async def _own(db, user, aid):
    a = await db.get_assignment(aid)
    if not a:
        raise HTTPException(404, "Assignment not found")
    if str(a["teacher_id"]) != user["id"]:
        raise HTTPException(403, "Access denied")
    return a

async def _do_grade(db, a, sub):
    """Run AI grading and persist results. Returns updated sub dict."""
    from services.assignment_grader import grade_assignment_submission
    result = await grade_assignment_submission(a, sub)
    upd = {
        "marks_obtained": result["marks_obtained"],
        "max_marks": a.get("total_marks", 10),
        "percentage": result["percentage"],
        "grade": result["grade"],
        "ai_feedback": result["ai_feedback"],
        "ai_rubric_breakdown": result.get("rubric_breakdown", []),
        "status": "graded",
        "graded_at": datetime.utcnow(),
    }
    updated = await db.update_assignment_submission(str(sub["id"]), upd)
    return updated or sub


# ─── AI Content Generation  (STATIC — must be before /{assignment_id}) ────────

@router.post("/generate-content")
async def generate_assignment_content(
    req: GenerateContentRequest,
    current_user: dict = Depends(require_teacher()),
):
    """Use AI to auto-generate description, instructions, and grading rubric."""
    deliverables = ", ".join(req.deliverables or []) or "PDF or document submission"
    prompt = f"""You are an expert teacher creating a complete, classroom-ready assignment.

ASSIGNMENT CONTEXT
- Title: {req.title}
- Subject: {req.subject_name}
- Class: {req.class_name or 'General'}
- Type: {req.assignment_type}
- Difficulty: {req.difficulty_level}
- Total Marks: {req.total_marks}
- Estimated Duration: {req.estimated_duration or 'Teacher did not specify'}
- Required Deliverables: {deliverables}
{f'- Topic Focus: {req.topic_hint}' if req.topic_hint else ''}
{f'- Extra Requirements: {req.requirements}' if req.requirements else ''}

Create a proper assignment sheet that a teacher can publish directly.
Use clear student-facing language. Split the marks across 3 to 6 meaningful tasks.
Make the grading rubric add up to {req.total_marks} marks.
Use the placeholder [ASG-CODE] in the email subject; the real assignment code is assigned when the assignment is saved. Students must send email submissions from the email address their teacher added to the class roster.
Only describe email submission mapping through the class-roster sender email address and assignment code.

Return ONLY valid JSON (no markdown fences) with this exact schema:
{{
  "assignment_name": "{req.title}",
  "description": "<2-3 sentence overview>",
  "learning_objectives": ["objective 1", "objective 2", "objective 3"],
  "tasks": [
    {{"title": "Task title", "details": "student-facing task details", "marks": 5}}
  ],
  "deliverables": ["what the student must submit"],
  "instructions": "<complete step-by-step instructions, 180-300 words>",
  "submission_format": "<how to submit, including PDF guidance>",
  "email_subject_syntax": "[ASG-CODE] {req.title}",
  "grading_rubric": "<rubric with mark allocation that totals {req.total_marks} marks>"
}}
"""
    try:
        from groq import AsyncGroq
        from config import get_settings
        settings = get_settings()
    except Exception as e:
        return _fallback_generated_payload(req, f"AI client unavailable: {e}")

    api_keys = [
        key.strip()
        for key in getattr(settings, "all_groq_keys", [])
        if key and key.strip() and "placeholder" not in key.strip().lower()
    ]
    if not api_keys:
        return _fallback_generated_payload(req, "No Groq API key configured")

    last_error: Optional[Exception] = None
    for api_key in api_keys:
        try:
            client = AsyncGroq(api_key=api_key)
            response = await client.chat.completions.create(
                model=settings.groq_llm_model,
                messages=[
                    {"role": "system", "content": "You are an expert teacher who creates clear, well-structured assignments. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.65,
                max_tokens=1800,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                lines = raw.split("\n")
                lines = [line for line in lines if not line.strip().startswith("```")]
                raw = "\n".join(lines)
            data = json.loads(raw)
            return _normalize_generated_payload(data, req)
        except json.JSONDecodeError as e:
            logger.warning("AI assignment generation returned malformed JSON: %s", e)
            return _fallback_generated_payload(req, "AI returned malformed JSON")
        except Exception as e:
            last_error = e
            logger.warning("AI assignment generation failed with a configured Groq key: %s", e)

    return _fallback_generated_payload(req, str(last_error) if last_error else "AI generation unavailable")


# ─── Email Config  (STATIC — must be before /{assignment_id}) ─────────────────

@router.get("/email/config")
async def get_email_config(current_user: dict = Depends(require_teacher())):
    db = await get_database()
    result = await db.get_email_config(current_user["id"])
    if not result:
        return None
    return {
        "id": str(result["id"]),
        "email_address": result["email_address"],
        "imap_host": result["imap_host"],
        "imap_port": result["imap_port"],
        "smtp_host": result.get("smtp_host") or "smtp.gmail.com",
        "smtp_port": result.get("smtp_port") or 587,
        "smtp_use_tls": result.get("smtp_use_tls", True),
        "smtp_use_ssl": result.get("smtp_use_ssl", False),
        "from_name": result.get("from_name"),
        "is_active": result["is_active"],
        "last_fetched_at": str(result["last_fetched_at"]) if result.get("last_fetched_at") else None,
    }

@router.post("/email/config")
async def save_email_config(data: EmailConfigRequest, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    result = await db.save_email_config(current_user["id"], data.dict())
    if not result:
        raise HTTPException(500, "Failed to save email config")
    return {
        "id": str(result["id"]),
        "email_address": result["email_address"],
        "imap_host": result["imap_host"],
        "imap_port": result["imap_port"],
        "smtp_host": result.get("smtp_host") or "smtp.gmail.com",
        "smtp_port": result.get("smtp_port") or 587,
        "smtp_use_tls": result.get("smtp_use_tls", True),
        "smtp_use_ssl": result.get("smtp_use_ssl", False),
        "from_name": result.get("from_name"),
        "is_active": result["is_active"],
        "last_fetched_at": str(result["last_fetched_at"]) if result.get("last_fetched_at") else None,
    }

@router.post("/email/test-connection")
async def test_email_connection(data: EmailConfigRequest, current_user: dict = Depends(require_teacher())):
    from services.email_service import EmailFetcher, EmailSender
    fetcher = EmailFetcher(data.email_address, data.app_password, data.imap_host, data.imap_port)
    imap_result = fetcher.test_connection()
    sender = EmailSender(
        data.email_address,
        data.app_password,
        data.smtp_host,
        data.smtp_port,
        data.smtp_use_tls,
        data.smtp_use_ssl,
        data.from_name,
    )
    smtp_result = sender.test_connection()
    success = bool(imap_result.get("success") and smtp_result.get("success"))
    return {
        "success": success,
        "message": f"IMAP: {imap_result.get('message')}. SMTP: {smtp_result.get('message')}.",
    }


# ─── Assignment CRUD ───────────────────────────────────────────────────────────

@router.post("/")
async def create_assignment(data: AssignmentCreate, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _validate_assignment_scope(db, current_user, data.class_id, data.subject_id)
    payload = {
        "teacher_id": current_user["id"],
        "subject_id": data.subject_id,
        "class_id": data.class_id,
        "title": data.title,
        "description": data.description,
        "instructions": _clean_email_submission_copy(data.instructions),
        "total_marks": data.total_marks,
        "due_date": _parse_due(data.due_date),
        "attachment_url": data.attachment_url,
        "attachment_filename": data.attachment_filename,
        "grading_rubric": data.grading_rubric,
        "auto_grade": data.auto_grade,
        "status": data.status,
    }
    created = await db.create_assignment(payload)
    if not created:
        raise HTTPException(500, "Failed to create assignment")
    if data.generate_pdf:
        try:
            full_assignment = await db.get_assignment(str(created["id"])) or created
            pdf_update = _save_assignment_pdf(full_assignment, current_user, data.generated_outline or {})
            await db.update_assignment(str(created["id"]), pdf_update)
            created = await db.get_assignment(str(created["id"])) or created
        except Exception as e:
            logger.warning(f"Assignment PDF generation failed for {created['id']}: {e}")
    return _ser(created)

@router.get("/")
async def list_assignments(
    class_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(require_teacher()),
):
    db = await get_database()
    rows = await db.get_assignments(current_user["id"], class_id=class_id, subject_id=subject_id, status=status)
    return [_ser(r) for r in rows]

@router.get("/{assignment_id}")
async def get_assignment(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _own(db, current_user, assignment_id)
    return _ser(a)

@router.patch("/{assignment_id}")
async def update_assignment(assignment_id: str, data: AssignmentUpdate, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    existing = await _own(db, current_user, assignment_id)
    upd = {k: v for k, v in data.dict().items() if v is not None}
    next_class_id = upd.get("class_id") or str(existing["class_id"])
    next_subject_id = upd.get("subject_id") or str(existing["subject_id"])
    await _validate_assignment_scope(db, current_user, next_class_id, next_subject_id)
    if "due_date" in upd:
        upd["due_date"] = _parse_due(upd["due_date"])
    if "instructions" in upd:
        upd["instructions"] = _clean_email_submission_copy(upd["instructions"])
    updated = await db.update_assignment(assignment_id, upd)
    return _ser(updated)

@router.delete("/{assignment_id}")
async def delete_assignment(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _own(db, current_user, assignment_id)
    await db.delete_assignment(assignment_id)
    return {"deleted": True}

@router.post("/{assignment_id}/publish")
async def publish_assignment(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _own(db, current_user, assignment_id)
    updated = await db.update_assignment(assignment_id, {"status": "published"})
    # Notify
    try:
        from services.notification_service import notify
        due_str = f" (due {a['due_date'].strftime('%b %d')}" + ")" if a.get("due_date") else ""
        await notify(
            teacher_id=current_user["id"],
            title="Assignment published",
            message=f'"{a["title"]}" has been published{due_str}. Students can now see and submit it.',
            notification_type="assignment_published",
            metadata={"assignment_id": assignment_id, "title": a.get("title", "")},
        )
    except Exception:
        pass
    return _ser(updated)

@router.post("/{assignment_id}/close")
async def close_assignment(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _own(db, current_user, assignment_id)
    updated = await db.update_assignment(assignment_id, {"status": "closed"})
    return _ser(updated)

@router.post("/{assignment_id}/upload-attachment")
async def upload_attachment(assignment_id: str, file: UploadFile = File(...), current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _own(db, current_user, assignment_id)
    d = os.path.join("uploads", "assignments", assignment_id)
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, file.filename)
    with open(fp, "wb") as f:
        f.write(await file.read())
    updated = await db.update_assignment(assignment_id, {
        "attachment_url": f"/static/uploads/assignments/{assignment_id}/{file.filename}",
        "attachment_filename": file.filename,
    })
    return _ser(updated)


# ─── Submissions ───────────────────────────────────────────────────────────────

@router.post("/{assignment_id}/generate-pdf")
async def generate_assignment_pdf(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _own(db, current_user, assignment_id)
    assignment = await db.get_assignment(assignment_id)
    try:
        pdf_update = _save_assignment_pdf(assignment, current_user, {})
        await db.update_assignment(assignment_id, pdf_update)
        updated = await db.get_assignment(assignment_id)
        return _ser(updated or assignment)
    except Exception as e:
        logger.error(f"Assignment PDF generation failed for {assignment_id}: {e}")
        raise HTTPException(500, "Failed to generate assignment PDF")


@router.get("/{assignment_id}/submissions")
async def list_submissions(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _own(db, current_user, assignment_id)
    subs = await db.get_assignment_submissions(assignment_id)
    return [_ser_sub(s) for s in subs]

@router.get("/{assignment_id}/submissions/{submission_id}")
async def get_submission(assignment_id: str, submission_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _own(db, current_user, assignment_id)
    sub = await db.get_assignment_submission(submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    return _ser_sub(sub)

@router.post("/{assignment_id}/submissions/{submission_id}/grade")
async def grade_one(assignment_id: str, submission_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _own(db, current_user, assignment_id)
    sub = await db.get_assignment_submission(submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    if not sub.get("submission_text") and not sub.get("submission_files"):
        raise HTTPException(400, "Submission has no content to grade")
    await db.update_assignment_submission(submission_id, {"status": "grading"})
    try:
        updated = await _do_grade(db, a, sub)
        # Notify
        try:
            from services.notification_service import notify
            marks = updated.get("marks_obtained") if updated else None
            pct = updated.get("percentage") if updated else None
            detail = f" — {marks}/{a.get('total_marks', '?')} ({round(pct)}%)" if marks is not None and pct is not None else ""
            await notify(
                teacher_id=current_user["id"],
                title="Submission graded",
                message=f'Submission for "{a["title"]}" graded{detail}.',
                notification_type="assignment_graded",
                metadata={"assignment_id": assignment_id, "submission_id": submission_id},
            )
        except Exception:
            pass
        return _ser_sub(updated)
    except Exception as e:
        await db.update_assignment_submission(submission_id, {"status": "submitted"})
        logger.error(f"Grading failed for {submission_id}: {e}")
        raise HTTPException(500, f"Grading failed: {str(e)}")

@router.patch("/{assignment_id}/submissions/{submission_id}/override")
async def override_grade(assignment_id: str, submission_id: str, data: OverrideRequest, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _own(db, current_user, assignment_id)
    upd = {"status": "returned"}
    if data.teacher_override_marks is not None:
        upd["teacher_override_marks"] = data.teacher_override_marks
    if data.teacher_remarks is not None:
        upd["teacher_remarks"] = data.teacher_remarks
    updated = await db.update_assignment_submission(submission_id, upd)
    if not updated:
        raise HTTPException(500, "Failed to update")
    return _ser_sub(updated)

@router.post("/{assignment_id}/grade-all")
async def grade_all(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _own(db, current_user, assignment_id)
    subs = await db.get_assignment_submissions(assignment_id)
    to_grade = [s for s in subs if s.get("status") == "submitted"]
    if not to_grade:
        return {"graded_count": 0, "failed_count": 0, "total": 0, "message": "No ungraded submissions"}
    graded, failed = 0, 0
    for sub in to_grade:
        try:
            await db.update_assignment_submission(str(sub["id"]), {"status": "grading"})
            await _do_grade(db, a, sub)
            graded += 1
        except Exception as e:
            logger.error(f"Grade-all failed for {sub['id']}: {e}")
            await db.update_assignment_submission(str(sub["id"]), {"status": "submitted"})
            failed += 1
    # Notify
    if graded > 0:
        try:
            from services.notification_service import notify
            await notify(
                teacher_id=current_user["id"],
                title="Batch grading complete",
                message=f'"{a["title"]}" — {graded}/{len(to_grade)} submissions graded' + (f', {failed} failed' if failed else '') + '.',
                notification_type="assignment_graded",
                metadata={"assignment_id": assignment_id, "graded": graded, "failed": failed},
            )
        except Exception:
            pass
    return {"graded_count": graded, "failed_count": failed, "total": len(to_grade)}

@router.get("/{assignment_id}/analytics")
async def get_analytics(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _own(db, current_user, assignment_id)
    subs = await db.get_assignment_submissions(assignment_id)
    students = await db.get_students(str(a["class_id"]))
    graded = [s for s in subs if s.get("status") in ("graded", "returned")]
    scores = [float(s["marks_obtained"]) for s in graded if s.get("marks_obtained") is not None]
    avg = round(sum(scores) / len(scores), 2) if scores else 0
    grade_dist: dict = {}
    for s in graded:
        g = s.get("grade", "N/A")
        grade_dist[g] = grade_dist.get(g, 0) + 1
    pass_count = sum(1 for s in graded if s.get("percentage") and float(s["percentage"]) >= 50)
    submitted = [s for s in subs if s.get("status") != "pending"]
    return {
        "total_students": len(students),
        "submitted_count": len(submitted),
        "graded_count": len(graded),
        "total_submissions": len(subs),
        "submission_rate": round(len(submitted) / max(len(students), 1) * 100, 1),
        "average_score": avg,
        "avg_score": avg,
        "pass_rate": round(pass_count / max(len(graded), 1) * 100, 1),
        "grade_distribution": grade_dist,
    }


# ─── Manual Upload ─────────────────────────────────────────────────────────────

@router.post("/{assignment_id}/manual-upload")
async def manual_upload(
    assignment_id: str,
    student_id: Optional[str] = Form(None),
    submission_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(require_teacher()),
):
    db = await get_database()
    a = await _own(db, current_user, assignment_id)
    if not student_id:
        raise HTTPException(400, "Please select a student from the class roster")
    roster_student = await _resolve_roster_student_for_submission(db, str(a["class_id"]), student_id)
    file_paths = []
    if file and file.filename:
        d = os.path.join("uploads", "submissions", assignment_id)
        os.makedirs(d, exist_ok=True)
        fp = os.path.join(d, file.filename.replace(" ", "_"))
        with open(fp, "wb") as f:
            f.write(await file.read())
        file_paths.append(f"/static/uploads/submissions/{assignment_id}/{file.filename.replace(' ', '_')}")

    sub = await db.create_assignment_submission({
        "assignment_id": assignment_id,
        "student_id": str(roster_student["id"]),
        "class_id": str(a["class_id"]),
        "submission_text": submission_text or "",
        "submission_files": file_paths,
        "status": "submitted",
        "submitted_at": datetime.utcnow(),
        "source": "manual",
    })
    if not sub:
        raise HTTPException(500, "Failed to create submission")

    if a.get("auto_grade") and (submission_text or file_paths):
        try:
            await db.update_assignment_submission(str(sub["id"]), {"status": "grading"})
            sub = await _do_grade(db, a, sub)
        except Exception as e:
            logger.warning(f"Auto-grade on manual upload failed: {e}")
            await db.update_assignment_submission(str(sub["id"]), {"status": "submitted"})
    return _ser_sub(sub)


# ─── Email Fetch ───────────────────────────────────────────────────────────────

@router.post("/{assignment_id}/fetch-email-submissions")
async def fetch_email_submissions(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _own(db, current_user, assignment_id)
    config = await db.get_email_config(current_user["id"])
    if not config:
        raise HTTPException(400, "No email config. Please configure email integration first.")
    if not config.get("is_active"):
        raise HTTPException(400, "Email integration is disabled.")
    from services.email_service import EmailFetcher
    fetcher = EmailFetcher(config["email_address"], config["app_password"], config["imap_host"], config["imap_port"])
    assignment_code = _assignment_email_code(assignment_id)
    try:
        emails = fetcher.fetch_assignment_emails(a["title"], assignment_id, assignment_code=assignment_code)
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch emails: {e}")

    class_id = str(a["class_id"])
    roster_students = await db.get_students(class_id)
    roster_email_to_student = {
        _normalize_email(s.get("email")): s
        for s in roster_students
        if _normalize_email(s.get("email"))
    }
    processed, skipped = 0, 0

    for mail_data in emails:
        sender = _normalize_email(mail_data.get("from_email") or mail_data.get("from_name"))
        student = roster_email_to_student.get(sender)
        log_base = {
            "teacher_id": current_user["id"],
            "assignment_id": assignment_id,
            "email_from": mail_data["from_email"],
            "email_subject": mail_data["subject"],
            "email_body": mail_data["body"][:1000],
            "attachment_paths": mail_data["attachments"],
            "processed_at": datetime.utcnow(),
        }
        if not student:
            await db.create_email_submission_log({
                **log_base,
                "status": "skipped",
                "notes": f"Assignment code matched, but the sender email is not in the teacher's roster for {a.get('class_name') or 'this class'}. Students must send from the email address saved in the class roster and use the subject {_assignment_email_subject(a.get('title') or 'Assignment', assignment_id)}.",
            })
            skipped += 1
            continue
        if not mail_data.get("body") and not mail_data.get("attachments"):
            await db.create_email_submission_log({**log_base, "student_id": str(student["id"]), "status": "skipped", "notes": "No message body or attachment found"})
            skipped += 1
            continue
        pdf_count = sum(1 for path in mail_data.get("attachments", []) if str(path).lower().endswith(".pdf"))
        sub = await db.create_assignment_submission({
            "assignment_id": assignment_id,
            "student_id": str(student["id"]),
            "class_id": str(a["class_id"]),
            "submission_text": mail_data["body"],
            "submission_files": mail_data["attachments"],
            "source": "email",
            "status": "submitted",
            "submitted_at": datetime.utcnow(),
        })
        if sub:
            notes = f"Mapped by class-roster sender email {sender} and {assignment_code} to {student.get('student_name') or 'student'}"
            notes += f" in {a.get('class_name') or 'selected class'} / {a.get('subject_name') or 'selected subject'}."
            if pdf_count:
                notes += f" Imported {pdf_count} PDF attachment{'s' if pdf_count != 1 else ''}."
            await db.create_email_submission_log({**log_base, "student_id": str(student["id"]), "status": "processed", "notes": notes})
            processed += 1
        else:
            await db.create_email_submission_log({**log_base, "student_id": str(student["id"]), "status": "failed", "notes": "Could not create or update submission"})
            skipped += 1

    await db.update_email_last_fetched(current_user["id"])
    return {"emails_found": len(emails), "processed": processed, "skipped": skipped,
            "assignment_code": assignment_code,
            "email_subject_syntax": _assignment_email_subject(a.get("title", ""), assignment_id),
            "class_name": a.get("class_name"),
            "subject_name": a.get("subject_name"),
            "message": f"Processed {processed} submissions, skipped {skipped} emails not sent from a class-roster email address"}

@router.get("/{assignment_id}/email-logs")
async def get_email_logs(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _own(db, current_user, assignment_id)
    logs = await db.get_email_submission_logs(current_user["id"], assignment_id)
    return [_ser_email_log(log) for log in logs]
