import csv
import io
import re
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, date, timedelta

from utils.security import get_current_user
from services.database import get_database, DatabaseService
from services.email_service import EmailSender

router = APIRouter()

# ─── Models ───────────────────────────────────────────────────────────────────

class AttendanceEntry(BaseModel):
    student_id: str
    status: str  # 'present', 'absent', 'late', 'excused'
    remarks: Optional[str] = None

class AttendanceBatch(BaseModel):
    class_id: str
    subject_id: str
    date: str
    entries: List[AttendanceEntry]

class AttendanceRecordResponse(BaseModel):
    id: str
    student_id: str
    status: str
    remarks: Optional[str] = None
    date: str

class AttendanceClassReportEmailRequest(BaseModel):
    class_id: str
    subject_id: str
    recipient_email: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    format: str = "pdf"

class AttendanceStudentReportEmailRequest(BaseModel):
    class_id: str
    subject_id: str
    student_id: str
    recipient_email: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

# ─── Helper ───────────────────────────────────────────────────────────────────

def _fmt(records: List[dict]) -> List[dict]:
    """Stringify date/timestamp fields so JSON serialisation never fails."""
    for r in records:
        for key in ("date", "created_at", "updated_at"):
            if r.get(key) is not None:
                r[key] = str(r[key])
    return records


def _date_range(start_date: Optional[str], end_date: Optional[str], days: int = 90) -> tuple[str, str]:
    """Normalize optional report date filters."""
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=days)).isoformat()
    return start_date, end_date


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _filename(value: str, extension: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", value or "attendance_report").strip("_")
    return f"{slug[:120] or 'attendance_report'}.{extension}"


def _valid_email(value: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (value or "").strip()))


def _fmt_pct(value: Any) -> str:
    return f"{_safe_float(value):.1f}%"


def _fmt_num(value: Any) -> str:
    number = _safe_float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")


def _esc(value: Any) -> str:
    from xml.sax.saxutils import escape
    return escape(str(value or ""))


async def _validate_report_scope(db: DatabaseService, teacher_id: str, class_id: str, subject_id: str) -> tuple[dict, dict]:
    cls = await db.get_class(class_id)
    if not cls or str(cls.get("teacher_id")) != str(teacher_id):
        raise HTTPException(status_code=403, detail="Access denied to this class")

    subject = await db.get_subject(subject_id)
    if not subject or str(subject.get("teacher_id")) != str(teacher_id):
        raise HTTPException(status_code=403, detail="Access denied to this subject")

    subject_class_id = str(subject.get("class_id")) if subject.get("class_id") else None
    if subject_class_id and subject_class_id != class_id:
        raise HTTPException(status_code=400, detail="Selected subject does not belong to the selected class")
    return cls, subject


