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
from urllib.parse import unquote, urlsplit, urlunsplit

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
        default_paper_template TEXT DEFAULT 'formal',
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
    ALTER TABLE teachers ADD COLUMN IF NOT EXISTS default_paper_template TEXT DEFAULT 'formal';

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
        word_count INTEGER,
        chunk_count INTEGER,
        processing_status TEXT DEFAULT 'pending' CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
        processing_progress INTEGER DEFAULT 0,
        processing_stage TEXT DEFAULT '',
        processing_error TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    -- Live migrations for existing databases
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS word_count INTEGER;
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER;
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_progress INTEGER DEFAULT 0;
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_stage TEXT DEFAULT '';
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_error TEXT;

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
        notification_type TEXT NOT NULL DEFAULT 'system',
        is_read BOOLEAN DEFAULT FALSE,
        metadata JSONB,
        student_account_id UUID,
        audience TEXT DEFAULT 'teacher',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    -- Drop old restrictive CHECK constraint so we can use richer notification types
    ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_notification_type_check;

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

    ALTER TABLE assignments ADD COLUMN IF NOT EXISTS attachment_url TEXT;
    ALTER TABLE assignments ADD COLUMN IF NOT EXISTS attachment_filename TEXT;

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
        source TEXT DEFAULT 'student_portal',
        status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'grading', 'graded', 'returned')),
        submitted_at TIMESTAMP WITH TIME ZONE,
        graded_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE (assignment_id, student_account_id)
    );

    ALTER TABLE assignment_submissions ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'student_portal';

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

    CREATE TABLE IF NOT EXISTS schedule_events (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('class', 'quiz', 'assignment', 'paper', 'personal')),
        class_id UUID REFERENCES classes(id) ON DELETE SET NULL,
        is_all_day BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_schedule_events_teacher ON schedule_events(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_schedule_events_date ON schedule_events(date);

    DROP TRIGGER IF EXISTS update_schedule_events_updated_at ON schedule_events;
    CREATE TRIGGER update_schedule_events_updated_at BEFORE UPDATE ON schedule_events
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

    CREATE TABLE IF NOT EXISTS attendance_records (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE NOT NULL,
        class_id UUID REFERENCES classes(id) ON DELETE CASCADE NOT NULL,
        subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
        student_id UUID REFERENCES students(id) ON DELETE CASCADE NOT NULL,
        date DATE NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late', 'excused')),
        remarks TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE(class_id, subject_id, student_id, date)
    );

    -- ==================== Email Integration Tables ====================

    CREATE TABLE IF NOT EXISTS email_integrations (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE NOT NULL UNIQUE,
        email_address TEXT NOT NULL,
        imap_host TEXT NOT NULL DEFAULT 'imap.gmail.com',
        imap_port INTEGER NOT NULL DEFAULT 993,
        app_password TEXT NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        last_fetched_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS email_submission_logs (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        teacher_id UUID REFERENCES teachers(id) ON DELETE CASCADE NOT NULL,
        assignment_id UUID REFERENCES assignments(id) ON DELETE SET NULL,
        student_account_id UUID REFERENCES student_accounts(id) ON DELETE SET NULL,
        email_from TEXT,
        email_subject TEXT,
        email_body TEXT,
        attachment_paths JSONB DEFAULT '[]',
        processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        status TEXT DEFAULT 'processed' CHECK (status IN ('processed', 'failed', 'skipped')),
        notes TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_email_integrations_teacher ON email_integrations(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_email_logs_teacher ON email_submission_logs(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_email_logs_assignment ON email_submission_logs(assignment_id);

    CREATE INDEX IF NOT EXISTS idx_attendance_teacher ON attendance_records(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance_records(student_id);
    CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance_records(date);

    DROP TRIGGER IF EXISTS update_attendance_records_updated_at ON attendance_records;
    CREATE TRIGGER update_attendance_records_updated_at BEFORE UPDATE ON attendance_records
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
            parsed = urlsplit(db_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("database URL must include scheme and host")
            db_name = unquote(parsed.path.lstrip("/"))
            if not db_name:
                logger.warning("Database URL has no database name - skipping auto-create.")
                return
            postgres_url = urlunsplit(
                (parsed.scheme, parsed.netloc, "/postgres", parsed.query, parsed.fragment)
            )
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
                safe_db_name = db_name.replace('"', '""')
                await conn.execute(f'CREATE DATABASE "{safe_db_name}"')
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
                    teacher_data.get("default_paper_template", "formal")
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
                    "SELECT id, chunk_index, chunk_type, text, metadata FROM doc_chunks WHERE document_id = $1 ORDER BY chunk_index",
                    uuid.UUID(document_id)
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting chunks for document {document_id}: {e}")
            return []

    async def update_document_progress(
        self,
        document_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        stage: Optional[str] = None,
        error: Optional[str] = None,
        page_count: Optional[int] = None,
        word_count: Optional[int] = None,
        chunk_count: Optional[int] = None,
    ) -> bool:
        """Update document processing state atomically (progress, stage, status, stats)."""
        try:
            parts = ["updated_at = NOW()"]
            vals: list = []
            idx = 1

            if status is not None:
                parts.append(f"processing_status = ${idx}"); vals.append(status); idx += 1
            if progress is not None:
                parts.append(f"processing_progress = ${idx}"); vals.append(max(0, min(100, progress))); idx += 1
            if stage is not None:
                parts.append(f"processing_stage = ${idx}"); vals.append(stage); idx += 1
            if error is not None:
                parts.append(f"processing_error = ${idx}"); vals.append(error); idx += 1
            if page_count is not None:
                parts.append(f"page_count = ${idx}"); vals.append(page_count); idx += 1
            if word_count is not None:
                parts.append(f"word_count = ${idx}"); vals.append(word_count); idx += 1
            if chunk_count is not None:
                parts.append(f"chunk_count = ${idx}"); vals.append(chunk_count); idx += 1

            vals.append(uuid.UUID(document_id))
            async with self.connection() as conn:
                await conn.execute(
                    f"UPDATE documents SET {', '.join(parts)} WHERE id = ${idx}",
                    *vals,
                )
            return True
        except Exception as e:
            logger.error(f"Error updating document progress {document_id}: {e}")
            return False

    async def update_document_status(self, document_id: str, status: str) -> bool:
        """Thin wrapper kept for backward-compat — delegates to update_document_progress."""
        return await self.update_document_progress(document_id, status=status)


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
        """
        Store document chunks in PostgreSQL (with chunk_type, metadata) and embeddings in ChromaDB.
        Uses executemany-style batching for fast bulk inserts on large documents.
        """
        try:
            if not chunks_data:
                return []

            results = []
            async with self.connection() as conn:
                # Use copy_records_to_table for very large batches when available,
                # otherwise fall back to individual inserts with RETURNING.
                for chunk in chunks_data:
                    raw_meta = chunk.get("metadata")
                    meta_json = json.dumps(raw_meta) if raw_meta and not isinstance(raw_meta, str) else (raw_meta or "{}")
                    # Map chunk_type to allowed values
                    ct = chunk.get("chunk_type", "paragraph")
                    if ct not in ("section", "paragraph", "list", "table"):
                        ct = "paragraph"
                    row = await conn.fetchrow(
                        """
                        INSERT INTO doc_chunks
                            (document_id, subject_id, owner_id, chunk_index, chunk_type, text, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        RETURNING id, document_id, chunk_index, text
                        """,
                        uuid.UUID(chunk["document_id"]),
                        uuid.UUID(chunk["subject_id"]),
                        uuid.UUID(chunk["owner_id"]),
                        chunk["chunk_index"],
                        ct,
                        chunk["text"],
                        meta_json,
                    )
                    if row:
                        results.append(dict(row))

            # Store embeddings in ChromaDB
            if results:
                subject_id = str(chunks_data[0]["subject_id"])
                try:
                    collection = self._chroma_client.get_or_create_collection(
                        name=f"subject_{subject_id.replace('-', '_')}"
                    )
                    ids        = [str(r["id"]) for r in results]
                    embeddings = [c["embedding"] for c in chunks_data if c.get("embedding")]
                    metas      = [
                        {
                            "document_id": str(c["document_id"]),
                            "chunk_index": c["chunk_index"],
                            "chunk_type": c.get("chunk_type", "paragraph"),
                        }
                        for c in chunks_data
                    ]
                    documents = [c["text"] for c in chunks_data]

                    # ChromaDB batches of 5000 (its internal limit)
                    CHROMA_BATCH = 5000
                    for b in range(0, len(ids), CHROMA_BATCH):
                        collection.add(
                            ids=ids[b:b+CHROMA_BATCH],
                            embeddings=embeddings[b:b+CHROMA_BATCH],
                            metadatas=metas[b:b+CHROMA_BATCH],
                            documents=documents[b:b+CHROMA_BATCH],
                        )
                    logger.info(f"Added {len(ids)} chunks to ChromaDB for subject {subject_id}")
                except Exception as chroma_err:
                    logger.warning(f"ChromaDB store failed (postgres still saved): {chroma_err}")

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
                    """
                    SELECT a.*, c.name AS class_name, s.name AS subject_name
                    FROM assignments a
                    LEFT JOIN classes c ON c.id = a.class_id
                    LEFT JOIN subjects s ON s.id = a.subject_id
                    WHERE a.id = $1
                    """,
                    uuid.UUID(assignment_id),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting assignment {assignment_id}: {e}")
            return None

    async def get_assignments(self, teacher_id: str, class_id: str = None, subject_id: str = None, status: str = None) -> List[Dict[str, Any]]:
        """Get assignments with optional filters"""
        try:
            q = """
                SELECT a.*, c.name AS class_name, s.name AS subject_name
                FROM assignments a
                LEFT JOIN classes c ON c.id = a.class_id
                LEFT JOIN subjects s ON s.id = a.subject_id
                WHERE a.teacher_id = $1
            """
            params: list = [uuid.UUID(teacher_id)]
            idx = 2
            if class_id:
                q += f" AND a.class_id = ${idx}"
                params.append(uuid.UUID(class_id))
                idx += 1
            if subject_id:
                q += f" AND a.subject_id = ${idx}"
                params.append(uuid.UUID(subject_id))
                idx += 1
            if status:
                q += f" AND a.status = ${idx}"
                params.append(status)
                idx += 1
            q += " ORDER BY a.created_at DESC"
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
                         submission_text, submission_files, source, status, submitted_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (assignment_id, student_account_id) DO UPDATE SET
                        submission_text = EXCLUDED.submission_text,
                        submission_files = EXCLUDED.submission_files,
                        source = EXCLUDED.source,
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
                    data.get("source", "student_portal"),
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
                    """
                    SELECT
                        s.*,
                        a.title AS assignment_title,
                        a.subject_id,
                        a.due_date AS assignment_due_date,
                        c.name AS class_name,
                        subj.name AS subject_name,
                        sa.full_name AS student_name,
                        sa.roll_number,
                        sa.email AS student_email
                    FROM assignment_submissions s
                    JOIN assignments a ON a.id = s.assignment_id
                    LEFT JOIN classes c ON c.id = s.class_id
                    LEFT JOIN subjects subj ON subj.id = a.subject_id
                    LEFT JOIN student_accounts sa ON sa.id = s.student_account_id
                    WHERE s.id = $1
                    """,
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
                    SELECT
                        s.*,
                        a.title AS assignment_title,
                        a.subject_id,
                        a.due_date AS assignment_due_date,
                        c.name AS class_name,
                        subj.name AS subject_name,
                        sa.full_name AS student_name,
                        sa.roll_number,
                        sa.email AS student_email
                    FROM assignment_submissions s
                    JOIN assignments a ON a.id = s.assignment_id
                    LEFT JOIN classes c ON c.id = s.class_id
                    LEFT JOIN subjects subj ON subj.id = a.subject_id
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

    # ==================== Schedule Operations ====================

    async def create_schedule_event(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            event_id = data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO schedule_events (
                        id, teacher_id, title, description, date, start_time, end_time, type, class_id, is_all_day
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING *
                    """,
                    uuid.UUID(event_id),
                    uuid.UUID(data["teacher_id"]),
                    data["title"],
                    data.get("description"),
                    data["date"],
                    data["start_time"],
                    data["end_time"],
                    data["type"],
                    uuid.UUID(data["class_id"]) if data.get("class_id") else None,
                    data.get("is_all_day", False)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating schedule event: {e}")
            return None

    async def get_schedule_events(self, teacher_id: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        try:
            q = "SELECT e.*, c.name as class_name FROM schedule_events e LEFT JOIN classes c ON e.class_id = c.id WHERE e.teacher_id = $1"
            params: list = [uuid.UUID(teacher_id)]
            idx = 2
            if start_date:
                q += f" AND e.date >= ${idx}"
                params.append(start_date)
                idx += 1
            if end_date:
                q += f" AND e.date <= ${idx}"
                params.append(end_date)
                idx += 1
            
            q += " ORDER BY e.date ASC, e.start_time ASC"
            
            async with self.connection() as conn:
                rows = await conn.fetch(q, *params)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting schedule events for teacher {teacher_id}: {e}")
            return []

    async def get_schedule_event(self, event_id: str, teacher_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM schedule_events WHERE id = $1 AND teacher_id = $2",
                    uuid.UUID(event_id), uuid.UUID(teacher_id)
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting schedule event {event_id}: {e}")
            return None

    async def update_schedule_event(self, event_id: str, teacher_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            set_clauses = []
            values = []
            idx = 1
            for key, value in data.items():
                if key in ["title", "description", "date", "start_time", "end_time", "type", "class_id", "is_all_day"]:
                    if key == "class_id" and value:
                        value = uuid.UUID(value)
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
            
            if not set_clauses:
                return await self.get_schedule_event(event_id, teacher_id)
            
            values.append(uuid.UUID(event_id))
            values.append(uuid.UUID(teacher_id))
            
            query = f"UPDATE schedule_events SET {', '.join(set_clauses)} WHERE id = ${idx} AND teacher_id = ${idx+1} RETURNING *"
            
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *values)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error updating schedule event {event_id}: {e}")
            return None

    async def delete_schedule_event(self, event_id: str, teacher_id: str) -> bool:
        try:
            async with self.connection() as conn:
                res = await conn.execute(
                    "DELETE FROM schedule_events WHERE id = $1 AND teacher_id = $2",
                    uuid.UUID(event_id), uuid.UUID(teacher_id)
                )
                return res.split(" ")[-1] == "1"
        except Exception as e:
            logger.error(f"Error deleting schedule event {event_id}: {e}")
            return False

    # ==================== Attendance Operations ====================

    async def get_attendance_records(self, teacher_id: str, class_id: str, subject_id: str, date: str) -> List[Dict[str, Any]]:
        try:
            from datetime import datetime
            q = "SELECT * FROM attendance_records WHERE teacher_id = $1 AND class_id = $2 AND subject_id = $3 AND date = $4"
            params: list = [uuid.UUID(teacher_id), uuid.UUID(class_id), uuid.UUID(subject_id), datetime.strptime(date, "%Y-%m-%d").date()]
            async with self.connection() as conn:
                rows = await conn.fetch(q, *params)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting attendance: {e}")
            return []

    async def upsert_attendance_record(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            from datetime import datetime
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO attendance_records (teacher_id, class_id, subject_id, student_id, date, status, remarks)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (class_id, subject_id, student_id, date) DO UPDATE 
                    SET status = EXCLUDED.status, remarks = EXCLUDED.remarks, updated_at = NOW()
                    RETURNING *
                    """,
                    uuid.UUID(data["teacher_id"]),
                    uuid.UUID(data["class_id"]),
                    uuid.UUID(data["subject_id"]),
                    uuid.UUID(data["student_id"]),
                    datetime.strptime(data["date"], "%Y-%m-%d").date(),
                    data["status"],
                    data.get("remarks")
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error upserting attendance: {e}")
            return None

    async def get_attendance_range(self, teacher_id: str, class_id: str, subject_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get all attendance records in a date range, joining student names."""
        try:
            from datetime import datetime
            async with self.connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT ar.*, s.student_name, s.student_id AS roll_number
                    FROM attendance_records ar
                    JOIN students s ON ar.student_id = s.id
                    WHERE ar.teacher_id = $1 AND ar.class_id = $2 AND ar.subject_id = $3
                      AND ar.date BETWEEN $4 AND $5
                    ORDER BY ar.date DESC, s.student_name
                    """,
                    uuid.UUID(teacher_id),
                    uuid.UUID(class_id),
                    uuid.UUID(subject_id),
                    datetime.strptime(start_date, "%Y-%m-%d").date(),
                    datetime.strptime(end_date, "%Y-%m-%d").date(),
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting attendance range: {e}")
            return []

    async def get_attendance_history(self, teacher_id: str, class_id: str, subject_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Return recent distinct session dates with per-date status counts."""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        date,
                        COUNT(*) FILTER (WHERE status = 'present') AS present,
                        COUNT(*) FILTER (WHERE status = 'absent')  AS absent,
                        COUNT(*) FILTER (WHERE status = 'late')    AS late,
                        COUNT(*) FILTER (WHERE status = 'excused') AS excused,
                        COUNT(*) AS total
                    FROM attendance_records
                    WHERE teacher_id = $1 AND class_id = $2 AND subject_id = $3
                    GROUP BY date
                    ORDER BY date DESC
                    LIMIT $4
                    """,
                    uuid.UUID(teacher_id),
                    uuid.UUID(class_id),
                    uuid.UUID(subject_id),
                    limit,
                )
                result = []
                for row in rows:
                    d = dict(row)
                    d["date"] = str(d["date"])
                    total = d["total"] or 1
                    d["attendance_rate"] = round((d["present"] + d["late"]) / total * 100, 1)
                    result.append(d)
                return result
        except Exception as e:
            logger.error(f"Error getting attendance history: {e}")
            return []

    async def get_class_attendance_analytics(self, teacher_id: str, class_id: str, subject_id: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """Comprehensive class-level analytics for a date range."""
        try:
            from datetime import datetime
            s_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            e_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            tid = uuid.UUID(teacher_id)
            cid = uuid.UUID(class_id)
            sid = uuid.UUID(subject_id)

            async with self.connection() as conn:
                # Overall totals
                totals = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) AS total_records,
                        COUNT(*) FILTER (WHERE status = 'present') AS present,
                        COUNT(*) FILTER (WHERE status = 'absent')  AS absent,
                        COUNT(*) FILTER (WHERE status = 'late')    AS late,
                        COUNT(*) FILTER (WHERE status = 'excused') AS excused,
                        COUNT(DISTINCT date)                       AS total_sessions
                    FROM attendance_records
                    WHERE teacher_id = $1 AND class_id = $2 AND subject_id = $3
                      AND date BETWEEN $4 AND $5
                    """,
                    tid, cid, sid, s_date, e_date
                )

                # Per-date trend
                trend_rows = await conn.fetch(
                    """
                    SELECT
                        date,
                        COUNT(*) FILTER (WHERE status = 'present') AS present,
                        COUNT(*) FILTER (WHERE status = 'absent')  AS absent,
                        COUNT(*) FILTER (WHERE status = 'late')    AS late,
                        COUNT(*) FILTER (WHERE status = 'excused') AS excused,
                        COUNT(*) AS total
                    FROM attendance_records
                    WHERE teacher_id = $1 AND class_id = $2 AND subject_id = $3
                      AND date BETWEEN $4 AND $5
                    GROUP BY date
                    ORDER BY date
                    """,
                    tid, cid, sid, s_date, e_date
                )

                # Per-student summary
                student_rows = await conn.fetch(
                    """
                    SELECT
                        ar.student_id,
                        s.student_name,
                        s.student_id AS roll_number,
                        COUNT(*) FILTER (WHERE ar.status = 'present') AS present,
                        COUNT(*) FILTER (WHERE ar.status = 'absent')  AS absent,
                        COUNT(*) FILTER (WHERE ar.status = 'late')    AS late,
                        COUNT(*) FILTER (WHERE ar.status = 'excused') AS excused,
                        COUNT(*) AS total
                    FROM attendance_records ar
                    JOIN students s ON ar.student_id = s.id
                    WHERE ar.teacher_id = $1 AND ar.class_id = $2 AND ar.subject_id = $3
                      AND ar.date BETWEEN $4 AND $5
                    GROUP BY ar.student_id, s.student_name, s.student_id
                    ORDER BY s.student_name
                    """,
                    tid, cid, sid, s_date, e_date
                )

            t = dict(totals)
            total_r = t["total_records"] or 1
            trend = []
            for row in trend_rows:
                d = dict(row)
                d["date"] = str(d["date"])
                tot = d["total"] or 1
                d["rate"] = round((d["present"] + d["late"]) / tot * 100, 1)
                trend.append(d)

            students = []
            for row in student_rows:
                d = dict(row)
                d["student_id"] = str(d["student_id"])
                tot = d["total"] or 1
                d["attendance_pct"] = round((d["present"] + d["late"]) / tot * 100, 1)
                students.append(d)

            low_attendance = [s for s in students if s["attendance_pct"] < 75]

            return {
                "total_sessions": t["total_sessions"],
                "total_records": t["total_records"],
                "present": t["present"],
                "absent": t["absent"],
                "late": t["late"],
                "excused": t["excused"],
                "overall_rate": round((t["present"] + t["late"]) / total_r * 100, 1) if total_r else 0,
                "trend": trend,
                "students": students,
                "low_attendance": low_attendance,
                "start_date": start_date,
                "end_date": end_date,
            }
        except Exception as e:
            logger.error(f"Error getting class analytics: {e}")
            return {}

    async def get_student_attendance_analytics(self, teacher_id: str, student_id: str, class_id: str, subject_id: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """Detailed analytics for a single student."""
        try:
            from datetime import datetime
            s_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            e_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            tid = uuid.UUID(teacher_id)
            stid = uuid.UUID(student_id)
            cid = uuid.UUID(class_id)
            sid = uuid.UUID(subject_id)

            async with self.connection() as conn:
                # Student info
                student = await conn.fetchrow("SELECT * FROM students WHERE id = $1", stid)

                # Summary totals
                totals = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'present') AS present,
                        COUNT(*) FILTER (WHERE status = 'absent')  AS absent,
                        COUNT(*) FILTER (WHERE status = 'late')    AS late,
                        COUNT(*) FILTER (WHERE status = 'excused') AS excused,
                        COUNT(*) AS total
                    FROM attendance_records
                    WHERE teacher_id = $1 AND student_id = $2 AND class_id = $3 AND subject_id = $4
                      AND date BETWEEN $5 AND $6
                    """,
                    tid, stid, cid, sid, s_date, e_date
                )

                # All records
                records = await conn.fetch(
                    """
                    SELECT date, status, remarks
                    FROM attendance_records
                    WHERE teacher_id = $1 AND student_id = $2 AND class_id = $3 AND subject_id = $4
                      AND date BETWEEN $5 AND $6
                    ORDER BY date DESC
                    """,
                    tid, stid, cid, sid, s_date, e_date
                )

                # Monthly breakdown
                monthly = await conn.fetch(
                    """
                    SELECT
                        TO_CHAR(date, 'YYYY-MM') AS month,
                        COUNT(*) FILTER (WHERE status = 'present') AS present,
                        COUNT(*) FILTER (WHERE status = 'absent')  AS absent,
                        COUNT(*) FILTER (WHERE status = 'late')    AS late,
                        COUNT(*) FILTER (WHERE status = 'excused') AS excused,
                        COUNT(*) AS total
                    FROM attendance_records
                    WHERE teacher_id = $1 AND student_id = $2 AND class_id = $3 AND subject_id = $4
                      AND date BETWEEN $5 AND $6
                    GROUP BY month
                    ORDER BY month
                    """,
                    tid, stid, cid, sid, s_date, e_date
                )

            t = dict(totals)
            total = t["total"] or 1
            attendance_pct = round((t["present"] + t["late"]) / total * 100, 1)

            rec_list = []
            for r in records:
                d = dict(r)
                d["date"] = str(d["date"])
                rec_list.append(d)

            monthly_list = []
            for m in monthly:
                d = dict(m)
                tot = d["total"] or 1
                d["rate"] = round((d["present"] + d["late"]) / tot * 100, 1)
                monthly_list.append(d)

            return {
                "student_name": student["student_name"] if student else "Unknown",
                "roll_number": student["student_id"] if student else "",
                "total_sessions": t["total"],
                "present": t["present"],
                "absent": t["absent"],
                "late": t["late"],
                "excused": t["excused"],
                "attendance_pct": attendance_pct,
                "records": rec_list,
                "monthly": monthly_list,
                "start_date": start_date,
                "end_date": end_date,
            }
        except Exception as e:
            logger.error(f"Error getting student analytics: {e}")
            return {}

    async def get_attendance_overview(self, teacher_id: str, class_id: str, subject_id: str) -> Dict[str, Any]:
        """High-level overview: heatmap data, overall stats, alerts."""
        try:
            from datetime import date, timedelta
            tid = uuid.UUID(teacher_id)
            cid = uuid.UUID(class_id)
            sid = uuid.UUID(subject_id)
            today = date.today()
            twelve_weeks_ago = today - timedelta(weeks=12)

            async with self.connection() as conn:
                # Totals ever
                totals = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(DISTINCT date) AS total_sessions,
                        COUNT(*) FILTER (WHERE status = 'present') AS present,
                        COUNT(*) FILTER (WHERE status = 'absent')  AS absent,
                        COUNT(*) FILTER (WHERE status = 'late')    AS late,
                        COUNT(*) FILTER (WHERE status = 'excused') AS excused,
                        COUNT(*) AS total_records
                    FROM attendance_records
                    WHERE teacher_id = $1 AND class_id = $2 AND subject_id = $3
                    """,
                    tid, cid, sid
                )

                # Heatmap: daily counts for last 12 weeks
                heatmap_rows = await conn.fetch(
                    """
                    SELECT
                        date,
                        COUNT(*) FILTER (WHERE status IN ('present', 'late')) AS attended,
                        COUNT(*) AS total
                    FROM attendance_records
                    WHERE teacher_id = $1 AND class_id = $2 AND subject_id = $3
                      AND date >= $4
                    GROUP BY date
                    ORDER BY date
                    """,
                    tid, cid, sid, twelve_weeks_ago
                )

                # Students below 75%
                low_rows = await conn.fetch(
                    """
                    SELECT
                        ar.student_id,
                        s.student_name,
                        COUNT(*) FILTER (WHERE ar.status IN ('present','late')) AS attended,
                        COUNT(*) AS total
                    FROM attendance_records ar
                    JOIN students s ON ar.student_id = s.id
                    WHERE ar.teacher_id = $1 AND ar.class_id = $2 AND ar.subject_id = $3
                    GROUP BY ar.student_id, s.student_name
                    HAVING COUNT(*) > 0
                    """,
                    tid, cid, sid
                )

            t = dict(totals)
            total_r = t["total_records"] or 1

            heatmap = []
            for row in heatmap_rows:
                d = dict(row)
                d["date"] = str(d["date"])
                d["rate"] = round(d["attended"] / (d["total"] or 1) * 100, 1)
                heatmap.append(d)

            at_risk = []
            for row in low_rows:
                d = dict(row)
                d["student_id"] = str(d["student_id"])
                pct = round(d["attended"] / (d["total"] or 1) * 100, 1)
                d["attendance_pct"] = pct
                if pct < 75:
                    at_risk.append(d)

            at_risk.sort(key=lambda x: x["attendance_pct"])

            return {
                "total_sessions": t["total_sessions"],
                "total_records": t["total_records"],
                "present": t["present"],
                "absent": t["absent"],
                "late": t["late"],
                "excused": t["excused"],
                "overall_rate": round((t["present"] + t["late"]) / total_r * 100, 1) if total_r else 0,
                "heatmap": heatmap,
                "at_risk_students": at_risk,
                "at_risk_count": len(at_risk),
            }
        except Exception as e:
            logger.error(f"Error getting attendance overview: {e}")
            return {}

    async def get_student_accounts_by_class(self, class_id: str, verified_only: bool = False) -> List[Dict[str, Any]]:
        """Get all student accounts for a class"""
        try:
            q = "SELECT * FROM student_accounts WHERE class_id = $1"
            params: list = [uuid.UUID(class_id)]
            if verified_only:
                q += " AND is_verified = TRUE"
            q += " ORDER BY full_name"
            async with self.connection() as conn:
                rows = await conn.fetch(q, *params)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting student accounts for class {class_id}: {e}")
            return []

    # ==================== Email Integration Operations ====================

    async def save_email_config(self, teacher_id: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Save or update teacher email integration config"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO email_integrations (teacher_id, email_address, imap_host, imap_port, app_password, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (teacher_id) DO UPDATE SET
                        email_address = EXCLUDED.email_address,
                        imap_host = EXCLUDED.imap_host,
                        imap_port = EXCLUDED.imap_port,
                        app_password = EXCLUDED.app_password,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    uuid.UUID(teacher_id),
                    config["email_address"],
                    config.get("imap_host", "imap.gmail.com"),
                    config.get("imap_port", 993),
                    config["app_password"],
                    config.get("is_active", True),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error saving email config for teacher {teacher_id}: {e}")
            return None

    async def get_email_config(self, teacher_id: str) -> Optional[Dict[str, Any]]:
        """Get teacher email integration config"""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM email_integrations WHERE teacher_id = $1",
                    uuid.UUID(teacher_id),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting email config for teacher {teacher_id}: {e}")
            return None

    async def update_email_last_fetched(self, teacher_id: str) -> bool:
        """Record the latest successful email sync time for a teacher."""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "UPDATE email_integrations SET last_fetched_at = NOW(), updated_at = NOW() WHERE teacher_id = $1",
                    uuid.UUID(teacher_id),
                )
                return True
        except Exception as e:
            logger.error(f"Error updating email last_fetched_at for teacher {teacher_id}: {e}")
            return False

    async def create_email_submission_log(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Log a processed email submission"""
        try:
            lid = data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO email_submission_logs
                        (id, teacher_id, assignment_id, student_account_id, email_from,
                         email_subject, email_body, attachment_paths, processed_at, status, notes)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    RETURNING *
                    """,
                    uuid.UUID(lid),
                    uuid.UUID(data["teacher_id"]),
                    uuid.UUID(data["assignment_id"]) if data.get("assignment_id") else None,
                    uuid.UUID(data["student_account_id"]) if data.get("student_account_id") else None,
                    data.get("email_from"),
                    data.get("email_subject"),
                    data.get("email_body"),
                    json.dumps(data.get("attachment_paths", [])),
                    data.get("processed_at"),
                    data.get("status", "processed"),
                    data.get("notes"),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating email submission log: {e}")
            return None

    async def get_email_submission_logs(self, teacher_id: str, assignment_id: str = None) -> List[Dict[str, Any]]:
        """Get email submission logs for a teacher"""
        try:
            q = """
                SELECT
                    l.*,
                    a.title AS assignment_title,
                    a.class_id,
                    a.subject_id,
                    c.name AS class_name,
                    subj.name AS subject_name,
                    sa.full_name AS student_name,
                    sa.email AS student_email
                FROM email_submission_logs l
                LEFT JOIN assignments a ON a.id = l.assignment_id
                LEFT JOIN classes c ON c.id = a.class_id
                LEFT JOIN subjects subj ON subj.id = a.subject_id
                LEFT JOIN student_accounts sa ON sa.id = l.student_account_id
                WHERE l.teacher_id = $1
            """
            params: list = [uuid.UUID(teacher_id)]
            if assignment_id:
                q += " AND l.assignment_id = $2"
                params.append(uuid.UUID(assignment_id))
            q += " ORDER BY l.processed_at DESC"
            async with self.connection() as conn:
                rows = await conn.fetch(q, *params)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting email submission logs: {e}")
            return []

    async def get_students_attendance_summary(self, teacher_id: str, class_id: str, subject_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Per-student attendance summary with percentage."""
        try:
            from datetime import datetime
            s_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            e_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            async with self.connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        ar.student_id,
                        s.student_name,
                        s.student_id AS roll_number,
                        COUNT(*) FILTER (WHERE ar.status = 'present') AS present,
                        COUNT(*) FILTER (WHERE ar.status = 'absent')  AS absent,
                        COUNT(*) FILTER (WHERE ar.status = 'late')    AS late,
                        COUNT(*) FILTER (WHERE ar.status = 'excused') AS excused,
                        COUNT(*) AS total
                    FROM attendance_records ar
                    JOIN students s ON ar.student_id = s.id
                    WHERE ar.teacher_id = $1 AND ar.class_id = $2 AND ar.subject_id = $3
                      AND ar.date BETWEEN $4 AND $5
                    GROUP BY ar.student_id, s.student_name, s.student_id
                    ORDER BY s.student_name
                    """,
                    uuid.UUID(teacher_id),
                    uuid.UUID(class_id),
                    uuid.UUID(subject_id),
                    s_date,
                    e_date,
                )
                result = []
                for row in rows:
                    d = dict(row)
                    d["student_id"] = str(d["student_id"])
                    tot = d["total"] or 1
                    d["attendance_pct"] = round((d["present"] + d["late"]) / tot * 100, 1)
                    result.append(d)
                return result
        except Exception as e:
            logger.error(f"Error getting students summary: {e}")
            return []

    # ==================== Notification Operations ====================

    VALID_NOTIF_TYPES = {
        'paper_assigned', 'grade_available', 'deadline_reminder',
        'document_processed', 'attendance_saved', 'student_enrolled',
        'assignment_published', 'assignment_graded', 'paper_published',
        'class_created', 'calendar_event', 'system',
    }

    async def create_notification(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a notification for a teacher. Silently drops invalid types."""
        try:
            notif_type = data.get("notification_type", "system")
            if notif_type not in self.VALID_NOTIF_TYPES:
                notif_type = "system"
            notif_id = data.get("id") or str(uuid.uuid4())
            async with self.connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO notifications
                        (id, user_id, title, message, notification_type, is_read, metadata)
                    VALUES ($1, $2, $3, $4, $5, FALSE, $6)
                    RETURNING *
                    """,
                    uuid.UUID(notif_id),
                    uuid.UUID(data["user_id"]),
                    data["title"],
                    data.get("message", ""),
                    notif_type,
                    json.dumps(data.get("metadata", {})),
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            return None

    async def get_notifications(
        self,
        user_id: str,
        only_unread: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List notifications for a teacher, newest first."""
        try:
            async with self.connection() as conn:
                where = "WHERE user_id = $1"
                params: list = [uuid.UUID(user_id)]
                if only_unread:
                    where += " AND is_read = FALSE"
                rows = await conn.fetch(
                    f"""
                    SELECT * FROM notifications
                    {where}
                    ORDER BY created_at DESC
                    LIMIT {limit} OFFSET {offset}
                    """,
                    *params,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching notifications for {user_id}: {e}")
            return []

    async def get_unread_count(self, user_id: str) -> int:
        """Return unread notification count for a teacher."""
        try:
            async with self.connection() as conn:
                val = await conn.fetchval(
                    "SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND is_read = FALSE",
                    uuid.UUID(user_id),
                )
                return int(val or 0)
        except Exception as e:
            logger.error(f"Error counting unread notifications: {e}")
            return 0

    async def mark_notification_read(self, notification_id: str, user_id: str) -> bool:
        """Mark a single notification as read (scoped to owner)."""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "UPDATE notifications SET is_read = TRUE WHERE id = $1 AND user_id = $2",
                    uuid.UUID(notification_id),
                    uuid.UUID(user_id),
                )
                return True
        except Exception as e:
            logger.error(f"Error marking notification {notification_id} read: {e}")
            return False

    async def mark_all_notifications_read(self, user_id: str) -> int:
        """Mark all unread notifications as read. Returns affected count."""
        try:
            async with self.connection() as conn:
                result = await conn.execute(
                    "UPDATE notifications SET is_read = TRUE WHERE user_id = $1 AND is_read = FALSE",
                    uuid.UUID(user_id),
                )
                # result is e.g. "UPDATE 5"
                try:
                    return int(result.split()[-1])
                except Exception:
                    return 0
        except Exception as e:
            logger.error(f"Error marking all notifications read for {user_id}: {e}")
            return 0

    async def delete_notification(self, notification_id: str, user_id: str) -> bool:
        """Delete a notification (scoped to owner)."""
        try:
            async with self.connection() as conn:
                await conn.execute(
                    "DELETE FROM notifications WHERE id = $1 AND user_id = $2",
                    uuid.UUID(notification_id),
                    uuid.UUID(user_id),
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting notification {notification_id}: {e}")
            return False

    async def delete_all_read_notifications(self, user_id: str) -> int:
        """Delete all read notifications for a teacher. Returns deleted count."""
        try:
            async with self.connection() as conn:
                result = await conn.execute(
                    "DELETE FROM notifications WHERE user_id = $1 AND is_read = TRUE",
                    uuid.UUID(user_id),
                )
                try:
                    return int(result.split()[-1])
                except Exception:
                    return 0
        except Exception as e:
            logger.error(f"Error clearing read notifications for {user_id}: {e}")
            return 0


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
