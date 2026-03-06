"""
Security utilities and middleware
"""
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Security scheme
security = HTTPBearer()


def setup_security_middleware(app: FastAPI, settings):
    """Setup security middleware for the application"""
    
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        """Add security headers to all responses"""
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Verify JWT token and return user data"""
    try:
        token = credentials.credentials
        payload = jwt.decode(
            token, 
            settings.secret_key, 
            algorithms=[settings.algorithm]
        )
        
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return {"user_id": user_id, "payload": payload}
        
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_teacher(token_data: dict = Depends(verify_token)) -> dict:
    """Get current teacher from token using PostgreSQL database"""
    from services.database import get_database
    
    db = await get_database()
    teacher = await db.get_teacher(token_data["user_id"])
    
    if teacher is None:
        raise HTTPException(
            status_code=401,
            detail="Teacher not found or access denied",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Convert UUID to string for consistent handling
    teacher["id"] = str(teacher["id"])
    return teacher


async def get_current_user(token_data: dict = Depends(verify_token)) -> dict:
    """Get current user from token (alias for get_current_teacher)"""
    return await get_current_teacher(token_data)


async def get_current_user_optional(request: Request) -> Optional[dict]:
    """Get current user if token is present (optional)"""
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ")[1]
        payload = jwt.decode(
            token, 
            settings.secret_key, 
            algorithms=[settings.algorithm]
        )
        
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        
        from services.database import get_database
        db = await get_database()
        user = await db.get_teacher(user_id)
        
        if user:
            user["id"] = str(user["id"])
        
        return user
        
    except Exception:
        return None


def require_role(required_role: str):
    """Decorator to require specific teacher role"""
    async def role_checker(current_teacher: dict = Depends(get_current_teacher)) -> dict:
        if current_teacher.get("role") != required_role:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {required_role}"
            )
        return current_teacher
    
    return role_checker


def require_teacher():
    """Require teacher role"""
    return require_role("teacher")


def require_admin():
    """Require admin role"""
    return require_role("admin")


def require_teacher_or_admin():
    """Require teacher or admin role"""
    async def role_checker(current_teacher: dict = Depends(get_current_teacher)) -> dict:
        teacher_role = current_teacher.get("role")
        if teacher_role not in ["teacher", "admin"]:
            raise HTTPException(
                status_code=403,
                detail="Access denied. Required role: teacher or admin"
            )
        return current_teacher
    
    return role_checker


def check_resource_ownership(resource_owner_id: str):
    """Check if current user owns the resource"""
    async def ownership_checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("id") != resource_owner_id and current_user.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail="Access denied. You don't own this resource"
            )
        return current_user
    
    return ownership_checker


# ==================== Student Authentication ====================

async def get_current_student(token_data: dict = Depends(verify_token)) -> dict:
    """Get current student account from token"""
    from services.database import get_database
    
    payload = token_data.get("payload", {})
    role = payload.get("role", "")
    
    if role != "student":
        raise HTTPException(
            status_code=403,
            detail="Access denied. Student account required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    db = await get_database()
    student = await db.get_student_account(token_data["user_id"])
    
    if student is None:
        raise HTTPException(
            status_code=401,
            detail="Student account not found or access denied",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    student["id"] = str(student["id"])
    if student.get("class_id"):
        student["class_id"] = str(student["class_id"])
    return student


def require_student():
    """Require student role"""
    async def student_checker(current_student: dict = Depends(get_current_student)) -> dict:
        if not current_student.get("is_active", True):
            raise HTTPException(
                status_code=403,
                detail="Student account is inactive"
            )
        return current_student
    return student_checker


async def get_current_user_any_role(token_data: dict = Depends(verify_token)) -> dict:
    """Get current user regardless of role (teacher or student)"""
    from services.database import get_database
    
    payload = token_data.get("payload", {})
    role = payload.get("role", "teacher")
    
    db = await get_database()
    
    if role == "student":
        user = await db.get_student_account(token_data["user_id"])
        if user:
            user["id"] = str(user["id"])
            user["role"] = "student"
            if user.get("class_id"):
                user["class_id"] = str(user["class_id"])
            return user
    else:
        user = await db.get_teacher(token_data["user_id"])
        if user:
            user["id"] = str(user["id"])
            return user
    
    raise HTTPException(
        status_code=401,
        detail="User not found",
        headers={"WWW-Authenticate": "Bearer"},
    )