async def _build_attendance_class_report_data(
    db: DatabaseService,
    teacher: dict,
    class_id: str,
    subject_id: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> Dict[str, Any]:
    start_date, end_date = _date_range(start_date, end_date)
    cls, subject = await _validate_report_scope(db, teacher["id"], class_id, subject_id)

    roster = await db.get_students(class_id)
    summary_rows = await db.get_students_attendance_summary(
        teacher_id=teacher["id"],
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    analytics = await db.get_class_attendance_analytics(
        teacher_id=teacher["id"],
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    ) or {}
    by_student = {str(row.get("student_id")): row for row in summary_rows}

    rows = []
    for student in roster:
        sid = str(student.get("id"))
        source = by_student.get(sid, {})
        present = _safe_int(source.get("present"))
        absent = _safe_int(source.get("absent"))
        late = _safe_int(source.get("late"))
        excused = _safe_int(source.get("excused"))
        total = _safe_int(source.get("total"))
        pct = _safe_float(source.get("attendance_pct"))
        if total == 0:
            pct = 0.0
        status = "Good"
        if pct < 75:
            status = "At risk"
        elif pct < 90:
            status = "Watch"
        rows.append({
            "student_id": sid,
            "student_name": student.get("student_name") or "Student",
            "roll_number": student.get("student_id") or "",
            "email": student.get("email") or "",
            "present": present,
            "absent": absent,
            "late": late,
            "excused": excused,
            "total": total,
            "attendance_pct": round(pct, 1),
            "status": status,
        })

    rows.sort(key=lambda row: (str(row.get("roll_number") or "").lower(), str(row.get("student_name") or "").lower()))
    percentages = [row["attendance_pct"] for row in rows if row["total"] > 0]
    summary = {
        "total_students": len(roster),
        "total_sessions": _safe_int(analytics.get("total_sessions")),
        "total_records": _safe_int(analytics.get("total_records")),
        "present": _safe_int(analytics.get("present")),
        "absent": _safe_int(analytics.get("absent")),
        "late": _safe_int(analytics.get("late")),
        "excused": _safe_int(analytics.get("excused")),
        "overall_rate": round(_safe_float(analytics.get("overall_rate")), 1),
        "average_student_attendance": round(sum(percentages) / len(percentages), 1) if percentages else 0.0,
        "at_risk_count": len([row for row in rows if row["total"] > 0 and row["attendance_pct"] < 75]),
        "not_recorded_count": len([row for row in rows if row["total"] == 0]),
    }

    return {
        "class": {
            "id": str(cls.get("id")),
            "name": cls.get("name") or "Class",
            "grade_level": cls.get("grade_level") or "",
            "academic_year": cls.get("academic_year") or "",
        },
        "subject": {
            "id": str(subject.get("id")),
            "name": subject.get("name") or "Subject",
        },
        "teacher": {
            "name": teacher.get("name") or teacher.get("full_name") or teacher.get("email") or "Teacher",
            "email": teacher.get("email") or "",
        },
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "summary": summary,
        "rows": rows,
    }


async def _build_attendance_student_report_data(
    db: DatabaseService,
    teacher: dict,
    class_id: str,
    subject_id: str,
    student_id: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> Dict[str, Any]:
    start_date, end_date = _date_range(start_date, end_date)
    cls, subject = await _validate_report_scope(db, teacher["id"], class_id, subject_id)
    student = await db.get_student(student_id)
    if not student or str(student.get("class_id")) != class_id:
        raise HTTPException(status_code=404, detail="Student was not found in this class roster")
    analytics = await db.get_student_attendance_analytics(
        teacher_id=teacher["id"],
        student_id=student_id,
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    ) or {}
    return {
        "class": {"id": str(cls.get("id")), "name": cls.get("name") or "Class"},
        "subject": {"id": str(subject.get("id")), "name": subject.get("name") or "Subject"},
        "teacher": {
            "name": teacher.get("name") or teacher.get("full_name") or teacher.get("email") or "Teacher",
            "email": teacher.get("email") or "",
        },
        "student": {
            "id": str(student.get("id")),
            "name": student.get("student_name") or analytics.get("student_name") or "Student",
            "roll_number": student.get("student_id") or analytics.get("roll_number") or "",
            "email": student.get("email") or "",
        },
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "analytics": analytics,
    }


def _attendance_csv_file(report: Dict[str, Any]) -> tuple[bytes, str, str]:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Attendance Class Report"])
    writer.writerow(["Class", report["class"]["name"], "Subject", report["subject"]["name"]])
    writer.writerow(["Teacher", report["teacher"]["name"], "From", report["start_date"], "To", report["end_date"]])
    writer.writerow(["Generated", report["generated_at"]])
    writer.writerow([])
    writer.writerow(["Summary"])
    for key, value in report["summary"].items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(["Roll No", "Student Name", "Email", "Present", "Absent", "Late", "Excused", "Recorded Sessions", "Attendance %", "Status"])
    for row in report["rows"]:
        writer.writerow([
            row.get("roll_number") or "",
            row.get("student_name") or "",
            row.get("email") or "",
            row.get("present") or 0,
            row.get("absent") or 0,
            row.get("late") or 0,
            row.get("excused") or 0,
            row.get("total") or 0,
            row.get("attendance_pct") or 0,
            row.get("status") or "",
        ])
    filename = _filename(f"{report['class']['name']}_{report['subject']['name']}_attendance_report", "csv")
    return output.getvalue().encode("utf-8-sig"), filename, "text/csv"


def _attendance_class_pdf_file(report: Dict[str, Any]) -> tuple[bytes, str, str]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF report dependency is not available: {exc}")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=0.35 * inch, rightMargin=0.35 * inch, topMargin=0.35 * inch, bottomMargin=0.45 * inch)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("AttendanceTitle", parent=styles["Title"], fontSize=18, leading=22, textColor=colors.HexColor("#0f172a"), alignment=TA_CENTER)
    muted = ParagraphStyle("AttendanceMuted", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#475569"), alignment=TA_CENTER)
    small = ParagraphStyle("AttendanceSmall", parent=styles["BodyText"], fontSize=7, leading=8, textColor=colors.HexColor("#0f172a"), alignment=TA_LEFT)
    small_center = ParagraphStyle("AttendanceSmallCenter", parent=small, alignment=TA_CENTER)
    section = ParagraphStyle("AttendanceSection", parent=styles["Heading2"], fontSize=10, leading=12, textColor=colors.HexColor("#0A66C2"))

    def p(value: Any, style=small):
        return Paragraph(_esc(value), style)

    story = [
        Paragraph("Attendance Class Report", title),
        Paragraph(_esc(f"{report['class']['name']} / {report['subject']['name']} / {report['start_date']} to {report['end_date']}"), muted),
        Spacer(1, 0.08 * inch),
    ]
    meta_rows = [
        ["Class", report["class"]["name"], "Subject", report["subject"]["name"]],
        ["Teacher", report["teacher"]["name"], "Generated", report["generated_at"]],
    ]
    meta = Table([[p(cell, small_center if i % 2 == 0 else small) for i, cell in enumerate(row)] for row in meta_rows], colWidths=[0.9 * inch, 3.8 * inch, 0.95 * inch, 3.8 * inch])
    meta.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dbeafe")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eff6ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(meta)
    story.append(Paragraph("Summary", section))
    s = report["summary"]
    summary = Table([
        [p("Students", small_center), p(s["total_students"], small_center), p("Sessions", small_center), p(s["total_sessions"], small_center), p("Overall", small_center), p(_fmt_pct(s["overall_rate"]), small_center)],
        [p("Present", small_center), p(s["present"], small_center), p("Absent", small_center), p(s["absent"], small_center), p("At Risk", small_center), p(s["at_risk_count"], small_center)],
        [p("Late", small_center), p(s["late"], small_center), p("Excused", small_center), p(s["excused"], small_center), p("Avg Student", small_center), p(_fmt_pct(s["average_student_attendance"]), small_center)],
    ], colWidths=[1.15 * inch] * 6)
    summary.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(summary)
    story.append(Paragraph("Student Attendance", section))
    rows = [["Roll", "Student", "Email", "Present", "Absent", "Late", "Excused", "Sessions", "%", "Status"]]
    for row in report["rows"]:
        rows.append([
            p(row.get("roll_number") or "-", small_center),
            p(row.get("student_name") or "-", small),
            p(row.get("email") or "-", small),
            p(row.get("present"), small_center),
            p(row.get("absent"), small_center),
            p(row.get("late"), small_center),
            p(row.get("excused"), small_center),
            p(row.get("total"), small_center),
            p(_fmt_pct(row.get("attendance_pct")), small_center),
            p(row.get("status") or "-", small_center),
        ])
    if len(rows) == 1:
        rows.append([p("No students found in this class.", small_center), "", "", "", "", "", "", "", "", ""])
    table = Table(rows, repeatRows=1, colWidths=[0.65 * inch, 1.5 * inch, 2.0 * inch, 0.62 * inch, 0.62 * inch, 0.55 * inch, 0.62 * inch, 0.7 * inch, 0.55 * inch, 0.8 * inch])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0A66C2")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(table)

    def footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(doc.leftMargin, 0.22 * inch, f"Generated {report['generated_at']}")
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.22 * inch, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    filename = _filename(f"{report['class']['name']}_{report['subject']['name']}_attendance_report", "pdf")
    return buffer.getvalue(), filename, "application/pdf"


def _attendance_student_pdf_file(report: Dict[str, Any]) -> tuple[bytes, str, str]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF report dependency is not available: {exc}")

    data = report["analytics"] or {}
    student = report["student"]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=0.45 * inch, rightMargin=0.45 * inch, topMargin=0.45 * inch, bottomMargin=0.45 * inch)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("StudentAttendanceTitle", parent=styles["Title"], fontSize=18, leading=22, textColor=colors.HexColor("#0f172a"), alignment=TA_CENTER)
    muted = ParagraphStyle("StudentAttendanceMuted", parent=styles["BodyText"], fontSize=9, leading=11, textColor=colors.HexColor("#475569"), alignment=TA_CENTER)
    small = ParagraphStyle("StudentAttendanceSmall", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#0f172a"), alignment=TA_LEFT)
    small_center = ParagraphStyle("StudentAttendanceSmallCenter", parent=small, alignment=TA_CENTER)
    section = ParagraphStyle("StudentAttendanceSection", parent=styles["Heading2"], fontSize=11, leading=13, textColor=colors.HexColor("#0A66C2"))

    def p(value: Any, style=small):
        return Paragraph(_esc(value), style)

    story = [
        Paragraph("Student Attendance Report", title),
        Paragraph(_esc(f"{student['name']} / {report['class']['name']} / {report['subject']['name']}"), muted),
        Paragraph(_esc(f"{report['start_date']} to {report['end_date']}"), muted),
        Spacer(1, 0.1 * inch),
    ]
    meta = Table([
        [p("Student", small_center), p(student["name"]), p("Roll No", small_center), p(student.get("roll_number") or "-")],
        [p("Class", small_center), p(report["class"]["name"]), p("Subject", small_center), p(report["subject"]["name"])],
        [p("Teacher", small_center), p(report["teacher"]["name"]), p("Generated", small_center), p(report["generated_at"])],
    ], colWidths=[0.9 * inch, 2.4 * inch, 0.9 * inch, 2.4 * inch])
    meta.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dbeafe")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eff6ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
    ]))
    story.append(meta)
    story.append(Paragraph("Summary", section))
    summary = Table([
        [p("Present", small_center), p(data.get("present", 0), small_center), p("Absent", small_center), p(data.get("absent", 0), small_center)],
        [p("Late", small_center), p(data.get("late", 0), small_center), p("Excused", small_center), p(data.get("excused", 0), small_center)],
        [p("Sessions", small_center), p(data.get("total_sessions", 0), small_center), p("Attendance", small_center), p(_fmt_pct(data.get("attendance_pct", 0)), small_center)],
    ], colWidths=[1.2 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch])
    summary.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(summary)

    records = data.get("records") or []
    story.append(Paragraph("Attendance Records", section))
    rows = [["Date", "Status", "Remarks"]]
    for record in records:
        rows.append([
            p(record.get("date") or "", small_center),
            p(str(record.get("status") or "").title(), small_center),
            p(record.get("remarks") or "-"),
        ])
    if len(rows) == 1:
        rows.append([p("No attendance records found in this date range.", small_center), "", ""])
    table = Table(rows, repeatRows=1, colWidths=[1.2 * inch, 1.1 * inch, 4.1 * inch])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0A66C2")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(table)
    doc.build(story)
    filename = _filename(f"{student['name']}_attendance_report", "pdf")
    return buffer.getvalue(), filename, "application/pdf"


def _file_response(content: bytes, filename: str, media_type: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _email_sender_from_config(config: dict) -> EmailSender:
    return EmailSender(
        config["email_address"],
        config["app_password"],
        config.get("smtp_host") or "smtp.gmail.com",
        config.get("smtp_port") or 587,
        config.get("smtp_use_tls", True),
        config.get("smtp_use_ssl", False),
        config.get("from_name") or "EduMaster Reports",
    )


async def _send_report_email(db: DatabaseService, teacher_id: str, recipient_email: str, subject: str, body: str, attachment: tuple[bytes, str, str]) -> Dict[str, Any]:
    if not _valid_email(recipient_email):
        raise HTTPException(status_code=400, detail="Enter a valid recipient email address")
    config = await db.get_email_config(teacher_id)
    if not config or not config.get("is_active"):
        raise HTTPException(status_code=400, detail="Configure and enable teacher email SMTP settings before sending reports")
    sender = _email_sender_from_config(config)
    content, filename, media_type = attachment
    result = sender.send_email(
        recipient_email,
        subject,
        body,
        [{"filename": filename, "content": content, "media_type": media_type}],
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message") or "Report email could not be sent")
    return result


# Reports

@router.get("/reports/class")
async def download_attendance_class_report(
    class_id: str,
    subject_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    format: str = Query("pdf", pattern="^(pdf|csv)$"),
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    report = await _build_attendance_class_report_data(db, current_user, class_id, subject_id, start_date, end_date)
    if format.lower() == "csv":
        return _file_response(*_attendance_csv_file(report))
    return _file_response(*_attendance_class_pdf_file(report))


@router.post("/reports/class/send")
async def send_attendance_class_report(
    request: AttendanceClassReportEmailRequest,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    report = await _build_attendance_class_report_data(
        db,
        current_user,
        request.class_id,
        request.subject_id,
        request.start_date,
        request.end_date,
    )
    attachment = _attendance_csv_file(report) if request.format.lower() == "csv" else _attendance_class_pdf_file(report)
    content, filename, media_type = attachment
    subject = f"Attendance Report - {report['class']['name']} - {report['subject']['name']}"
    body = (
        f"Attached is the attendance report for {report['class']['name']} / {report['subject']['name']} "
        f"from {report['start_date']} to {report['end_date']}.\n\n"
        f"Students: {report['summary']['total_students']}\n"
        f"Overall attendance: {_fmt_pct(report['summary']['overall_rate'])}\n"
        f"At-risk students: {report['summary']['at_risk_count']}\n"
    )
    await _send_report_email(db, current_user["id"], request.recipient_email, subject, body, (content, filename, media_type))
    return {"status": "success", "message": f"Attendance report sent to {request.recipient_email}"}


@router.post("/reports/student/send")
async def send_attendance_student_report(
    request: AttendanceStudentReportEmailRequest,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    report = await _build_attendance_student_report_data(
        db,
        current_user,
        request.class_id,
        request.subject_id,
        request.student_id,
        request.start_date,
        request.end_date,
    )
    recipient = (request.recipient_email or report["student"].get("email") or "").strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="This student has no roster email. Enter a recipient email address.")
    content, filename, media_type = _attendance_student_pdf_file(report)
    subject = f"Attendance Report - {report['student']['name']} - {report['subject']['name']}"
    analytics = report["analytics"] or {}
    body = (
        f"Attached is the attendance report for {report['student']['name']} "
        f"({report['class']['name']} / {report['subject']['name']}) from {report['start_date']} to {report['end_date']}.\n\n"
        f"Attendance: {_fmt_pct(analytics.get('attendance_pct', 0))}\n"
        f"Present: {analytics.get('present', 0)}\n"
        f"Absent: {analytics.get('absent', 0)}\n"
        f"Late: {analytics.get('late', 0)}\n"
    )
    await _send_report_email(db, current_user["id"], recipient, subject, body, (content, filename, media_type))
    return {"status": "success", "message": f"Student attendance report sent to {recipient}"}


# ─── Basic CRUD ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def get_attendance(
    class_id: str,
    subject_id: str,
    date: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Get attendance for a specific class, subject, and date."""
    records = await db.get_attendance_records(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        date=date
    )
    return _fmt(records)


@router.post("/", response_model=dict)
async def submit_attendance(
    batch: AttendanceBatch,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Submit or update attendance for a batch of students."""
    teacher_id = current_user["id"]
    success_count = 0
    failed_count = 0

    for entry in batch.entries:
        data = {
            "teacher_id": teacher_id,
            "class_id": batch.class_id,
            "subject_id": batch.subject_id,
            "student_id": entry.student_id,
            "date": batch.date,
            "status": entry.status,
            "remarks": entry.remarks,
        }
        res = await db.upsert_attendance_record(data)
        if res:
            success_count += 1
        else:
            failed_count += 1

    # Fire notification
    if success_count > 0:
        absent_count = sum(1 for e in batch.entries if e.status == "absent")
        late_count   = sum(1 for e in batch.entries if e.status == "late")
        summary_parts = []
        if absent_count:
            summary_parts.append(f"{absent_count} absent")
        if late_count:
            summary_parts.append(f"{late_count} late")
        summary = f" ({', '.join(summary_parts)})" if summary_parts else ""

        try:
            from services.notification_service import notify
            await notify(
                teacher_id=teacher_id,
                title="Attendance saved",
                message=f"Attendance for {batch.date} saved — {success_count} students recorded{summary}.",
                notification_type="attendance_saved",
                metadata={
                    "class_id": batch.class_id,
                    "subject_id": batch.subject_id,
                    "date": batch.date,
                    "total": success_count,
                    "absent": absent_count,
                    "late": late_count,
                },
            )
        except Exception:
            pass

    return {
        "status": "success",
        "message": f"Successfully updated {success_count} records.",
        "failed": failed_count,
    }


# ─── Range / History Queries ──────────────────────────────────────────────────

@router.get("/range", response_model=List[dict])
async def get_attendance_range(
    class_id: str,
    subject_id: str,
    start_date: str,
    end_date: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Get all attendance records for a date range."""
    records = await db.get_attendance_range(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    return _fmt(records)


@router.get("/history", response_model=List[dict])
async def get_attendance_history(
    class_id: str,
    subject_id: str,
    limit: int = Query(default=30, le=90),
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    Return the last *limit* distinct session dates that have attendance records,
    together with the per-date summary (present/absent/late/excused counts).
    """
    data = await db.get_attendance_history(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        limit=limit,
    )
    return data


# ─── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics/class", response_model=dict)
async def get_class_analytics(
    class_id: str,
    subject_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    Full analytics for a class/subject:
    - Overall totals (present / absent / late / excused)
    - Attendance rate per session (for trend charts)
    - Status distribution
    - Students with attendance < 75%
    - Most-absent students
    """
    # Default to the last 30 days if no range provided
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()

    analytics = await db.get_class_attendance_analytics(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    return analytics


@router.get("/analytics/student/{student_id}", response_model=dict)
async def get_student_analytics(
    student_id: str,
    class_id: str,
    subject_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    Detailed attendance analytics for a single student:
    - Total sessions, present/absent/late/excused counts
    - Attendance percentage
    - Full record list for the range
    - Monthly breakdown
    """
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=90)).isoformat()

    analytics = await db.get_student_attendance_analytics(
        teacher_id=current_user["id"],
        student_id=student_id,
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    return analytics


@router.get("/analytics/overview", response_model=dict)
async def get_attendance_overview(
    class_id: str,
    subject_id: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    High-level overview: total sessions taken, overall attendance %, 
    students below threshold, heatmap data for last 12 weeks.
    """
    overview = await db.get_attendance_overview(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
    )
    return overview


@router.get("/students/summary", response_model=List[dict])
async def get_students_summary(
    class_id: str,
    subject_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """
    Per-student attendance summary for a class/subject:
    returns each student's present/absent/late/excused count and attendance %.
    """
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=90)).isoformat()

    summary = await db.get_students_attendance_summary(
        teacher_id=current_user["id"],
        class_id=class_id,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date,
    )
    return summary
