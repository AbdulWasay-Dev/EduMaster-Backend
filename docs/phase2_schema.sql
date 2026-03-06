-- EduMaster Phase 2 — Schema Additions
-- Run these migrations on top of the existing schema

-- ================================================================
-- 1. Add class_code support to existing classes table
-- ================================================================
ALTER TABLE classes ADD COLUMN IF NOT EXISTS class_code TEXT UNIQUE;
ALTER TABLE classes ADD COLUMN IF NOT EXISTS max_students INTEGER DEFAULT 100;
ALTER TABLE classes ADD COLUMN IF NOT EXISTS allow_student_signup BOOLEAN DEFAULT TRUE;

-- ================================================================
-- 2. Add password_hash to teachers if not already present
-- ================================================================
ALTER TABLE teachers ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- ================================================================
-- 3. Student Accounts (students who can log in)
-- ================================================================
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

CREATE INDEX IF NOT EXISTS idx_student_accounts_class ON student_accounts(class_id);
CREATE INDEX IF NOT EXISTS idx_student_accounts_email ON student_accounts(email);

-- ================================================================
-- 4. Assignments
-- ================================================================
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

CREATE INDEX IF NOT EXISTS idx_assignments_teacher ON assignments(teacher_id);
CREATE INDEX IF NOT EXISTS idx_assignments_class ON assignments(class_id);
CREATE INDEX IF NOT EXISTS idx_assignments_subject ON assignments(subject_id);
CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status);

-- ================================================================
-- 5. Assignment Submissions
-- ================================================================
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

CREATE INDEX IF NOT EXISTS idx_asub_assignment ON assignment_submissions(assignment_id);
CREATE INDEX IF NOT EXISTS idx_asub_student ON assignment_submissions(student_account_id);
CREATE INDEX IF NOT EXISTS idx_asub_status ON assignment_submissions(status);

-- ================================================================
-- 6. Student Scores (unified ledger)
-- ================================================================
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

CREATE INDEX IF NOT EXISTS idx_scores_student ON student_scores(student_account_id);
CREATE INDEX IF NOT EXISTS idx_scores_class ON student_scores(class_id);

-- ================================================================
-- 7. Extend notifications table
-- ================================================================
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS student_account_id UUID REFERENCES student_accounts(id) ON DELETE CASCADE;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS audience TEXT DEFAULT 'teacher';

-- ================================================================
-- 8. Trigger for updated_at on new tables
-- ================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_student_accounts_updated_at ON student_accounts;
CREATE TRIGGER update_student_accounts_updated_at
    BEFORE UPDATE ON student_accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_assignments_updated_at ON assignments;
CREATE TRIGGER update_assignments_updated_at
    BEFORE UPDATE ON assignments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_assignment_submissions_updated_at ON assignment_submissions;
CREATE TRIGGER update_assignment_submissions_updated_at
    BEFORE UPDATE ON assignment_submissions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
