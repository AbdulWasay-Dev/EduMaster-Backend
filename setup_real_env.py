#!/usr/bin/env python3
"""
Setup script for real environment configuration
"""

import os
import sys

def create_env_file():
    """Create .env file with real credentials"""
    
    print("🚀 EduMaster Backend - Real Environment Setup")
    print("=" * 50)
    
    # Check if .env already exists
    if os.path.exists('.env'):
        print("⚠️  .env file already exists!")
        response = input("Do you want to overwrite it? (y/N): ")
        if response.lower() != 'y':
            print("❌ Setup cancelled.")
            return False
    
    print("\n📝 Please provide your real credentials:")
    print("(Press Enter to skip any field)")
    
    # Get Supabase credentials
    print("\n🗄️  Supabase Configuration:")
    supabase_url = input("SUPABASE_URL: ").strip()
    supabase_anon_key = input("SUPABASE_ANON_KEY: ").strip()
    supabase_service_key = input("SUPABASE_SERVICE_ROLE_KEY: ").strip()
    
    # Get Google API key
    print("\n🤖 Google GenAI Configuration:")
    google_api_key = input("GOOGLE_API_KEY: ").strip()
    
    # Get secret key
    print("\n🔐 Security Configuration:")
    secret_key = input("SECRET_KEY (or press Enter for auto-generated): ").strip()
    if not secret_key:
        import secrets
        secret_key = secrets.token_urlsafe(32)
        print(f"✅ Auto-generated SECRET_KEY: {secret_key}")
    
    # Create .env content
    env_content = f"""# EduMaster Backend Environment Configuration

# Application Settings
DEBUG=true
ENVIRONMENT=development
SECRET_KEY={secret_key}

# API Configuration
PORT=8010
CORS_ORIGINS=["http://localhost:5174", "http://127.0.0.1:5174"]

# Supabase Configuration
SUPABASE_URL={supabase_url or 'https://your-project.supabase.co'}
SUPABASE_ANON_KEY={supabase_anon_key or 'your-supabase-anon-key'}
SUPABASE_SERVICE_ROLE_KEY={supabase_service_key or 'your-supabase-service-role-key'}

# Google GenAI Configuration
GOOGLE_API_KEY={google_api_key or 'your-google-api-key'}
GOOGLE_EMBEDDING_MODEL=text-embedding-004
GOOGLE_LLM_MODEL=gemini-1.5-pro

# Redis Configuration
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=

# File Upload Configuration
MAX_FILE_SIZE=52428800
ALLOWED_FILE_TYPES=["pdf", "pptx", "docx", "png", "jpg", "jpeg"]
UPLOAD_PATH=uploads

# OCR Configuration
TESSERACT_PATH=
USE_GOOGLE_VISION=false
GOOGLE_VISION_CREDENTIALS=

# RAG Configuration
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
MAX_RETRIEVED_CHUNKS=5
SIMILARITY_THRESHOLD=0.7

# Security Configuration
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Rate Limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Monitoring
SENTRY_DSN=
ENABLE_METRICS=true
"""
    
    # Write .env file
    try:
        with open('.env', 'w') as f:
            f.write(env_content)
        print("\n✅ .env file created successfully!")
        return True
    except Exception as e:
        print(f"\n❌ Error creating .env file: {e}")
        return False

def test_connections():
    """Test connections to external services"""
    print("\n🔍 Testing connections...")
    
    # Test Supabase connection
    try:
        from services.supabase_client import get_supabase_service
        supabase = get_supabase_service()
        print("✅ Supabase connection successful!")
    except Exception as e:
        print(f"❌ Supabase connection failed: {e}")
    
    # Test Google API connection
    try:
        from services.llm_service import get_llm_service
        llm_service = get_llm_service()
        print("✅ Google API connection successful!")
    except Exception as e:
        print(f"❌ Google API connection failed: {e}")

def main():
    """Main setup function"""
    if create_env_file():
        print("\n🎉 Environment setup completed!")
        print("\n📋 Next steps:")
        print("1. Restart the server: python main.py")
        print("2. Test the endpoints at: http://localhost:8010/docs")
        print("3. Try uploading documents and using RAG features")
        
        # Ask if user wants to test connections
        response = input("\n🔍 Do you want to test connections now? (y/N): ")
        if response.lower() == 'y':
            test_connections()
    else:
        print("\n❌ Setup failed. Please try again.")

if __name__ == "__main__":
    main()
