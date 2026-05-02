"""
Configuration settings for EduMaster Backend
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    app_name: str = "EduMaster Backend"
    app_version: str = "1.0.0"
    debug: bool = Field(default=False, env="DEBUG")
    environment: str = Field(default="development", env="ENVIRONMENT")
    
    # API Configuration
    api_v1_prefix: str = "/api/v1"
    port: int = Field(default=8010, env="PORT")
    cors_origins: list[str] = Field(
        default=["*"],  # Allow all origins in development
        env="CORS_ORIGINS"
    )
    
    # PostgreSQL Database Configuration
    database_url: str = Field(
        default="postgresql://postgres:password@localhost:5432/edumaster_db",
        env="DATABASE_URL"
    )
    
    # Google GenAI Configuration (kept for Vision OCR if needed)
    google_api_key: str = Field(default="placeholder-google-key", env="GOOGLE_API_KEY")

    # Groq LLM Configuration (free, fast inference)
    groq_api_key: str = Field(default="placeholder-groq-key", env="GROQ_API_KEY")
    groq_api_keys: str = Field(default="", env="GROQ_API_KEYS")

    @property
    def all_groq_keys(self) -> list[str]:
        keys = []
        if self.groq_api_keys:
            keys.extend([k.strip() for k in self.groq_api_keys.split(",") if k.strip()])
        if self.groq_api_key and self.groq_api_key not in keys and self.groq_api_key != "placeholder-groq-key":
            keys.append(self.groq_api_key)
        return keys
    groq_llm_model: str = Field(
        default="llama-3.3-70b-versatile", env="GROQ_LLM_MODEL"
    )

    # Local Embedding Model (sentence-transformers, no API key needed)
    # Top-ranked free model on MTEB benchmark, 768-dim embeddings
    local_embedding_model: str = Field(
        default="BAAI/bge-base-en-v1.5", env="LOCAL_EMBEDDING_MODEL"
    )
    
    # Mistral AI Configuration
    mistral_api_key: str = Field(default="placeholder-mistral-key", env="MISTRAL_API_KEY")
    
    # Redis Configuration
    redis_url: str = Field(default="redis://localhost:6379", env="REDIS_URL")
    redis_password: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    
    # File Upload Configuration
    max_file_size: int = Field(default=50 * 1024 * 1024, env="MAX_FILE_SIZE")  # 50MB
    allowed_file_types: list[str] = Field(
        default=["pdf", "pptx", "docx", "png", "jpg", "jpeg"],
        env="ALLOWED_FILE_TYPES"
    )
    upload_path: str = Field(default="uploads", env="UPLOAD_PATH")
    
    # OCR Configuration
    tesseract_path: Optional[str] = Field(default=None, env="TESSERACT_PATH")
    use_google_vision: bool = Field(default=False, env="USE_GOOGLE_VISION")
    google_vision_credentials: Optional[str] = Field(default=None, env="GOOGLE_VISION_CREDENTIALS")
    
    # RAG Configuration
    chunk_size: int = Field(default=1000, env="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, env="CHUNK_OVERLAP")
    max_retrieved_chunks: int = Field(default=5, env="MAX_RETRIEVED_CHUNKS")
    similarity_threshold: float = Field(default=0.7, env="SIMILARITY_THRESHOLD")
    chroma_db_path: str = Field(default="chroma_db", env="CHROMA_DB_PATH")
    
    # Security Configuration (JWT)
    secret_key: str = Field(default="your-secret-key-here-change-in-production-make-it-long-and-random", env="SECRET_KEY")
    algorithm: str = Field(default="HS256", env="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # Rate Limiting
    rate_limit_requests: int = Field(default=100, env="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=60, env="RATE_LIMIT_WINDOW")  # seconds
    
    # Celery Configuration
    celery_broker_url: str = Field(default="redis://localhost:6379/0", env="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/0", env="CELERY_RESULT_BACKEND")
    
    # Monitoring
    sentry_dsn: Optional[str] = Field(default=None, env="SENTRY_DSN")
    enable_metrics: bool = Field(default=True, env="ENABLE_METRICS")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_flag(cls, value):
        """Accept common environment labels accidentally supplied as DEBUG."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "no", "off"}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "yes", "on"}:
                return True
        return value
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings"""
    return settings


# Environment-specific configurations
class DevelopmentSettings(Settings):
    """Development environment settings"""
    debug: bool = True
    environment: str = "development"


class ProductionSettings(Settings):
    """Production environment settings"""
    debug: bool = False
    environment: str = "production"
    cors_origins: list[str] = []  # Set specific origins in production


def get_environment_settings() -> Settings:
    """Get environment-specific settings"""
    env = os.getenv("ENVIRONMENT", "development")
    
    if env == "production":
        return ProductionSettings()
    else:
        return DevelopmentSettings()
