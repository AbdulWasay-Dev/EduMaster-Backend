"""
Student Authentication API endpoints
Separate auth flow for student accounts
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from jose import jwt
import bcrypt

from utils.security import get_current_student, require_student
from config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class StudentSignup(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None  # YYYY-MM-DD
    gender: Optional[str] = None
    roll_number: Optional[str] = None
    student_id: Optional[str] = None
    class_code: str


class StudentLogin(BaseModel):
    email: EmailStr
    password: str


class StudentProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    profile_image_url: Optional[str] = None


class StudentProfileResponse(BaseModel):
    id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    roll_number: Optional[str] = None
    student_id: Optional[str] = None
    class_id: Optional[str] = None
    class_name: Optional[str] = None
    is_verified: bool = False
    is_active: bool = True
    profile_image_url: Optional[str] = None
    joined_at: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _create_student_token(student_id: str, email: str, class_id: str = None) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes * 2)  # longer session for students
    data = {
        "sub": student_id,
        "email": email,
        "role": "student",
        "class_id": class_id or "",
        "exp": expire,
    }
    return jwt.encode(data, settings.secret_key, algorithm=settings.algorithm)


def _student_to_response(s: dict, class_name: str = None) -> dict:
    return {
        "id": str(s["id"]),
        "full_name": s.get("full_name", ""),
        "email": s.get("email", ""),
        "phone": s.get("phone"),
        "date_of_birth": str(s["date_of_birth"]) if s.get("date_of_birth") else None,
        "gender": s.get("gender"),
        "roll_number": s.get("roll_number"),
        "student_id": s.get("student_id"),
        "student_record_id": str(s["student_record_id"]) if s.get("student_record_id") else None,
        "class_id": str(s["class_id"]) if s.get("class_id") else None,
        "class_name": class_name,
        "is_verified": s.get("is_verified", False),
        "is_active": s.get("is_active", True),
        "profile_image_url": s.get("profile_image_url"),
        "joined_at": str(s["joined_at"]) if s.get("joined_at") else None,
        "created_at": str(s["joined_at"]) if s.get("joined_at") else None,
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/validate-class-code/{code}")
async def validate_class_code(code: str):
    """Public: validate a class join code and return class info"""
    from services.database import get_database
    db = await get_database()

    normalized_code = (code or "").strip().upper()
    cls = await db.get_class_by_code(normalized_code)
    if not cls:
        raise HTTPException(status_code=404, detail="Invalid class code")

    if not cls.get("allow_student_signup", True):
        raise HTTPException(status_code=403, detail="Student signup is disabled for this class")

    # Get teacher name
    teacher = await db.get_teacher(str(cls["teacher_id"]))
    teacher_name = teacher.get("name", "Unknown") if teacher else "Unknown"

    return {
        "valid": True,
        "class_code": normalized_code,
        "class_id": str(cls["id"]),
        "class_name": cls["name"],
        "grade_level": cls.get("grade_level"),
        "academic_year": cls.get("academic_year"),
        "teacher_name": teacher_name,
    }


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def student_signup(data: StudentSignup):
    """Register a new student account using a class code"""
    from services.database import get_database
    db = await get_database()

    # 1. Validate class code
    normalized_class_code = (data.class_code or "").strip().upper()
    cls = await db.get_class_by_code(normalized_class_code)
    if not cls:
        raise HTTPException(status_code=400, detail="Invalid class code")

    if not cls.get("allow_student_signup", True):
        raise HTTPException(status_code=403, detail="Student signup is disabled for this class")

    # 2. Check max students
    existing = await db.get_student_accounts_by_class(str(cls["id"]))
    max_students = cls.get("max_students", 100) or 100
    if len(existing) >= max_students:
        raise HTTPException(status_code=400, detail="Class is full. Contact your teacher.")

    # 3. Check if email already registered
    existing_account = await db.get_student_account_by_email(data.email)
    if existing_account:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    # Also check teacher accounts
    existing_teacher = await db.get_teacher_by_email(data.email)
    if existing_teacher:
        raise HTTPException(status_code=400, detail="This email is registered as a teacher account")

    # 4. Resolve roll number / student ID and prevent duplicates in class
    class_id = str(cls["id"])
    requested_roll = ((data.roll_number or data.student_id or "").strip() or None)
    requested_student_id = ((data.student_id or requested_roll or "").strip() or None)

    if requested_roll:
        duplicate_roll = await db.get_student_account_by_roll_number(class_id, requested_roll)
        if duplicate_roll:
            raise HTTPException(
                status_code=400,
                detail="This roll number is already assigned in the class",
            )

    matched_student = await db.find_student_record_for_account(
        class_id=class_id,
        roll_number=requested_roll,
        student_id=requested_student_id,
        email=data.email,
    )

    if not requested_roll and matched_student and matched_student.get("student_id"):
        requested_roll = str(matched_student.get("student_id"))
    if not requested_student_id and requested_roll:
        requested_student_id = requested_roll

    # 5. Parse date of birth
    dob = None
    if data.date_of_birth:
        try:
            from datetime import date as date_type
            parts = data.date_of_birth.split("-")
            dob = date_type(int(parts[0]), int(parts[1]), int(parts[2]))
        except Exception:
            pass

    # 6. Create account
    student_id = str(uuid.uuid4())
    account_data = {
        "id": student_id,
        "full_name": data.full_name,
        "email": data.email,
        "password_hash": _hash_password(data.password),
        "phone": data.phone,
        "date_of_birth": dob,
        "gender": data.gender,
        "roll_number": requested_roll,
        "student_id": requested_student_id,
        "student_record_id": str(matched_student["id"]) if matched_student else None,
        "class_id": class_id,
        "is_verified": False,
    }

    account = await db.create_student_account(account_data)
    if not account:
        raise HTTPException(status_code=500, detail="Failed to create student account")

    # 7. Issue JWT
    token = _create_student_token(student_id, data.email, class_id)

    logger.info(f"Student registered: {data.email} → class {cls['name']}")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _student_to_response(account, cls["name"]),
    }


@router.post("/login")
async def student_login(credentials: StudentLogin):
    """Student login"""
    from services.database import get_database
    db = await get_database()

    account = await db.get_student_account_by_email(credentials.email)
    if not account:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not account.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _verify_password(credentials.password, account["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not account.get("is_active", True):
        raise HTTPException(status_code=403, detail="Your account has been deactivated. Contact your teacher.")

    class_id = str(account["class_id"]) if account.get("class_id") else ""
    token = _create_student_token(str(account["id"]), account["email"], class_id)

    # Get class name
    class_name = None
    if account.get("class_id"):
        cls = await db.get_class(str(account["class_id"]))
        class_name = cls["name"] if cls else None

    logger.info(f"Student logged in: {credentials.email}")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _student_to_response(account, class_name),
    }


@router.get("/profile")
async def get_student_profile(current_student: dict = Depends(require_student())):
    """Get logged-in student profile"""
    from services.database import get_database
    db = await get_database()

    class_name = None
    if current_student.get("class_id"):
        cls = await db.get_class(current_student["class_id"])
        class_name = cls["name"] if cls else None

    return _student_to_response(current_student, class_name)


@router.patch("/profile")
async def update_student_profile(
    data: StudentProfileUpdate,
    current_student: dict = Depends(require_student()),
):
    """Update student profile"""
    from services.database import get_database
    db = await get_database()

    update_data = {}
    if data.full_name is not None:
        update_data["full_name"] = data.full_name
    if data.phone is not None:
        update_data["phone"] = data.phone
    if data.profile_image_url is not None:
        update_data["profile_image_url"] = data.profile_image_url

    if update_data:
        updated = await db.update_student_account(current_student["id"], update_data)
        if updated:
            class_name = None
            if current_student.get("class_id"):
                cls = await db.get_class(current_student["class_id"])
                class_name = cls["name"] if cls else None
            return _student_to_response(updated, class_name)

    return _student_to_response(current_student)
