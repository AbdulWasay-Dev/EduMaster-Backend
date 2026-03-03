-- EduMaster Database Schema - FIXED VERSION
-- Supabase PostgreSQL with pgvector extension

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Teachers table (extends Supabase auth.users) - teachers and admins only
CREATE TABLE IF NOT EXISTS teachers (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
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
    student_id TEXT, -- School student ID
    email TEXT, -- Optional contact email
    phone TEXT, -- Optional contact phone
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
    color_code TEXT, -- For UI theming
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

-- Enhanced Document Chunks with hierarchical structure
CREATE TABLE IF NOT EXISTS doc_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    owner_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    parent_chunk_id BIGINT REFERENCES doc_chunks(id),
    chunk_type TEXT DEFAULT 'paragraph' CHECK (chunk_type IN ('section', 'paragraph', 'list', 'table')),
    text TEXT NOT NULL,
    metadata JSONB,
    embedding VECTOR(768),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Question Bank for reusable questions
CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    owner_id UUID REFERENCES teachers(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('mcq', 'true_false', 'short_answer', 'essay', 'fill_blank')),
    difficulty_level INTEGER CHECK (difficulty_level BETWEEN 1 AND 5),
    bloom_taxonomy TEXT CHECK (bloom_taxonomy IN ('remember', 'understand', 'apply', 'analyze', 'evaluate', 'create')),
    correct_answer JSONB NOT NULL,
    options JSONB,
    rubric JSONB,
    explanation TEXT,
    tags TEXT[],
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enhanced Papers with detailed configuration
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

-- Paper assignments to classes
CREATE TABLE IF NOT EXISTS paper_assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    assigned_by UUID REFERENCES teachers(id),
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    due_date TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE
);

-- Enhanced Student Submissions
CREATE TABLE IF NOT EXISTS submissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    student_id UUID REFERENCES students(id) ON DELETE CASCADE,
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    student_name TEXT NOT NULL,
    storage_path TEXT, -- For scanned answer sheets
    ocr_text TEXT,
    submission_data JSONB, -- Structured answers
    total_score DECIMAL(5,2),
    grade_percentage DECIMAL(5,2),
    feedback TEXT,
    grading_status TEXT DEFAULT 'pending' CHECK (grading_status IN ('pending', 'grading', 'completed')),
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    graded_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Detailed submission responses for each question
CREATE TABLE IF NOT EXISTS submission_responses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
    question_id UUID, -- References questions.id or paper questions
    question_text TEXT NOT NULL,
    student_answer TEXT,
    correct_answer TEXT,
    score DECIMAL(5,2),
    max_score DECIMAL(5,2),
    feedback TEXT,
    is_correct BOOLEAN,
    confidence_score DECIMAL(3,2), -- AI confidence in grading
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Analytics and performance tracking
CREATE TABLE IF NOT EXISTS performance_analytics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id UUID REFERENCES students(id) ON DELETE CASCADE,
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    metric_type TEXT NOT NULL, -- 'overall_score', 'question_difficulty', 'time_spent'
    metric_value DECIMAL(10,4),
    metadata JSONB,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
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
CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding ON doc_chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_subject ON doc_chunks(subject_id);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_owner ON doc_chunks(owner_id);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_document ON doc_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject_id);
CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(question_type);
CREATE INDEX IF NOT EXISTS idx_submissions_student ON submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_submissions_paper ON submissions(paper_id);
CREATE INDEX IF NOT EXISTS idx_submissions_class ON submissions(class_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, is_read) WHERE is_read = FALSE;

-- Function for vector similarity search
CREATE OR REPLACE FUNCTION search_similar_chunks(
    query_embedding VECTOR(768),
    subject_id UUID,
    match_threshold FLOAT DEFAULT 0.7,
    match_count INTEGER DEFAULT 5
)
RETURNS TABLE (
    id BIGINT,
    document_id UUID,
    text TEXT,
    similarity FLOAT
)
LANGUAGE SQL
AS $$
    SELECT 
        doc_chunks.id,
        doc_chunks.document_id,
        doc_chunks.text,
        1 - (doc_chunks.embedding <=> query_embedding) AS similarity
    FROM doc_chunks
    WHERE doc_chunks.subject_id = search_similar_chunks.subject_id
    AND 1 - (doc_chunks.embedding <=> query_embedding) > match_threshold
    ORDER BY doc_chunks.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- Row Level Security (RLS) policies
ALTER TABLE teachers ENABLE ROW LEVEL SECURITY;
ALTER TABLE classes ENABLE ROW LEVEL SECURITY;
ALTER TABLE subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE doc_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE papers ENABLE ROW LEVEL SECURITY;
ALTER TABLE submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

-- RLS Policies for teachers
CREATE POLICY "Teachers can view their own profile" ON teachers
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Teachers can update their own profile" ON teachers
    FOR UPDATE USING (auth.uid() = id);

-- RLS Policies for classes
CREATE POLICY "Teachers can manage their classes" ON classes
    FOR ALL USING (auth.uid() = teacher_id);

-- RLS Policies for subjects
CREATE POLICY "Teachers can manage their own subjects" ON subjects
    FOR ALL USING (auth.uid() = teacher_id);

-- RLS Policies for documents
CREATE POLICY "Teachers can manage their own documents" ON documents
    FOR ALL USING (auth.uid() = owner_id);

-- RLS Policies for doc_chunks
CREATE POLICY "Teachers can access chunks from their documents" ON doc_chunks
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM documents 
            WHERE documents.id = doc_chunks.document_id 
            AND documents.owner_id = auth.uid()
        )
    );

-- RLS Policies for papers
CREATE POLICY "Teachers can manage their own papers" ON papers
    FOR ALL USING (auth.uid() = owner_id);

-- RLS Policies for submissions
CREATE POLICY "Teachers can manage submissions for their papers" ON submissions
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM papers 
            WHERE papers.id = submissions.paper_id 
            AND papers.owner_id = auth.uid()
        )
    );

-- RLS Policies for notifications
CREATE POLICY "Teachers can manage their own notifications" ON notifications
    FOR ALL USING (auth.uid() = user_id);

-- Triggers for updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_teachers_updated_at BEFORE UPDATE ON teachers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_classes_updated_at BEFORE UPDATE ON classes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_subjects_updated_at BEFORE UPDATE ON subjects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_questions_updated_at BEFORE UPDATE ON questions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_papers_updated_at BEFORE UPDATE ON papers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
