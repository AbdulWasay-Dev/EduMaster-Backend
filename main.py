"""
EduMaster Backend - FastAPI Application
Educational RAG System with AI-powered question generation and grading
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import get_settings, Settings
from utils.security import setup_security_middleware
from utils.logging_config import setup_logging
from routers import auth, subjects, documents, rag, grading, classes, students, analytics, notifications, papers


# Global settings
settings = get_settings()

# Setup logging
setup_logging(settings.environment)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("🚀 Starting EduMaster Backend...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Initialize services here if needed
    # await initialize_services()
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down EduMaster Backend...")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Educational RAG System with AI-powered question generation and grading",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan
)

# Add security middleware
setup_security_middleware(app, settings)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",  # Allow all origins in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add trusted host middleware for production
if settings.environment == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["yourdomain.com", "*.yourdomain.com"]
    )

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Global exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    logger.error(f"HTTP {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "path": str(request.url)
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "path": str(request.url)
        }
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to EduMaster Backend API",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "docs_url": "/docs" if settings.debug else "Documentation not available in production",
        "health_check": "/health"
    }


# Include routers
app.include_router(
    auth.router,
    prefix=f"{settings.api_v1_prefix}/auth",
    tags=["Authentication"]
)

app.include_router(
    subjects.router,
    prefix=f"{settings.api_v1_prefix}/subjects",
    tags=["Subjects"]
)

app.include_router(
    documents.router,
    prefix=f"{settings.api_v1_prefix}/documents",
    tags=["Documents"]
)

app.include_router(
    rag.router,
    prefix=f"{settings.api_v1_prefix}/rag",
    tags=["RAG System"]
)

app.include_router(
    grading.router,
    prefix=f"{settings.api_v1_prefix}/grading",
    tags=["Grading"]
)

app.include_router(
    classes.router,
    prefix=f"{settings.api_v1_prefix}/classes",
    tags=["Classes"]
)

app.include_router(
    students.router,
    prefix=f"{settings.api_v1_prefix}/students",
    tags=["Students"]
)

app.include_router(
    analytics.router,
    prefix=f"{settings.api_v1_prefix}/analytics",
    tags=["Analytics"]
)

app.include_router(
    notifications.router,
    prefix=f"{settings.api_v1_prefix}/notifications",
    tags=["Notifications"]
)

app.include_router(
    papers.router,
    prefix=f"{settings.api_v1_prefix}/papers",
    tags=["Papers"]
)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info" if not settings.debug else "debug"
    )
