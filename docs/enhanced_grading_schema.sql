-- Enhanced Database Schema for Advanced Grading System
-- Additions to support Mistral OCR and multiple image processing

-- Add new columns to submissions table for enhanced grading
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS images_processed INTEGER DEFAULT 1;
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS ocr_confidence DECIMAL(3,2) DEFAULT 0.0;
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS grading_mode TEXT DEFAULT 'auto' CHECK (grading_mode IN ('auto', 'semi_auto', 'manual'));
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS strictness TEXT DEFAULT 'medium' CHECK (strictness IN ('lenient', 'medium', 'strict'));
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS processing_metadata JSONB;

-- Create table for storing individual image processing results
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

-- Create table for detailed grading results per question
CREATE TABLE IF NOT EXISTS question_grading_details (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL, -- Can be UUID or string identifier
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('mcq', 'true_false', 'short_answer', 'essay', 'fill_blank')),
    student_answer TEXT,
    correct_answer TEXT,
    score DECIMAL(5,2) NOT NULL DEFAULT 0,
    max_score DECIMAL(5,2) NOT NULL,
    feedback TEXT,
    ai_confidence DECIMAL(3,2), -- AI confidence in grading this specific question
    grading_method TEXT DEFAULT 'ai' CHECK (grading_method IN ('ai', 'manual', 'auto')),
    is_correct BOOLEAN,
    partial_credit DECIMAL(3,2) DEFAULT 0, -- For partial credit scenarios
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create table for OCR processing logs
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

-- Create table for grading audit trail
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

-- Create table for batch grading operations
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
    grading_settings JSONB, -- Store grading mode, strictness, etc.
    error_log TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_submission_images_submission ON submission_images(submission_id);
CREATE INDEX IF NOT EXISTS idx_submission_images_index ON submission_images(submission_id, image_index);
CREATE INDEX IF NOT EXISTS idx_question_grading_submission ON question_grading_details(submission_id);
CREATE INDEX IF NOT EXISTS idx_question_grading_question ON question_grading_details(question_id);
CREATE INDEX IF NOT EXISTS idx_ocr_logs_submission ON ocr_processing_logs(submission_id);
CREATE INDEX IF NOT EXISTS idx_ocr_logs_image ON ocr_processing_logs(image_id);
CREATE INDEX IF NOT EXISTS idx_grading_audit_submission ON grading_audit_log(submission_id);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_teacher ON batch_grading_jobs(teacher_id);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_paper ON batch_grading_jobs(paper_id);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_grading_jobs(status);

-- Add RLS policies for new tables
ALTER TABLE submission_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE question_grading_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE ocr_processing_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE grading_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE batch_grading_jobs ENABLE ROW LEVEL SECURITY;

-- RLS Policies for submission_images
CREATE POLICY "Teachers can access images from their submissions" ON submission_images
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM submissions 
            JOIN papers ON papers.id = submissions.paper_id
            WHERE submissions.id = submission_images.submission_id 
            AND papers.owner_id = auth.uid()
        )
    );

-- RLS Policies for question_grading_details
CREATE POLICY "Teachers can access grading details from their submissions" ON question_grading_details
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM submissions 
            JOIN papers ON papers.id = submissions.paper_id
            WHERE submissions.id = question_grading_details.submission_id 
            AND papers.owner_id = auth.uid()
        )
    );

-- RLS Policies for ocr_processing_logs
CREATE POLICY "Teachers can access OCR logs from their submissions" ON ocr_processing_logs
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM submissions 
            JOIN papers ON papers.id = submissions.paper_id
            WHERE submissions.id = ocr_processing_logs.submission_id 
            AND papers.owner_id = auth.uid()
        )
    );

-- RLS Policies for grading_audit_log
CREATE POLICY "Teachers can access audit logs from their submissions" ON grading_audit_log
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM submissions 
            JOIN papers ON papers.id = submissions.paper_id
            WHERE submissions.id = grading_audit_log.submission_id 
            AND papers.owner_id = auth.uid()
        )
    );

-- RLS Policies for batch_grading_jobs
CREATE POLICY "Teachers can manage their own batch grading jobs" ON batch_grading_jobs
    FOR ALL USING (auth.uid() = teacher_id);

