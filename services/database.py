"""
PostgreSQL Database Service for EduMaster Backend
Replaces Supabase client with direct asyncpg connection
Integrates ChromaDB for vector similarity search
"""
import logging
import uuid
import os
import json
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

import asyncpg
from asyncpg import Pool
import chromadb
from chromadb.config import Settings as ChromaSettings

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DatabaseService:
    """Async PostgreSQL database service and ChromaDB client"""
    
    _pool: Optional[Pool] = None
    _chroma_client: Optional[chromadb.Client] = None

    # ==================== Schema SQL ====================
    # All tables are created with IF NOT EXISTS so this is safe to run on every startup.

    SCHEMA_SQL = """
    -- Enable required extensions
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    -- ==================== Core Tables ====================

    CREATE TABLE IF NOT EXISTS teachers (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'teacher' CHECK (role IN ('teacher', 'admin')),
        profile_image_url TEXT,
        school_name TEXT,
        department TEXT,
        institution_type TEXT,
        institution_level TEXT,
        institution_address TEXT,
        institution_city TEXT,
        institution_country TEXT,
        designation TEXT,
        qualification TEXT,
        specialization TEXT,
        employee_id TEXT,
        phone TEXT,
        default_course_name TEXT,
        default_exam_duration TEXT,
        default_exam_instructions TEXT,
        default_student_fields JSONB DEFAULT '["name", "roll_number"]',
        default_paper_template TEXT DEFAULT 'classic',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS institution_type TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS institution_level TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS institution_address TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS institution_city TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS institution_country TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS designation TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS qualification TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS specialization TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS employee_id TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS phone TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS default_course_name TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS default_exam_duration TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS default_exam_instructions TEXT;
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS default_student_fields JSONB DEFAULT '["name", "roll_number"]';
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS default_paper_template TEXT DEFAULT 'classic';

    CREATE TABLE IF NOT EXISTS classes (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT,
        grade_level TEXT,
        subject_area TEXT,
        academic_year TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        class_code TEXT UNIQUE,
        max_students INTEGER DEFAULT 100,
        allow_student_signup BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

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

    CREATE TABLE IF NOT EXISTS notifications (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        notification_type TEXT NOT NULL CHECK (notification_type IN ('paper_assigned', 'grade_available', 'deadline_reminder', 'document_processed')),
        is_read BOOLEAN DEFAULT FALSE,
        metadata JSONB,
        student_account_id UUID,
        audience TEXT DEFAULT 'teacher',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    -- ==================== Phase 2 Tables ====================

    CREATE TABLE IF NOT EXISTS student_accounts (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        phone TEXT,
        date_of_birth DATE,
        gender TEXT CHECK (gender IN ('male', 'female', 'other', 'prefer_not_to_say')),
        profile_image_url TEXT,
        roll_number TEXT,
        student_id TEXT,
        class_id UUID REFERENCES classes(id) ON DELETE SET NULL,
        student_record_id UUID REFERENCES students(id) ON DELETE SET NULL,
        is_active BOOLEAN DEFAULT TRUE,
        is_verified BOOLEAN DEFAULT FALSE,
        joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS assignments (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE NOT NULL,
        subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE NOT NULL,
        class_id UUID REFERENCES classes(id) ON DELETE CASCADE NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        instructions TEXT,
        total_marks INTEGER NOT NULL DEFAULT 10,
        due_date TIMESTAMP WITH TIME ZONE,
        attachment_url TEXT,
        attachment_filename TEXT,
        grading_rubric TEXT,
        auto_grade BOOLEAN DEFAULT TRUE,
        status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'closed')),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS assignment_submissions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        assignment_id UUID REFERENCES assignments(id) ON DELETE CASCADE NOT NULL,
        student_account_id UUID REFERENCES student_accounts(id) ON DELETE CASCADE NOT NULL,
        class_id UUID REFERENCES classes(id) ON DELETE CASCADE NOT NULL,
        submission_text TEXT,
        submission_files JSONB DEFAULT '[]',
        marks_obtained NUMERIC(5,2),
        max_marks INTEGER,
        percentage NUMERIC(5,2),
        grade TEXT,
        ai_feedback TEXT,
        ai_rubric_breakdown JSONB,
        teacher_remarks TEXT,
        teacher_override_marks NUMERIC(5,2),
        status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'grading', 'graded', 'returned')),
        submitted_at TIMESTAMP WITH TIME ZONE,
        graded_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE (assignment_id, student_account_id)
    );

    CREATE TABLE IF NOT EXISTS student_scores (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        student_account_id UUID REFERENCES student_accounts(id) ON DELETE CASCADE NOT NULL,
        class_id UUID REFERENCES classes(id) ON DELETE CASCADE NOT NULL,
        subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
        score_type TEXT NOT NULL CHECK (score_type IN ('assignment', 'paper', 'quiz')),
        reference_id UUID NOT NULL,
        title TEXT,
        marks_obtained NUMERIC(5,2),
        max_marks NUMERIC(5,2),
        percentage NUMERIC(5,2),
        grade TEXT,
        scored_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    -- ==================== Enhanced Grading Tables ====================

    CREATE TABLE IF NOT EXISTS submission_images (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
        image_index INTEGER NOT NULL,
        image_type TEXT DEFAULT 'jpeg' CHECK (image_type IN ('jpeg', 'jpg', 'png', 'gif', 'bmp')),
        file_size BIGINT,
        ocr_text TEXT,
        ocr_confidence DECIMAL(3,2),
        processing_status TEXT DEFAULT 'pending' CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
        error_message TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS question_grading_details (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
        question_id TEXT NOT NULL,
        question_text TEXT NOT NULL,
        question_type TEXT NOT NULL CHECK (question_type IN ('mcq', 'true_false', 'short_answer', 'essay', 'fill_blank')),
        student_answer TEXT,
        correct_answer TEXT,
        score DECIMAL(5,2) NOT NULL DEFAULT 0,
        max_score DECIMAL(5,2) NOT NULL,
        feedback TEXT,
        ai_confidence DECIMAL(3,2),
        grading_method TEXT DEFAULT 'ai' CHECK (grading_method IN ('ai', 'manual', 'auto')),
        is_correct BOOLEAN,
        partial_credit DECIMAL(3,2) DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ocr_processing_logs (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
        image_id UUID REFERENCES submission_images(id) ON DELETE CASCADE,
        ocr_service TEXT DEFAULT 'mistral' CHECK (ocr_service IN ('mistral', 'tesseract', 'google_vision')),
        processing_time_ms INTEGER,
        raw_ocr_response JSONB,
        extracted_text TEXT,
        confidence_score DECIMAL(3,2),
        error_details TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS grading_audit_log (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
        action_type TEXT NOT NULL CHECK (action_type IN ('graded', 'regraded', 'manual_override', 'grade_adjusted')),
        previous_score DECIMAL(5,2),
        new_score DECIMAL(5,2),
        previous_percentage DECIMAL(5,2),
        new_percentage DECIMAL(5,2),
        changed_by UUID REFERENCES teachers(id),
        change_reason TEXT,
        metadata JSONB,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS batch_grading_jobs (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
        paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
        class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
        job_name TEXT,
        total_submissions INTEGER DEFAULT 0,
        processed_submissions INTEGER DEFAULT 0,
        successful_submissions INTEGER DEFAULT 0,
        failed_submissions INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
        grading_settings JSONB,
        error_log TEXT,
        started_at TIMESTAMP WITH TIME ZONE,
        completed_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    -- ==================== Indexes ====================

    CREATE INDEX IF NOT EXISTS idx_teachers_email ON teachers(email);
    CREATE INDEX IF NOT EXISTS idx_subjects_teacher_id ON subjects(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_subjects_class_id ON subjects(class_id);
    CREATE INDEX IF NOT EXISTS idx_documents_subject_id ON documents(subject_id);
    CREATE INDEX IF NOT EXISTS idx_doc_chunks_document ON doc_chunks(document_id);
    CREATE INDEX IF NOT EXISTS idx_doc_chunks_subject ON doc_chunks(subject_id);
    CREATE INDEX IF NOT EXISTS idx_doc_chunks_owner ON doc_chunks(owner_id);
    CREATE INDEX IF NOT EXISTS idx_papers_subject_id ON papers(subject_id);
    CREATE INDEX IF NOT EXISTS idx_papers_owner_id ON papers(owner_id);
    CREATE INDEX IF NOT EXISTS idx_papers_class_id ON papers(class_id);
    CREATE INDEX IF NOT EXISTS idx_submissions_paper ON submissions(paper_id);
    CREATE INDEX IF NOT EXISTS idx_submissions_student ON submissions(student_id);
    CREATE INDEX IF NOT EXISTS idx_submissions_class ON submissions(class_id);
    CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
    CREATE INDEX IF NOT EXISTS idx_student_accounts_class ON student_accounts(class_id);
    CREATE INDEX IF NOT EXISTS idx_student_accounts_email ON student_accounts(email);
    CREATE INDEX IF NOT EXISTS idx_assignments_teacher ON assignments(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_assignments_class ON assignments(class_id);
    CREATE INDEX IF NOT EXISTS idx_assignments_subject ON assignments(subject_id);
    CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status);
    CREATE INDEX IF NOT EXISTS idx_asub_assignment ON assignment_submissions(assignment_id);
    CREATE INDEX IF NOT EXISTS idx_asub_student ON assignment_submissions(student_account_id);
    CREATE INDEX IF NOT EXISTS idx_asub_status ON assignment_submissions(status);
    CREATE INDEX IF NOT EXISTS idx_scores_student ON student_scores(student_account_id);
    CREATE INDEX IF NOT EXISTS idx_scores_class ON student_scores(class_id);
    CREATE INDEX IF NOT EXISTS idx_submission_images_submission ON submission_images(submission_id);
    CREATE INDEX IF NOT EXISTS idx_question_grading_submission ON question_grading_details(submission_id);
    CREATE INDEX IF NOT EXISTS idx_ocr_logs_submission ON ocr_processing_logs(submission_id);
    CREATE INDEX IF NOT EXISTS idx_grading_audit_submission ON grading_audit_log(submission_id);
    CREATE INDEX IF NOT EXISTS idx_batch_jobs_teacher ON batch_grading_jobs(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_grading_jobs(status);

    -- ==================== Triggers ====================

    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

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

    DROP TRIGGER IF EXISTS update_student_accounts_updated_at ON student_accounts;
    CREATE TRIGGER update_student_accounts_updated_at BEFORE UPDATE ON student_accounts
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

    DROP TRIGGER IF EXISTS update_assignments_updated_at ON assignments;
    CREATE TRIGGER update_assignments_updated_at BEFORE UPDATE ON assignments
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

    DROP TRIGGER IF EXISTS update_assignment_submissions_updated_at ON assignment_submissions;
    CREATE TRIGGER update_assignment_submissions_updated_at BEFORE UPDATE ON assignment_submissions
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """

    async def initialize(self):
        """Initialize connection pools, create schema, and set up ChromaDB"""
        # 1. Ensure the target database exists
        await self._ensure_database_exists()

        # 2. Initialize PostgreSQL pool
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    settings.database_url,
                    min_size=2,
                    max_size=10,
                    command_timeout=60
                )
                logger.info("✅ PostgreSQL connection pool initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize PostgreSQL pool: {e}")
                raise

        # 3. Run schema migrations (idempotent)
        await self._init_schema()

        # 4. Initialize ChromaDB
        if self._chroma_client is None:
            try:
                os.makedirs(settings.chroma_db_path, exist_ok=True)
                self._chroma_client = chromadb.PersistentClient(
                    path=settings.chroma_db_path,
                    settings=ChromaSettings(allow_reset=True)
                )
                logger.info(f"✅ ChromaDB initialized at {settings.chroma_db_path}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize ChromaDB: {e}")
                raise

    async def _ensure_database_exists(self):
        """Create the target database if it does not already exist."""
        db_url = settings.database_url
        try:
            base_url, db_name = db_url.rsplit("/", 1)
            # Strip query params from db_name if any
            if "?" in db_name:
                db_name = db_name.split("?")[0]
            postgres_url = f"{base_url}/postgres"
        except ValueError:
            logger.warning("Could not parse database name from URL — skipping auto-create.")
            return

        try:
            conn = await asyncpg.connect(postgres_url)
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", db_name
            )
            if not exists:
                # CREATE DATABASE cannot run inside a transaction block
                await conn.execute(f'CREATE DATABASE "{db_name}"')
                logger.info(f"✨ Created database '{db_name}'")
            else:
                logger.info(f"👍 Database '{db_name}' already exists")
            await conn.close()
        except Exception as e:
            logger.warning(f"Could not auto-create database (will try to connect anyway): {e}")

    async def _init_schema(self):
        """Execute the schema SQL to create all tables/indexes/triggers (idempotent)."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(self.SCHEMA_SQL)
            logger.info("✅ Database schema verified / created successfully")
        except Exception as e:
            logger.error(f"❌ Error initialising database schema: {e}")
            raise
    
    async def close(self):
        """Close connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL connection pool closed")
    
    @asynccontextmanager
    async def connection(self):
        """Get a connection from the pool"""
        if self._pool is None:
            await self.initialize()
        async with self._pool.acquire() as conn:
            yield conn
    
    async def check_connection(self) -> bool:
        """Check if database connection is working"""
        try:
            async with self.connection() as conn:
                await conn.fetchval("SELECT 1")
            return self._chroma_client is not None
        except Exception as e:
            logger.error(f"Database connection check failed: {e}")
            return False

    # ==================== Teacher Operations ====================
    
    async def get_teacher(self, teacher_id: str) -> Optional[Dict[str, Any]]:
        """Get teacher by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM teachers WHERE id = $1",
                    uuid.UUID(teacher_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting teacher {teacher_id}: {e}")
            return None
    
    async def get_teacher_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get teacher by email"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM teachers WHERE email = $1",
                    email
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting teacher by email {email}: {e}")
            return None
    
    async def create_teacher(self, teacher_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new teacher"""
        try:
            teacher_id = teacher_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO teachers (
                        id, email, name, role, password_hash, profile_image_url,
                        school_name, department, institution_type, institution_level,
                        institution_address, institution_city, institution_country,
                        designation, qualification, specialization, employee_id, phone,
                        default_course_name, default_exam_duration, default_exam_instructions,
                        default_student_fields, default_paper_template
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                        $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23
                    )
                    RETURNING *
                    """,
                    uuid.UUID(teacher_id),
                    teacher_data["email"],
                    teacher_data["name"],
                    teacher_data.get("role", "teacher"),
                    teacher_data.get("password_hash"),
                    teacher_data.get("profile_image_url"),
                    teacher_data.get("school_name"),
                    teacher_data.get("department"),
                    teacher_data.get("institution_type"),
                    teacher_data.get("institution_level"),
                    teacher_data.get("institution_address"),
                    teacher_data.get("institution_city"),
                    teacher_data.get("institution_country"),
                    teacher_data.get("designation"),
                    teacher_data.get("qualification"),
                    teacher_data.get("specialization"),
                    teacher_data.get("employee_id"),
                    teacher_data.get("phone"),
                    teacher_data.get("default_course_name"),
                    teacher_data.get("default_exam_duration"),
                    teacher_data.get("default_exam_instructions"),
                    json.dumps(teacher_data.get("default_student_fields", ["name", "roll_number"])),
                    teacher_data.get("default_paper_template", "classic")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating teacher: {e}")
            return None
    
    async def update_teacher(self, teacher_id: str, teacher_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update teacher data"""
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in teacher_data.items():
                if key != "id":
                    if key == "default_student_fields" and isinstance(value, list):
                        value = json.dumps(value)
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
            
            if not set_clauses:
                return await self.get_teacher(teacher_id)
            
            values.append(uuid.UUID(teacher_id))
            query = f"UPDATE teachers SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating teacher {teacher_id}: {e}")
            return None

    # ==================== Subject Operations ====================
    
    async def get_subject(self, subject_id: str) -> Optional[Dict[str, Any]]:
        """Get subject by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM subjects WHERE id = $1",
                    uuid.UUID(subject_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting subject {subject_id}: {e}")
            return None
    
    async def create_subject(self, subject_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new subject"""
        try:
            subject_id = subject_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO subjects (id, teacher_id, class_id, name, description, color_code)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                    """,
                    uuid.UUID(subject_id),
                    uuid.UUID(subject_data["teacher_id"]),
                    uuid.UUID(subject_data["class_id"]) if subject_data.get("class_id") else None,
                    subject_data["name"],
                    subject_data.get("description"),
                    subject_data.get("color_code")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating subject: {e}")
            return None
    
    async def get_subjects(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get subjects by teacher"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM subjects WHERE teacher_id = $1",
                    uuid.UUID(teacher_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting subjects for teacher {teacher_id}: {e}")
            return []

    # ==================== Document Operations ====================
    
    async def create_document(self, document_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new document record"""
        try:
            doc_id = document_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO documents (id, subject_id, owner_id, filename, original_filename, 
                                          storage_path, file_type, file_size, processing_status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING *
                    """,
                    uuid.UUID(doc_id),
                    uuid.UUID(document_data["subject_id"]),
                    uuid.UUID(document_data["owner_id"]),
                    document_data["filename"],
                    document_data["original_filename"],
                    document_data["storage_path"],
                    document_data["file_type"],
                    document_data.get("file_size", 0),
                    document_data.get("processing_status", "pending")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating document: {e}")
            return None
    
    async def get_documents(self, subject_id: str) -> List[Dict[str, Any]]:
        """Get documents by subject"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM documents WHERE subject_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(subject_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting documents for subject {subject_id}: {e}")
            return []

    async def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM documents WHERE id = $1",
                    uuid.UUID(document_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return None

    async def get_document_chunks(self, document_id: str) -> List[Dict[str, Any]]:
        """Get text chunks for a document"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT id, chunk_index, text, metadata FROM doc_chunks WHERE document_id = $1 ORDER BY chunk_index",
                    uuid.UUID(document_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting chunks for document {document_id}: {e}")
            return []

    async def update_document_status(self, document_id: str, status: str) -> bool:
        """Update document processing status"""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "UPDATE documents SET processing_status = $1, updated_at = NOW() WHERE id = $2",
                    status,
                    uuid.UUID(document_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating document {document_id} status: {e}")
            return False

    async def delete_document(self, document_id: str) -> bool:
        """Delete a document and its chunks from PostgreSQL and ChromaDB"""
        try:
            # Get subject_id first to find the ChromaDB collection
            document = await self.get_document(document_id)
            if not document:
                return False
            
            subject_id = str(document["subject_id"])
            
            async with self.connection() as conn:
                # Delete from PostgreSQL
                await conn.execute(
                    "DELETE FROM doc_chunks WHERE document_id = $1",
                    uuid.UUID(document_id)
                )
                await conn.execute(
                    "DELETE FROM documents WHERE id = $1",
                    uuid.UUID(document_id)
                )
            
            # Delete from ChromaDB
            try:
                collection_name = f"subject_{subject_id.replace('-', '_')}"
                collection = self._chroma_client.get_collection(name=collection_name)
                # Chroma delete by where metadata
                collection.delete(where={"document_id": str(document_id)})
                logger.info(f"Deleted chunks for document {document_id} from ChromaDB")
            except Exception as ce:
                logger.warning(f"Could not delete from ChromaDB (collection might not exist): {ce}")
                
            return True
        except Exception as e:
            logger.error(f"Error deleting document {document_id}: {e}")
            return False

    # ==================== Document Chunks Operations ====================
    
    async def create_document_chunks(self, chunks_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create document chunks in PostgreSQL and embeddings in ChromaDB"""
        try:
            if not chunks_data:
                return []
            
            # 1. Store relational data in PostgreSQL
            results = []
            async with self.connection() as conn:
                for chunk in chunks_data:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO doc_chunks (document_id, subject_id, owner_id, chunk_index, text)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id, document_id, chunk_index, text
                        """,
                        uuid.UUID(chunk["document_id"]),
                        uuid.UUID(chunk["subject_id"]),
                        uuid.UUID(chunk["owner_id"]),
                        chunk["chunk_index"],
                        chunk["text"]
                    )
                    if row:
                        results.append(dict(row))
            
            # 2. Store embeddings in ChromaDB
            if results:
                subject_id = str(chunks_data[0]["subject_id"])
                collection = self._chroma_client.get_or_create_collection(
                    name=f"subject_{subject_id.replace('-', '_')}"
                )
                
                ids = [str(r["id"]) for r in results]
                embeddings = [c["embedding"] for c in chunks_data]
                metadatas = [{"document_id": str(c["document_id"]), "chunk_index": c["chunk_index"]} for c in chunks_data]
                documents = [c["text"] for c in chunks_data]
                
                collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=documents
                )
                logger.info(f"Added {len(ids)} chunks to ChromaDB collection for subject {subject_id}")
                
            return results
        except Exception as e:
            logger.error(f"Error creating document chunks: {e}")
            return []
    
    async def search_similar_chunks(
        self, 
        embedding: List[float], 
        subject_id: str, 
        limit: int = 5,
        match_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Search for similar chunks using ChromaDB"""
        try:
            collection_name = f"subject_{subject_id.replace('-', '_')}"
            collection = self._chroma_client.get_or_create_collection(name=collection_name)
            
            results = collection.query(
                query_embeddings=[embedding],
                n_results=limit,
                include=["documents", "metadatas", "distances"]
            )
            
            search_results = []
            if results["ids"] and results["ids"][0]:
                for i in range(len(results["ids"][0])):
                    distance = results["distances"][0][i]
                    # Assuming default is cosine distance (0 to 2, where 0 is identical)
                    # For cosine, similarity = 1 - (distance / 2)? Or if it's cosine similarity...
                    # Chroma default is l2 (squared L2 distance). 
                    # If we use cosine, it's 1.0 - distance.
                    similarity = 1.0 - (distance / 2.0) if distance <= 2.0 else 0.0
                    
                    if similarity >= match_threshold:
                        search_results.append({
                            "id": results["ids"][0][i],
                            "document_id": results["metadatas"][0][i]["document_id"],
                            "text": results["documents"][0][i],
                            "similarity": similarity
                        })
            
            return search_results
        except Exception as e:
            logger.error(f"Error searching similar chunks in ChromaDB: {e}")
            return []

    # ==================== Paper Operations ====================
    
    async def create_paper(self, paper_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new paper"""
        try:
            paper_id = paper_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO papers (id, subject_id, class_id, owner_id, title, description, 
                                       questions, configuration, answer_key, total_marks, is_published)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING *
                    """,
                    uuid.UUID(paper_id),
                    uuid.UUID(paper_data["subject_id"]),
                    uuid.UUID(paper_data["class_id"]) if paper_data.get("class_id") else None,
                    uuid.UUID(paper_data["owner_id"]) if paper_data.get("owner_id") else None,
                    paper_data["title"],
                    paper_data.get("description"),
                    json.dumps(paper_data.get("questions", [])),
                    json.dumps(paper_data.get("configuration", {})),
                    json.dumps(paper_data.get("answer_key", {})),
                    paper_data.get("total_marks", 0),
                    paper_data.get("is_published", False)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating paper: {e}")
            return None
    
    async def get_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """Get paper by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM papers WHERE id = $1",
                    uuid.UUID(paper_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting paper {paper_id}: {e}")
            return None
    
    async def update_paper(self, paper_id: str, paper_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update paper"""
        try:
            set_clauses = []
            values = []
            idx = 1
            
            for key, value in paper_data.items():
                if key == "id":
                    continue
                if key in ["questions", "configuration", "answer_key"]:
                    value = json.dumps(value)
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1
            
            if not set_clauses:
                return await self.get_paper(paper_id)
            
            values.append(uuid.UUID(paper_id))
            query = f"UPDATE papers SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating paper {paper_id}: {e}")
            return None
    
    async def get_papers(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get papers by teacher"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM papers WHERE owner_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(teacher_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting papers for teacher {teacher_id}: {e}")
            return []

    async def get_papers_by_class(self, class_id: str) -> List[Dict[str, Any]]:
        """Get papers by class ID"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM papers WHERE class_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(class_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting papers for class {class_id}: {e}")
            return []

    # ==================== Student Operations ====================
    
    async def create_student(self, student_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new student"""
        try:
            student_id = student_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO students (id, class_id, student_name, student_id, email, phone)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                    """,
                    uuid.UUID(student_id),
                    uuid.UUID(student_data["class_id"]),
                    student_data["student_name"],
                    student_data.get("student_id"),
                    student_data.get("email"),
                    student_data.get("phone")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating student: {e}")
            return None
    
    async def get_students(self, class_id: str) -> List[Dict[str, Any]]:
        """Get students by class"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM students WHERE class_id = $1 ORDER BY student_name",
                    uuid.UUID(class_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting students for class {class_id}: {e}")
            return []
    
    async def get_student(self, student_id: str) -> Optional[Dict[str, Any]]:
        """Get student by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM students WHERE id = $1",
                    uuid.UUID(student_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting student {student_id}: {e}")
            return None
    
    async def update_student(self, student_id: str, student_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update student data"""
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in student_data.items():
                if key != "id":
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
            
            if not set_clauses:
                return await self.get_student(student_id)
            
            values.append(uuid.UUID(student_id))
            query = f"UPDATE students SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating student {student_id}: {e}")
            return None
    
    async def delete_student(self, student_id: str) -> bool:
        """Delete student"""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "DELETE FROM students WHERE id = $1",
                    uuid.UUID(student_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting student {student_id}: {e}")
            return False

    # ==================== Class Operations ====================
    
    async def create_class(self, class_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new class"""
        try:
            class_id = class_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO classes (id, teacher_id, name, description, grade_level, subject_area, academic_year, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING *
                    """,
                    uuid.UUID(class_id),
                    uuid.UUID(class_data["teacher_id"]),
                    class_data["name"],
                    class_data.get("description"),
                    class_data.get("grade_level"),
                    class_data.get("subject_area"),
                    class_data.get("academic_year"),
                    class_data.get("is_active", True)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating class: {e}")
            return None
    
    async def get_classes(self, teacher_id: str) -> List[Dict[str, Any]]:
        """Get classes by teacher"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM classes WHERE teacher_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(teacher_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting classes for teacher {teacher_id}: {e}")
            return []

    async def get_class(self, class_id: str) -> Optional[Dict[str, Any]]:
        """Get class by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM classes WHERE id = $1",
                    uuid.UUID(class_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting class {class_id}: {e}")
            return None

    # ==================== Submission Operations ====================
    
    async def create_submission(self, submission_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create new submission"""
        try:
            sub_id = submission_data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO submissions (id, paper_id, student_id, class_id, student_name, storage_path, 
                                            ocr_text, submission_data, total_score, grade_percentage, feedback, grading_status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    RETURNING *
                    """,
                    uuid.UUID(sub_id),
                    uuid.UUID(submission_data["paper_id"]),
                    uuid.UUID(submission_data["student_id"]) if submission_data.get("student_id") else None,
                    uuid.UUID(submission_data["class_id"]) if submission_data.get("class_id") else None,
                    submission_data.get("student_name", ""),
                    submission_data.get("storage_path"),
                    submission_data.get("ocr_text"),
                    json.dumps(submission_data.get("submission_data", {})) if submission_data.get("submission_data") else None,
                    submission_data.get("total_score"),
                    submission_data.get("grade_percentage"),
                    submission_data.get("feedback"),
                    submission_data.get("grading_status", "pending")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating submission: {e}")
            return None
    
    async def get_submissions(self, paper_id: str) -> List[Dict[str, Any]]:
        """Get submissions by paper"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM submissions WHERE paper_id = $1 ORDER BY created_at DESC",
                    uuid.UUID(paper_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting submissions for paper {paper_id}: {e}")
            return []

    async def get_submission(self, submission_id: str) -> Optional[Dict[str, Any]]:
        """Get single submission by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM submissions WHERE id = $1",
                    uuid.UUID(submission_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting submission {submission_id}: {e}")
            return None
    
    async def update_submission(self, submission_id: str, submission_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update submission"""
        try:
            set_clauses = []
            values = []
            idx = 1
            
            for key, value in submission_data.items():
                if key == "id":
                    continue
                if key == "submission_data" and isinstance(value, dict):
                    value = json.dumps(value)
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1
            
            if not set_clauses:
                return await self.get_submission(submission_id)
            
            values.append(uuid.UUID(submission_id))
            query = f"UPDATE submissions SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating submission {submission_id}: {e}")
            return None

    async def get_submissions_by_status(self, paper_id: str, status: str) -> List[Dict[str, Any]]:
        """Get submissions by paper and grading status"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM submissions WHERE paper_id = $1 AND grading_status = $2",
                    uuid.UUID(paper_id),
                    status
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting submissions for paper {paper_id} with status {status}: {e}")
            return []

    async def delete_submission(self, submission_id: str) -> bool:
        """Delete a submission by ID"""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "DELETE FROM submissions WHERE id = $1",
                    uuid.UUID(submission_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting submission {submission_id}: {e}")
            return False

    # ==================== Additional Query Methods ====================
    
    async def get_doc_chunks_by_subject(self, subject_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get document chunks by subject ID"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT id, document_id, subject_id, owner_id, chunk_index, text FROM doc_chunks WHERE subject_id = $1 LIMIT $2",
                    uuid.UUID(subject_id),
                    limit
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting chunks for subject {subject_id}: {e}")
            return []

    # ==================== Student Account Operations ====================

    async def create_student_account(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a student account (login-capable)"""
        try:
            sid = data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO student_accounts
                        (id, full_name, email, password_hash, phone, date_of_birth, gender,
                         profile_image_url, roll_number, student_id, class_id, is_verified)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    RETURNING *
                    """,
                    uuid.UUID(sid),
                    data["full_name"],
                    data["email"],
                    data["password_hash"],
                    data.get("phone"),
                    data.get("date_of_birth"),
                    data.get("gender"),
                    data.get("profile_image_url"),
                    data.get("roll_number"),
                    data.get("student_id"),
                    uuid.UUID(data["class_id"]) if data.get("class_id") else None,
                    data.get("is_verified", False),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating student account: {e}")
            return None

    async def get_student_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Get student account by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM student_accounts WHERE id = $1",
                    uuid.UUID(account_id),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting student account {account_id}: {e}")
            return None

    async def get_student_account_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get student account by email"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM student_accounts WHERE email = $1",
                    email,
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting student account by email {email}: {e}")
            return None

    async def update_student_account(self, account_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update student account"""
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in data.items():
                if key != "id":
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
            if not set_clauses:
                return await self.get_student_account(account_id)
            values.append(uuid.UUID(account_id))
            query = f"UPDATE student_accounts SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating student account {account_id}: {e}")
            return None

    async def get_student_accounts_by_class(self, class_id: str, verified_only: bool = False) -> List[Dict[str, Any]]:
        """Get all student accounts in a class"""
        try:
            q = "SELECT * FROM student_accounts WHERE class_id = $1"
            if verified_only:
                q += " AND is_verified = TRUE"
            q += " ORDER BY full_name"
            async with self.connection() as conn:
                rows = await conn.fetch(q, uuid.UUID(class_id))
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting student accounts for class {class_id}: {e}")
            return []

    async def get_pending_student_accounts(self, class_id: str) -> List[Dict[str, Any]]:
        """Get unverified student accounts for a class"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM student_accounts WHERE class_id = $1 AND is_verified = FALSE ORDER BY joined_at DESC",
                    uuid.UUID(class_id),
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting pending students for class {class_id}: {e}")
            return []

    # ==================== Class Code Operations ====================

    async def get_class_by_code(self, class_code: str) -> Optional[Dict[str, Any]]:
        """Get class by join code"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM classes WHERE class_code = $1",
                    class_code,
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting class by code {class_code}: {e}")
            return None

    async def set_class_code(self, class_id: str, code: str) -> Optional[Dict[str, Any]]:
        """Set or update class join code"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "UPDATE classes SET class_code = $1, updated_at = NOW() WHERE id = $2 RETURNING *",
                    code,
                    uuid.UUID(class_id),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error setting class code for {class_id}: {e}")
            return None

    async def update_class(self, class_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update class fields"""
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in data.items():
                if key != "id":
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
            if not set_clauses:
                return await self.get_class(class_id)
            values.append(uuid.UUID(class_id))
            query = f"UPDATE classes SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating class {class_id}: {e}")
            return None

    # ==================== Assignment Operations ====================

    async def create_assignment(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new assignment"""
        try:
            aid = data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO assignments
                        (id, teacher_id, subject_id, class_id, title, description, instructions,
                         total_marks, due_date, attachment_url, attachment_filename,
                         grading_rubric, auto_grade, status)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                    RETURNING *
                    """,
                    uuid.UUID(aid),
                    uuid.UUID(data["teacher_id"]),
                    uuid.UUID(data["subject_id"]),
                    uuid.UUID(data["class_id"]),
                    data["title"],
                    data.get("description"),
                    data.get("instructions"),
                    data.get("total_marks", 10),
                    data.get("due_date"),
                    data.get("attachment_url"),
                    data.get("attachment_filename"),
                    data.get("grading_rubric"),
                    data.get("auto_grade", True),
                    data.get("status", "draft"),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating assignment: {e}")
            return None

    async def get_assignment(self, assignment_id: str) -> Optional[Dict[str, Any]]:
        """Get assignment by ID"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM assignments WHERE id = $1",
                    uuid.UUID(assignment_id),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting assignment {assignment_id}: {e}")
            return None

    async def get_assignments(self, teacher_id: str, class_id: str = None, subject_id: str = None, status: str = None) -> List[Dict[str, Any]]:
        """Get assignments with optional filters"""
        try:
            q = "SELECT * FROM assignments WHERE teacher_id = $1"
            params: list = [uuid.UUID(teacher_id)]
            idx = 2
            if class_id:
                q += f" AND class_id = ${idx}"
                params.append(uuid.UUID(class_id))
                idx += 1
            if subject_id:
                q += f" AND subject_id = ${idx}"
                params.append(uuid.UUID(subject_id))
                idx += 1
            if status:
                q += f" AND status = ${idx}"
                params.append(status)
                idx += 1
            q += " ORDER BY created_at DESC"
            async with self.connection() as conn:
                rows = await conn.fetch(q, *params)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting assignments: {e}")
            return []

    async def get_assignments_by_class(self, class_id: str, status: str = None) -> List[Dict[str, Any]]:
        """Get assignments for a class (student view)"""
        try:
            q = "SELECT * FROM assignments WHERE class_id = $1"
            params: list = [uuid.UUID(class_id)]
            if status:
                q += " AND status = $2"
                params.append(status)
            q += " ORDER BY due_date ASC NULLS LAST"
            async with self.connection() as conn:
                rows = await conn.fetch(q, *params)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting assignments for class {class_id}: {e}")
            return []

    async def update_assignment(self, assignment_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update assignment"""
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in data.items():
                if key != "id":
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
            if not set_clauses:
                return await self.get_assignment(assignment_id)
            values.append(uuid.UUID(assignment_id))
            query = f"UPDATE assignments SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating assignment {assignment_id}: {e}")
            return None

    async def delete_assignment(self, assignment_id: str) -> bool:
        """Delete assignment"""
        try:
            async with self.connection() as conn:
                await conn.execute("DELETE FROM assignments WHERE id = $1", uuid.UUID(assignment_id))
                return True
        except Exception as e:
            logger.error(f"Error deleting assignment {assignment_id}: {e}")
            return False

    # ==================== Assignment Submission Operations ====================

    async def create_assignment_submission(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create or update an assignment submission"""
        try:
            sid = data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO assignment_submissions
                        (id, assignment_id, student_account_id, class_id,
                         submission_text, submission_files, status, submitted_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (assignment_id, student_account_id) DO UPDATE SET
                        submission_text = EXCLUDED.submission_text,
                        submission_files = EXCLUDED.submission_files,
                        status = EXCLUDED.status,
                        submitted_at = EXCLUDED.submitted_at,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    uuid.UUID(sid),
                    uuid.UUID(data["assignment_id"]),
                    uuid.UUID(data["student_account_id"]),
                    uuid.UUID(data["class_id"]),
                    data.get("submission_text"),
                    json.dumps(data.get("submission_files", [])),
                    data.get("status", "submitted"),
                    data.get("submitted_at"),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating assignment submission: {e}")
            return None

    async def get_assignment_submission(self, submission_id: str) -> Optional[Dict[str, Any]]:
        """Get single assignment submission"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM assignment_submissions WHERE id = $1",
                    uuid.UUID(submission_id),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting assignment submission {submission_id}: {e}")
            return None

    async def get_assignment_submission_by_student(self, assignment_id: str, student_account_id: str) -> Optional[Dict[str, Any]]:
        """Get a student's submission for an assignment"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM assignment_submissions WHERE assignment_id = $1 AND student_account_id = $2",
                    uuid.UUID(assignment_id),
                    uuid.UUID(student_account_id),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting submission: {e}")
            return None

    async def get_assignment_submissions(self, assignment_id: str) -> List[Dict[str, Any]]:
        """Get all submissions for an assignment"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT s.*, sa.full_name as student_name, sa.roll_number, sa.email as student_email
                    FROM assignment_submissions s
                    JOIN student_accounts sa ON sa.id = s.student_account_id
                    WHERE s.assignment_id = $1
                    ORDER BY s.submitted_at DESC NULLS LAST
                    """,
                    uuid.UUID(assignment_id),
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting submissions for assignment {assignment_id}: {e}")
            return []

    async def update_assignment_submission(self, submission_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update assignment submission (for grading results, etc.)"""
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in data.items():
                if key == "id":
                    continue
                if key == "ai_rubric_breakdown" and isinstance(value, (dict, list)):
                    value = json.dumps(value)
                if key == "submission_files" and isinstance(value, list):
                    value = json.dumps(value)
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1
            if not set_clauses:
                return await self.get_assignment_submission(submission_id)
            values.append(uuid.UUID(submission_id))
            query = f"UPDATE assignment_submissions SET {', '.join(set_clauses)}, updated_at = NOW() WHERE id = ${idx} RETURNING *"
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating assignment submission {submission_id}: {e}")
            return None

    async def get_student_submissions(self, student_account_id: str) -> List[Dict[str, Any]]:
        """Get all submissions for a student across assignments"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT s.*, a.title as assignment_title, a.total_marks as assignment_total_marks,
                           a.due_date as assignment_due_date, a.subject_id
                    FROM assignment_submissions s
                    JOIN assignments a ON a.id = s.assignment_id
                    WHERE s.student_account_id = $1
                    ORDER BY s.submitted_at DESC NULLS LAST
                    """,
                    uuid.UUID(student_account_id),
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting submissions for student {student_account_id}: {e}")
            return []

    # ==================== Student Scores Operations ====================

    async def create_student_score(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Record a student score"""
        try:
            sid = data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO student_scores
                        (id, student_account_id, class_id, subject_id, score_type,
                         reference_id, title, marks_obtained, max_marks, percentage, grade)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    RETURNING *
                    """,
                    uuid.UUID(sid),
                    uuid.UUID(data["student_account_id"]),
                    uuid.UUID(data["class_id"]),
                    uuid.UUID(data["subject_id"]) if data.get("subject_id") else None,
                    data["score_type"],
                    uuid.UUID(data["reference_id"]),
                    data.get("title"),
                    data.get("marks_obtained"),
                    data.get("max_marks"),
                    data.get("percentage"),
                    data.get("grade"),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating student score: {e}")
            return None

    async def get_student_scores(self, student_account_id: str, class_id: str = None, subject_id: str = None) -> List[Dict[str, Any]]:
        """Get scores for a student"""
        try:
            q = "SELECT * FROM student_scores WHERE student_account_id = $1"
            params: list = [uuid.UUID(student_account_id)]
            idx = 2
            if class_id:
                q += f" AND class_id = ${idx}"
                params.append(uuid.UUID(class_id))
                idx += 1
            if subject_id:
                q += f" AND subject_id = ${idx}"
                params.append(uuid.UUID(subject_id))
                idx += 1
            q += " ORDER BY scored_at DESC"
            async with self.connection() as conn:
                rows = await conn.fetch(q, *params)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting scores for student {student_account_id}: {e}")
            return []

    # ==================== Class Overview Helpers ====================

    async def get_class_overview(self, class_id: str) -> Dict[str, Any]:
        """Get aggregated overview for a class"""
        try:
            async with self.connection() as conn:
                cid = uuid.UUID(class_id)
                student_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM student_accounts WHERE class_id = $1", cid
                ) or 0
                subject_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM subjects WHERE class_id = $1", cid
                ) or 0
                assignment_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM assignments WHERE class_id = $1", cid
                ) or 0
                paper_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM papers WHERE class_id = $1", cid
                ) or 0
                pending_students = await conn.fetchval(
                    "SELECT COUNT(*) FROM student_accounts WHERE class_id = $1 AND is_verified = FALSE", cid
                ) or 0
                return {
                    "student_count": student_count,
                    "subject_count": subject_count,
                    "assignment_count": assignment_count,
                    "paper_count": paper_count,
                    "pending_students": pending_students,
                }
        except Exception as e:
            logger.error(f"Error getting class overview for {class_id}: {e}")
            return {"student_count": 0, "subject_count": 0, "assignment_count": 0, "paper_count": 0, "pending_students": 0}

    async def get_subjects_by_class(self, class_id: str) -> List[Dict[str, Any]]:
        """Get subjects belonging to a class"""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM subjects WHERE class_id = $1 ORDER BY name",
                    uuid.UUID(class_id),
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting subjects for class {class_id}: {e}")
            return []


# Global instance
_database_service: Optional[DatabaseService] = None


async def get_database() -> DatabaseService:
    """Get database service instance (initializes on first call)"""
    global _database_service
    if _database_service is None:
        _database_service = DatabaseService()
        await _database_service.initialize()
    return _database_service


def get_database_sync() -> DatabaseService:
    """Get database service instance (sync version, assumes already initialized)"""
    global _database_service
    if _database_service is None:
        _database_service = DatabaseService()
    return _database_service
