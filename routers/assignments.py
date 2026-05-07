"""
Assignments API — Teacher CRUD + publish/close + submissions + AI grading
+ Email integration (IMAP fetch) + Manual upload by teacher
"""
import logging, os, uuid, json
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from utils.security import require_teacher
from services.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Models ──────────────────────────────────────────────────────────────────

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

class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    total_marks: Optional[int] = None
    due_date: Optional[str] = None
    grading_rubric: Optional[str] = None
    auto_grade: Optional[bool] = None

class OverrideRequest(BaseModel):
    teacher_override_marks: Optional[float] = None
    teacher_remarks: Optional[str] = None

class EmailConfigRequest(BaseModel):
    email_address: str
    app_password: str
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ser_assignment(a: dict) -> dict:
    return {
        "id": str(a["id"]),
        "teacher_id": str(a["teacher_id"]),
        "subject_id": str(a["subject_id"]),
        "class_id": str(a["class_id"]),
        "title": a.get("title", ""),
        "description": a.get("description"),
        "instructions": a.get("instructions"),
        "total_marks": a.get("total_marks", 10),
        "due_date": str(a["due_date"]) if a.get("due_date") else None,
        "attachment_url": a.get("attachment_url"),
        "attachment_filename": a.get("attachment_filename"),
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
        "student_account_id": str(s["student_account_id"]),
        "student_name": s.get("student_name", ""),
        "student_email": s.get("student_email", ""),
        "roll_number": s.get("roll_number"),
        "class_id": str(s["class_id"]),
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
        "source": s.get("source", "direct"),
    }

def _parse_due(due_date_str):
    if not due_date_str:
        return None
    try:
        return datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
    except:
        return None

async def _verify_owner(db, current_user, assignment_id):
    a = await db.get_assignment(assignment_id)
    if not a:
        raise HTTPException(404, "Assignment not found")
    if str(a["teacher_id"]) != current_user["id"]:
        raise HTTPException(403, "Access denied")
    return a


# ─── Assignment CRUD ──────────────────────────────────────────────────────────