-- Function to calculate overall submission statistics
CREATE OR REPLACE FUNCTION get_submission_statistics(submission_uuid UUID)
RETURNS TABLE (
    total_questions INTEGER,
    answered_questions INTEGER,
    correct_answers INTEGER,
    total_score DECIMAL(5,2),
    max_possible_score DECIMAL(5,2),
    percentage DECIMAL(5,2),
    average_confidence DECIMAL(3,2)
)
LANGUAGE SQL
AS $$
    SELECT 
        COUNT(*)::INTEGER as total_questions,
        COUNT(CASE WHEN student_answer IS NOT NULL AND student_answer != '' THEN 1 END)::INTEGER as answered_questions,
        COUNT(CASE WHEN is_correct = true THEN 1 END)::INTEGER as correct_answers,
        COALESCE(SUM(score), 0) as total_score,
        COALESCE(SUM(max_score), 0) as max_possible_score,
        CASE 
            WHEN COALESCE(SUM(max_score), 0) > 0 
            THEN (COALESCE(SUM(score), 0) / SUM(max_score)) * 100 
            ELSE 0 
        END as percentage,
        COALESCE(AVG(ai_confidence), 0) as average_confidence
    FROM question_grading_details 
    WHERE submission_id = submission_uuid;
$$;

-- Function to get class grading summary
CREATE OR REPLACE FUNCTION get_class_grading_summary(class_uuid UUID, paper_uuid UUID)
RETURNS TABLE (
    total_students INTEGER,
    submitted_students INTEGER,
    graded_students INTEGER,
    average_score DECIMAL(5,2),
    average_percentage DECIMAL(5,2),
    highest_score DECIMAL(5,2),
    lowest_score DECIMAL(5,2)
)
LANGUAGE SQL
AS $$
    SELECT 
        COUNT(DISTINCT s.student_id)::INTEGER as total_students,
        COUNT(DISTINCT CASE WHEN s.submitted_at IS NOT NULL THEN s.student_id END)::INTEGER as submitted_students,
        COUNT(DISTINCT CASE WHEN s.grading_status = 'completed' THEN s.student_id END)::INTEGER as graded_students,
        COALESCE(AVG(s.total_score), 0) as average_score,
        COALESCE(AVG(s.grade_percentage), 0) as average_percentage,
        COALESCE(MAX(s.total_score), 0) as highest_score,
        COALESCE(MIN(s.total_score), 0) as lowest_score
    FROM submissions s
    WHERE s.class_id = class_uuid AND s.paper_id = paper_uuid;
$$;

-- Trigger to update submission statistics when grading details change
CREATE OR REPLACE FUNCTION update_submission_from_grading_details()
RETURNS TRIGGER AS $$
DECLARE
    submission_stats RECORD;
BEGIN
    -- Get updated statistics
    SELECT * INTO submission_stats 
    FROM get_submission_statistics(NEW.submission_id);
    
    -- Update the submission record
    UPDATE submissions 
    SET 
        total_score = submission_stats.total_score,
        grade_percentage = submission_stats.percentage,
        updated_at = NOW()
    WHERE id = NEW.submission_id;
    
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_submission_stats_trigger
    AFTER INSERT OR UPDATE OR DELETE ON question_grading_details
    FOR EACH ROW EXECUTE FUNCTION update_submission_from_grading_details();

-- View for comprehensive submission details
CREATE OR REPLACE VIEW submission_details_view AS
SELECT 
    s.id as submission_id,
    s.paper_id,
    s.student_id,
    s.student_name,
    s.class_id,
    s.total_score,
    s.grade_percentage,
    s.feedback,
    s.grading_status,
    s.images_processed,
    s.ocr_confidence,
    s.grading_mode,
    s.strictness,
    s.submitted_at,
    s.graded_at,
    p.title as paper_title,
    p.total_marks as paper_total_marks,
    c.name as class_name,
    sub.name as subject_name,
    t.name as teacher_name,
    -- Statistics
    (SELECT COUNT(*) FROM question_grading_details qgd WHERE qgd.submission_id = s.id) as total_questions,
    (SELECT COUNT(*) FROM question_grading_details qgd WHERE qgd.submission_id = s.id AND qgd.student_answer IS NOT NULL AND qgd.student_answer != '') as answered_questions,
    (SELECT COUNT(*) FROM question_grading_details qgd WHERE qgd.submission_id = s.id AND qgd.is_correct = true) as correct_answers,
    (SELECT AVG(qgd.ai_confidence) FROM question_grading_details qgd WHERE qgd.submission_id = s.id) as average_ai_confidence
FROM submissions s
JOIN papers p ON p.id = s.paper_id
JOIN classes c ON c.id = s.class_id
JOIN subjects sub ON sub.id = p.subject_id
JOIN teachers t ON t.id = p.owner_id;
