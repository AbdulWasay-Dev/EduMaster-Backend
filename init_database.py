"""
Database initialization script for EduMaster Backend (PostgreSQL + ChromaDB)
Run this script to set up the PostgreSQL database and ChromaDB
"""
import asyncio
import asyncpg
import os
import sys

# Database schema SQL
SCHEMA_SQL = """
-- EduMaster Database Schema
-- PostgreSQL for relational data

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Teachers table with password hash for local authentication
CREATE TABLE IF NOT EXISTS teachers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'teacher' CHECK (role IN ('teacher', 'admin')),
    profile_image_url TEXT,
    school_name TEXT,
    department TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Classes/Groups for organizing students (managed by teachers)
CREATE TABLE IF NOT EXISTS classes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    grade_level TEXT,
    subject_area TEXT,
    academic_year TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Students (managed by teachers, no direct login)
CREATE TABLE IF NOT EXISTS students (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    student_name TEXT NOT NULL,
    student_id TEXT,
    email TEXT,
    phone TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Subjects (managed by teachers)
CREATE TABLE IF NOT EXISTS subjects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    color_code TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Documents (enhanced with metadata)
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    owner_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'pptx', 'docx', 'png', 'jpg', 'jpeg')),
    file_size BIGINT,
    page_count INTEGER,
    processing_status TEXT DEFAULT 'pending' CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Document Chunks (Relation only, embeddings stored in ChromaDB)
CREATE TABLE IF NOT EXISTS doc_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    owner_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_type TEXT DEFAULT 'paragraph' CHECK (chunk_type IN ('section', 'paragraph', 'list', 'table')),
    text TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Papers with questions and answer keys
CREATE TABLE IF NOT EXISTS papers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    class_id UUID REFERENCES classes(id),
    owner_id UUID REFERENCES teachers(id),
    title TEXT NOT NULL,
    description TEXT,
    questions JSONB NOT NULL,
    configuration JSONB,
    answer_key JSONB NOT NULL,
    total_marks DECIMAL(5,2),
    is_published BOOLEAN DEFAULT FALSE,
    published_at TIMESTAMP WITH TIME ZONE,
    due_date TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Student Submissions
CREATE TABLE IF NOT EXISTS submissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    student_id UUID REFERENCES students(id) ON DELETE CASCADE,
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    student_name TEXT NOT NULL,
    storage_path TEXT,
    ocr_text TEXT,
    submission_data JSONB,
    total_score DECIMAL(5,2),
    grade_percentage DECIMAL(5,2),
    feedback TEXT,
    grading_status TEXT DEFAULT 'pending' CHECK (grading_status IN ('pending', 'grading', 'completed')),
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    graded_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Notifications system
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    notification_type TEXT NOT NULL CHECK (notification_type IN ('paper_assigned', 'grade_available', 'deadline_reminder', 'document_processed')),
    is_read BOOLEAN DEFAULT FALSE,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_doc_chunks_subject ON doc_chunks(subject_id);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_owner ON doc_chunks(owner_id);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_document ON doc_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_submissions_student ON submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_submissions_paper ON submissions(paper_id);
CREATE INDEX IF NOT EXISTS idx_submissions_class ON submissions(class_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_teachers_email ON teachers(email);

-- Triggers for updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_teachers_updated_at ON teachers;
CREATE TRIGGER update_teachers_updated_at BEFORE UPDATE ON teachers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_classes_updated_at ON classes;
CREATE TRIGGER update_classes_updated_at BEFORE UPDATE ON classes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_subjects_updated_at ON subjects;
CREATE TRIGGER update_subjects_updated_at BEFORE UPDATE ON subjects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_documents_updated_at ON documents;
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_papers_updated_at ON papers;
CREATE TRIGGER update_papers_updated_at BEFORE UPDATE ON papers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
"""


async def init_database():
    """Initialize the database with the schema"""
    from config import get_settings
    settings = get_settings()
    
    # Extract database name and base connection string
    db_url = settings.database_url
    if not db_url.startswith("postgresql://"):
        print(f"❌ Invalid DATABASE_URL format: {db_url}")
        return

    # Split to get parts
    try:
        base_url, db_name = db_url.rsplit("/", 1)
        postgres_url = f"{base_url}/postgres"
    except ValueError:
        print(f"❌ Could not parse database name from URL: {db_url}")
        return

    print("🗄️ Initializing EduMaster database...")
    print(f"📍 Target Database: {db_name}")

    try:
        # 1. Connect to default 'postgres' database to create the target database if it doesn't exist
        print(f"🔗 Connecting to 'postgres' to check for '{db_name}'...")
        conn = await asyncpg.connect(postgres_url)
        
        # Check if database exists
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        
        if not exists:
            print(f"✨ Database '{db_name}' does not exist. Creating it now...")
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"✅ Database '{db_name}' created.")
        else:
            print(f"👍 Database '{db_name}' already exists.")
        
        await conn.close()

        # 2. Connect to the target database and run schema
        print(f"🔗 Connecting to '{db_name}' to apply schema...")
        conn = await asyncpg.connect(db_url)
        
        print("📝 Creating tables and indexes...")
        await conn.execute(SCHEMA_SQL)
        
        print("✅ Database schema created successfully!")
        
        # 3. Initialize ChromaDB
        print("\n🔎 Initializing ChromaDB...")
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        
        os.makedirs(settings.chroma_db_path, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=settings.chroma_db_path)
        print(f"✅ ChromaDB initialized at {settings.chroma_db_path}")
        
        # Verify tables exist
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        
        print(f"\n📋 Created tables ({len(tables)}):")
        for table in tables:
            print(f"   - {table['table_name']}")
        
        await conn.close()
        print("\n🎉 Database initialization complete!")
        
    except Exception as e:
        print(f"\n❌ Error initializing database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(init_database())