@router.post("/")
async def create_assignment(data: AssignmentCreate, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    payload = {
        "teacher_id": current_user["id"],
        "subject_id": data.subject_id,
        "class_id": data.class_id,
        "title": data.title,
        "description": data.description,
        "instructions": data.instructions,
        "total_marks": data.total_marks,
        "due_date": _parse_due(data.due_date),
        "grading_rubric": data.grading_rubric,
        "auto_grade": data.auto_grade,
        "status": data.status,
    }
    created = await db.create_assignment(payload)
    if not created:
        raise HTTPException(500, "Failed to create assignment")
    return _ser_assignment(created)

@router.get("/")
async def list_assignments(class_id: Optional[str] = None, subject_id: Optional[str] = None,
                           status: Optional[str] = None, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    rows = await db.get_assignments(current_user["id"], class_id=class_id, subject_id=subject_id, status=status)
    return [_ser_assignment(r) for r in rows]

@router.get("/{assignment_id}")
async def get_assignment(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _verify_owner(db, current_user, assignment_id)
    return _ser_assignment(a)

@router.patch("/{assignment_id}")
async def update_assignment(assignment_id: str, data: AssignmentUpdate, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
    upd = {k: v for k, v in data.dict().items() if v is not None}
    if "due_date" in upd:
        upd["due_date"] = _parse_due(upd["due_date"])
    updated = await db.update_assignment(assignment_id, upd)
    return _ser_assignment(updated)

@router.delete("/{assignment_id}")
async def delete_assignment(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
    await db.delete_assignment(assignment_id)
    return {"deleted": True}

@router.post("/{assignment_id}/publish")
async def publish_assignment(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
    updated = await db.update_assignment(assignment_id, {"status": "published"})
    return _ser_assignment(updated)

@router.post("/{assignment_id}/close")
async def close_assignment(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
    updated = await db.update_assignment(assignment_id, {"status": "closed"})
    return _ser_assignment(updated)

@router.post("/{assignment_id}/upload-attachment")
async def upload_assignment_attachment(assignment_id: str, file: UploadFile = File(...),
                                       current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
    upload_dir = os.path.join("uploads", "assignments", assignment_id)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    updated = await db.update_assignment(assignment_id, {
        "attachment_url": f"/static/uploads/assignments/{assignment_id}/{file.filename}",
        "attachment_filename": file.filename,
    })
    return _ser_assignment(updated)


# ─── Submissions ──────────────────────────────────────────────────────────────

@router.get("/{assignment_id}/submissions")
async def list_submissions(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
    subs = await db.get_assignment_submissions(assignment_id)
    return [_ser_sub(s) for s in subs]

@router.get("/{assignment_id}/submissions/{submission_id}")
async def get_submission(assignment_id: str, submission_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
    sub = await db.get_assignment_submission(submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    return _ser_sub(sub)

@router.post("/{assignment_id}/submissions/{submission_id}/grade")
async def grade_single(assignment_id: str, submission_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _verify_owner(db, current_user, assignment_id)
    sub = await db.get_assignment_submission(submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    await db.update_assignment_submission(submission_id, {"status": "grading"})
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
    updated = await db.update_assignment_submission(submission_id, upd)
    try:
        await db.create_student_score({
            "student_account_id": str(sub["student_account_id"]),
            "class_id": str(a["class_id"]),
            "subject_id": str(a["subject_id"]),
            "score_type": "assignment",
            "reference_id": str(a["id"]),
            "title": a["title"],
            "marks_obtained": result["marks_obtained"],
            "max_marks": a.get("total_marks", 10),
            "percentage": result["percentage"],
            "grade": result["grade"],
        })
    except Exception as e:
        logger.warning(f"Could not record score: {e}")
    return _ser_sub(updated) if updated else {"status": "graded"}

@router.patch("/{assignment_id}/submissions/{submission_id}/override")
async def override_submission(assignment_id: str, submission_id: str, data: OverrideRequest,
                              current_user: dict = Depends(require_teacher())):
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
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
    a = await _verify_owner(db, current_user, assignment_id)
    subs = await db.get_assignment_submissions(assignment_id)
    to_grade = [s for s in subs if s.get("status") == "submitted"]
    if not to_grade:
        return {"graded_count": 0, "total": 0, "message": "No ungraded submissions"}
    from services.assignment_grader import grade_assignment_submission
    graded, failed = 0, 0
    for sub in to_grade:
        try:
            await db.update_assignment_submission(str(sub["id"]), {"status": "grading"})
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
            await db.update_assignment_submission(str(sub["id"]), upd)
            try:
                await db.create_student_score({
                    "student_account_id": str(sub["student_account_id"]),
                    "class_id": str(a["class_id"]),
                    "subject_id": str(a["subject_id"]),
                    "score_type": "assignment",
                    "reference_id": str(a["id"]),
                    "title": a["title"],
                    "marks_obtained": result["marks_obtained"],
                    "max_marks": a.get("total_marks", 10),
                    "percentage": result["percentage"],
                    "grade": result["grade"],
                })
            except Exception:
                pass
            graded += 1
        except Exception as e:
            logger.error(f"Grade error for {sub['id']}: {e}")
            await db.update_assignment_submission(str(sub["id"]), {"status": "submitted"})
            failed += 1
    return {"graded_count": graded, "failed_count": failed, "total": len(to_grade)}

@router.get("/{assignment_id}/analytics")
async def get_analytics(assignment_id: str, current_user: dict = Depends(require_teacher())):
    db = await get_database()
    a = await _verify_owner(db, current_user, assignment_id)
    subs = await db.get_assignment_submissions(assignment_id)
    students = await db.get_student_accounts_by_class(str(a["class_id"]))
    total_students = len(students)
    submitted = [s for s in subs if s.get("status") not in ("pending",)]
    graded = [s for s in subs if s.get("status") in ("graded", "returned")]
    scores = [float(s["marks_obtained"]) for s in graded if s.get("marks_obtained") is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0
    grade_dist = {}
    for s in graded:
        g = s.get("grade", "N/A")
        grade_dist[g] = grade_dist.get(g, 0) + 1
    pass_count = len([s for s in graded if s.get("percentage") and float(s["percentage"]) >= 50])
    return {
        "total_students": total_students,
        "submitted_count": len(submitted),
        "graded_count": len(graded),
        "submission_rate": round(len(submitted) / max(total_students, 1) * 100, 1),
        "avg_score": avg_score,
        "pass_rate": round(pass_count / max(len(graded), 1) * 100, 1),
        "grade_distribution": grade_dist,
        "total_submissions": len(subs),
        "average_score": avg_score,
    }


# ─── Manual Upload by Teacher ─────────────────────────────────────────────────

@router.post("/{assignment_id}/manual-upload")
async def manual_upload_submission(
    assignment_id: str,
    student_account_id: str = Form(...),
    submission_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(require_teacher()),
):
    """Teacher manually uploads a submission on behalf of a student."""
    db = await get_database()
    a = await _verify_owner(db, current_user, assignment_id)

    file_paths = []
    if file and file.filename:
        upload_dir = os.path.join("uploads", "submissions", assignment_id)
        os.makedirs(upload_dir, exist_ok=True)
        content = await file.read()
        safe_name = file.filename.replace(" ", "_")
        fpath = os.path.join(upload_dir, safe_name)
        with open(fpath, "wb") as f:
            f.write(content)
        file_paths.append(f"/static/uploads/submissions/{assignment_id}/{safe_name}")

    sub_data = {
        "assignment_id": assignment_id,
        "student_account_id": student_account_id,
        "class_id": str(a["class_id"]),
        "submission_text": submission_text or "",
        "submission_files": file_paths,
        "status": "submitted",
        "submitted_at": datetime.utcnow(),
        "source": "manual",
    }
    sub = await db.create_assignment_submission(sub_data)
    if not sub:
        raise HTTPException(500, "Failed to create submission")

    # Auto-grade if enabled
    if a.get("auto_grade") and (submission_text or file_paths):
        try:
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
            sub = await db.update_assignment_submission(str(sub["id"]), upd) or sub
        except Exception as e:
            logger.warning(f"Auto-grade failed: {e}")

    return _ser_sub(sub)


# ─── Email Integration ────────────────────────────────────────────────────────

@router.post("/email/config")
async def save_email_config(data: EmailConfigRequest, current_user: dict = Depends(require_teacher())):
    """Save teacher's email IMAP configuration."""
    db = await get_database()
    result = await db.save_email_config(current_user["id"], data.dict())
    if not result:
        raise HTTPException(500, "Failed to save email config")
    return {
        "id": str(result["id"]),
        "email_address": result["email_address"],
        "imap_host": result["imap_host"],
        "imap_port": result["imap_port"],
        "is_active": result["is_active"],
        "last_fetched_at": str(result["last_fetched_at"]) if result.get("last_fetched_at") else None,
    }

@router.get("/email/config")
async def get_email_config(current_user: dict = Depends(require_teacher())):
    """Get teacher's email IMAP configuration."""
    db = await get_database()
    result = await db.get_email_config(current_user["id"])
    if not result:
        return None
    return {
        "id": str(result["id"]),
        "email_address": result["email_address"],
        "imap_host": result["imap_host"],
        "imap_port": result["imap_port"],
        "is_active": result["is_active"],
        "last_fetched_at": str(result["last_fetched_at"]) if result.get("last_fetched_at") else None,
    }

@router.post("/email/test-connection")
async def test_email_connection(data: EmailConfigRequest, current_user: dict = Depends(require_teacher())):
    """Test IMAP connection with provided credentials."""
    from services.email_service import EmailFetcher
    fetcher = EmailFetcher(data.email_address, data.app_password, data.imap_host, data.imap_port)
    result = fetcher.test_connection()
    return result

@router.post("/{assignment_id}/fetch-email-submissions")
async def fetch_email_submissions(assignment_id: str, current_user: dict = Depends(require_teacher())):
    """Fetch student submissions sent via email for this assignment."""
    db = await get_database()
    a = await _verify_owner(db, current_user, assignment_id)
    config = await db.get_email_config(current_user["id"])
    if not config:
        raise HTTPException(400, "No email configuration found. Please set up email integration first.")
    if not config.get("is_active"):
        raise HTTPException(400, "Email integration is disabled.")

    from services.email_service import EmailFetcher
    fetcher = EmailFetcher(
        config["email_address"],
        config["app_password"],
        config["imap_host"],
        config["imap_port"],
    )

    try:
        emails = fetcher.fetch_assignment_emails(a["title"], assignment_id)
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch emails: {str(e)}")

    # Get students in this class to match by email
    students = await db.get_student_accounts_by_class(str(a["class_id"]))
    email_to_student = {s["email"].lower(): s for s in students if s.get("email")}

    processed, skipped = 0, 0
    for mail_data in emails:
        sender = mail_data["from_email"].lower()
        student = email_to_student.get(sender)
        if not student:
            # Log as skipped - unknown sender
            await db.create_email_submission_log({
                "teacher_id": current_user["id"],
                "assignment_id": assignment_id,
                "email_from": mail_data["from_email"],
                "email_subject": mail_data["subject"],
                "email_body": mail_data["body"][:1000],
                "attachment_paths": mail_data["attachments"],
                "processed_at": datetime.utcnow(),
                "status": "skipped",
                "notes": "Sender email not found in class roster",
            })
            skipped += 1
            continue

        # Create submission
        sub_data = {
            "assignment_id": assignment_id,
            "student_account_id": str(student["id"]),
            "class_id": str(a["class_id"]),
            "submission_text": mail_data["body"],
            "submission_files": mail_data["attachments"],
            "status": "submitted",
            "submitted_at": datetime.utcnow(),
        }
        sub = await db.create_assignment_submission(sub_data)

        if sub:
            await db.create_email_submission_log({
                "teacher_id": current_user["id"],
                "assignment_id": assignment_id,
                "student_account_id": str(student["id"]),
                "email_from": mail_data["from_email"],
                "email_subject": mail_data["subject"],
                "email_body": mail_data["body"][:1000],
                "attachment_paths": mail_data["attachments"],
                "processed_at": datetime.utcnow(),
                "status": "processed",
            })
            processed += 1

    # Update last_fetched_at
    await db.save_email_config(current_user["id"], {
        "email_address": config["email_address"],
        "app_password": config["app_password"],
        "imap_host": config["imap_host"],
        "imap_port": config["imap_port"],
        "is_active": True,
    })

    return {
        "emails_found": len(emails),
        "processed": processed,
        "skipped": skipped,
        "message": f"Processed {processed} new submissions, skipped {skipped} unknown senders",
    }

@router.get("/{assignment_id}/email-logs")
async def get_email_logs(assignment_id: str, current_user: dict = Depends(require_teacher())):
    """Get email fetch logs for an assignment."""
    db = await get_database()
    await _verify_owner(db, current_user, assignment_id)
    logs = await db.get_email_submission_logs(current_user["id"], assignment_id)
    return logs
