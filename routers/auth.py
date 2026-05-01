"""
Authentication API endpoints
Local JWT authentication (replaces Supabase Auth)
"""
import logging
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from jose import jwt
import bcrypt

from utils.security import get_current_teacher
from config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()
security = HTTPBearer()


class UserRegister(BaseModel):
    """User registration model"""
    email: EmailStr
    password: str
    name: str
    role: str = "teacher"
    school_name: Optional[str] = None
    institution_type: Optional[str] = None
    institution_level: Optional[str] = None
    institution_address: Optional[str] = None
    institution_city: Optional[str] = None
    institution_country: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    qualification: Optional[str] = None
    specialization: Optional[str] = None
    employee_id: Optional[str] = None
    phone: Optional[str] = None
    default_course_name: Optional[str] = None
    default_exam_duration: Optional[str] = None
    default_exam_instructions: Optional[str] = None
    default_student_fields: Optional[List[str]] = None
    default_paper_template: Optional[str] = None


class UserLogin(BaseModel):
    """User login model"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Token response model"""
    access_token: str
    token_type: str


class UserProfile(BaseModel):
    """User profile model"""
    id: str
    name: str
    email: str
    role: str
    profile_image_url: Optional[str] = None
    school_name: Optional[str] = None
    institution_type: Optional[str] = None
    institution_level: Optional[str] = None
    institution_address: Optional[str] = None
    institution_city: Optional[str] = None
    institution_country: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    qualification: Optional[str] = None
    specialization: Optional[str] = None
    employee_id: Optional[str] = None
    phone: Optional[str] = None
    default_course_name: Optional[str] = None
    default_exam_duration: Optional[str] = None
    default_exam_instructions: Optional[str] = None
    default_student_fields: List[str] = Field(default_factory=lambda: ["name", "roll_number"])
    default_paper_template: Optional[str] = "classic"


TEACHER_PROFILE_FIELDS = [
    "profile_image_url",
    "school_name",
    "institution_type",
    "institution_level",
    "institution_address",
    "institution_city",
    "institution_country",
    "department",
    "designation",
    "qualification",
    "specialization",
    "employee_id",
    "phone",
    "default_course_name",
    "default_exam_duration",
    "default_exam_instructions",
    "default_student_fields",
    "default_paper_template",
]


def _parse_student_fields(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except Exception:
            return ["name", "roll_number"]
    return ["name", "roll_number"]


def _profile_response(user: dict) -> UserProfile:
    return UserProfile(
        id=str(user["id"]),
        name=user.get("name", user.get("full_name", "Unknown")),
        email=user["email"],
        role=user.get("role", "teacher"),
        profile_image_url=user.get("profile_image_url"),
        school_name=user.get("school_name"),
        institution_type=user.get("institution_type"),
        institution_level=user.get("institution_level"),
        institution_address=user.get("institution_address"),
        institution_city=user.get("institution_city"),
        institution_country=user.get("institution_country"),
        department=user.get("department"),
        designation=user.get("designation"),
        qualification=user.get("qualification"),
        specialization=user.get("specialization"),
        employee_id=user.get("employee_id"),
        phone=user.get("phone"),
        default_course_name=user.get("default_course_name"),
        default_exam_duration=user.get("default_exam_duration"),
        default_exam_instructions=user.get("default_exam_instructions"),
        default_student_fields=_parse_student_fields(user.get("default_student_fields")),
        default_paper_template=user.get("default_paper_template") or "classic",
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(user_data: UserRegister):
    """Register a new user with local authentication"""
    try:
        logger.info(f"Registering user: {user_data.email}")
        
        # Import database service
        from services.database import get_database
        db = await get_database()
        
        # Check if email already exists
        existing_user = await db.get_teacher_by_email(user_data.email)
        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="User with this email already exists"
            )
        
        # Create new user with hashed password
        user_id = str(uuid.uuid4())
        password_hash = get_password_hash(user_data.password)
        
        teacher_data = {
            "id": user_id,
            "email": user_data.email,
            "name": user_data.name,
            "role": user_data.role,
            "password_hash": password_hash,
            "school_name": user_data.school_name,
            "institution_type": user_data.institution_type,
            "institution_level": user_data.institution_level,
            "institution_address": user_data.institution_address,
            "institution_city": user_data.institution_city,
            "institution_country": user_data.institution_country,
            "department": user_data.department,
            "designation": user_data.designation,
            "qualification": user_data.qualification,
            "specialization": user_data.specialization,
            "employee_id": user_data.employee_id,
            "phone": user_data.phone,
            "default_course_name": user_data.default_course_name,
            "default_exam_duration": user_data.default_exam_duration,
            "default_exam_instructions": user_data.default_exam_instructions,
            "default_student_fields": user_data.default_student_fields or ["name", "roll_number"],
            "default_paper_template": user_data.default_paper_template or "classic",
        }
        
        user = await db.create_teacher(teacher_data)
        if not user:
            raise HTTPException(
                status_code=500,
                detail="Failed to create user"
            )
        
        # Create access token so the user is logged in immediately after registration
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = create_access_token(
            data={"sub": str(user["id"]), "email": user["email"], "role": user["role"]},
            expires_delta=access_token_expires
        )

        logger.info(f"User registered successfully: {user_id}")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": str(user["id"]),
                "email": user["email"],
                "full_name": user.get("name", ""),
                "role": user.get("role", "teacher")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration failed: {str(e)}"
        )


@router.post("/login", response_model=Token)
async def login_user(user_credentials: UserLogin):
    """Login with email and password, returns JWT token"""
    try:
        logger.info(f"Login attempt for: {user_credentials.email}")
        
        # Import database service
        from services.database import get_database
        db = await get_database()
        
        # Get user by email
        user = await db.get_teacher_by_email(user_credentials.email)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        
        # Verify password
        if not user.get("password_hash"):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        
        if not verify_password(user_credentials.password, user["password_hash"]):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        
        # Create access token
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = create_access_token(
            data={"sub": str(user["id"]), "email": user["email"], "role": user["role"]},
            expires_delta=access_token_expires
        )
        
        logger.info(f"User logged in successfully: {user['id']}")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": str(user["id"]),
                "email": user["email"],
                "full_name": user.get("name", ""),
                "role": user.get("role", "teacher")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )


@router.get("/profile", response_model=UserProfile)
async def get_profile(current_user: dict = Depends(get_current_teacher)):
    """Get current user profile"""
    return _profile_response(current_user)


@router.put("/profile")
async def update_profile(
    profile_data: dict,
    current_user: dict = Depends(get_current_teacher)
):
    """Update user profile"""
    try:
        from services.database import get_database
        db = await get_database()
        
        # Only allow updating teacher profile fields.
        allowed_fields = ["name", *TEACHER_PROFILE_FIELDS]
        update_data = {k: v for k, v in profile_data.items() if k in allowed_fields}
        
        if update_data:
            await db.update_teacher(str(current_user["id"]), update_data)
        
        # Return updated profile as a User object
        updated = await db.get_teacher(str(current_user["id"]))
        if updated:
            return _profile_response(updated)
        return {"message": "Profile updated successfully"}
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update profile"
        )
