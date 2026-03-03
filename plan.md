📌 Enhanced Backend Plan (FastAPI + Supabase + Google GenAI) - Teacher-Focused Educational RAG System
1. Tech Stack

Framework: FastAPI (async, auto OpenAPI docs)

Database + Vector Store: Supabase Postgres with pgvector extension

Storage: Supabase Storage buckets (PDFs, PPTX, Word docs, answer sheets, images)

Auth: Supabase Auth (JWT-based teacher management - teachers and admins only)

Embeddings: Google Generative AI Embeddings (text-embedding-004)

LLM: Google Gemini Chat Model (gemini-1.5-pro or gemini-1.5-flash)

LangChain: Advanced RAG pipeline with hybrid retrieval

OCR: Tesseract OCR (free) + Google Vision API (for higher accuracy)

Additional Services:
- Redis (caching layer for embeddings and frequent queries)
- Celery (background task processing for document processing)
- WebSocket support (real-time notifications)

Deployment:
- Backend: Render / Railway / Fly.io (free tiers)
- Supabase: free managed hosting
- Google GenAI: free API credits available
- Redis: Upstash (free tier)

2. Enhanced File Structure
backend/
│── main.py                 # FastAPI entry point with WebSocket support
│── config.py               # Env vars, API keys, Redis config
│── requirements.txt
│── celery_app.py           # Celery configuration for background tasks
│
├── routers/                # API endpoints
│   ├── auth.py             # Supabase auth wrapper with role management
│   ├── subjects.py         # Create/list subjects
│   ├── documents.py        # Upload/list documents with multi-format support
│   ├── rag.py              # Enhanced query + Paper generation
│   ├── grading.py          # Advanced OCR + answer checking
│   ├── classes.py          # Class/group management
│   ├── students.py         # Student enrollment and management
│   ├── analytics.py        # Performance analytics and insights
│   ├── notifications.py    # Real-time notifications
│
├── services/               # Business logic
│   ├── supabase_client.py  # Supabase SDK wrapper
│   ├── redis_client.py     # Redis caching service
│   ├── embedding_service.py# Google embeddings with caching
│   ├── llm_service.py      # Google LLM with advanced prompting
│   ├── text_extractor.py   # Multi-format parsing (PDF/PPT/Word/Images)
│   ├── chunker.py          # Semantic and hierarchical chunking
│   ├── retriever.py        # Hybrid search (semantic + keyword)
│   ├── rag_pipeline.py     # Advanced LangChain pipeline
│   ├── ocr_service.py      # Enhanced OCR with preprocessing
│   ├── grading_service.py  # Intelligent LLM-based grading
│   ├── question_generator.py # Advanced question generation
│   ├── analytics_service.py # Performance analytics
│   ├── notification_service.py # Real-time notifications
│
├── tasks/                  # Celery background tasks
│   ├── document_processing.py # Async document processing
│   ├── embedding_generation.py # Async embedding creation
│   ├── grading_tasks.py    # Async grading processing
│
├── utils/
│   ├── prompts.py          # Advanced prompt templates
│   ├── security.py         # JWT validation and role checking
│   ├── file_validators.py  # File type and security validation
│   ├── text_processing.py  # Text cleaning and preprocessing
│
└── schemas/                # Pydantic models
    ├── auth.py
    ├── subjects.py
    ├── documents.py
    ├── rag.py
    ├── grading.py
    ├── classes.py
    ├── students.py
    ├── analytics.py
    ├── notifications.py

3. Enhanced Database Schema (Supabase + pgvector)
create extension if not exists vector;

-- Teachers (via Supabase Auth) - teachers and admins only
create table teachers (
  id uuid primary key references auth.users(id),
  name text not null,
  email text unique not null,
  role text not null default 'teacher', -- 'teacher', 'admin'
  profile_image_url text,
  school_name text,
  department text,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- Classes/Groups for organizing students (managed by teachers)
create table classes (
  id uuid primary key default gen_random_uuid(),
  teacher_id uuid references teachers(id) on delete cascade,
  name text not null,
  description text,
  grade_level text,
  subject_area text,
  academic_year text,
  is_active boolean default true,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- Students (managed by teachers, no direct login)
create table students (
  id uuid primary key default gen_random_uuid(),
  class_id uuid references classes(id) on delete cascade,
  student_name text not null,
  student_id text, -- School student ID
  email text, -- Optional contact email
  phone text, -- Optional contact phone
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- Subjects (managed by teachers)
create table subjects (
  id uuid primary key default gen_random_uuid(),
  teacher_id uuid references teachers(id) on delete cascade,
  class_id uuid references classes(id) on delete cascade,
  name text not null,
  description text,
  color_code text, -- For UI theming
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- Documents (enhanced with metadata)
create table documents (
  id uuid primary key default gen_random_uuid(),
  subject_id uuid references subjects(id) on delete cascade,
  owner_id uuid references app_users(id) on delete cascade,
  filename text not null,
  original_filename text not null,
  storage_path text not null,
  file_type text not null, -- 'pdf', 'pptx', 'docx', 'image'
  file_size bigint,
  page_count int,
  processing_status text default 'pending', -- 'pending', 'processing', 'completed', 'failed'
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- Enhanced Document Chunks with hierarchical structure
create table doc_chunks (
  id bigserial primary key,
  document_id uuid references documents(id) on delete cascade,
  subject_id uuid references subjects(id) on delete cascade,
  owner_id uuid references app_users(id) on delete cascade,
  chunk_index int not null,
  parent_chunk_id bigint references doc_chunks(id), -- For hierarchical chunks
  chunk_type text default 'paragraph', -- 'section', 'paragraph', 'list', 'table'
  text text not null,
  metadata jsonb, -- Page numbers, headers, etc.
  embedding vector(768),
  created_at timestamp default now()
);

-- Question Bank for reusable questions
create table questions (
  id uuid primary key default gen_random_uuid(),
  subject_id uuid references subjects(id) on delete cascade,
  owner_id uuid references app_users(id) on delete cascade,
  question_text text not null,
  question_type text not null, -- 'mcq', 'true_false', 'short_answer', 'essay', 'fill_blank'
  difficulty_level int check (difficulty_level between 1 and 5),
  bloom_taxonomy text, -- 'remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'
  correct_answer jsonb not null,
  options jsonb, -- For MCQ options
  rubric jsonb, -- For essay questions
  explanation text,
  tags text[],
  is_active boolean default true,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- Enhanced Papers with detailed configuration
create table papers (
  id uuid primary key default gen_random_uuid(),
  subject_id uuid references subjects(id) on delete cascade,
  class_id uuid references classes(id),
  owner_id uuid references app_users(id),
  title text not null,
  description text,
  questions jsonb not null, -- Structured question data
  configuration jsonb, -- Time limit, difficulty distribution, etc.
  answer_key jsonb not null,
  total_marks decimal(5,2),
  is_published boolean default false,
  published_at timestamp,
  due_date timestamp,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- Paper assignments to classes
create table paper_assignments (
  id uuid primary key default gen_random_uuid(),
  paper_id uuid references papers(id) on delete cascade,
  class_id uuid references classes(id) on delete cascade,
  assigned_by uuid references app_users(id),
  assigned_at timestamp default now(),
  due_date timestamp,
  is_active boolean default true
);

-- Enhanced Student Submissions
create table submissions (
  id uuid primary key default gen_random_uuid(),
  paper_id uuid references papers(id) on delete cascade,
  student_id uuid references app_users(id) on delete cascade,
  class_id uuid references classes(id) on delete cascade,
  student_name text not null,
  storage_path text, -- For scanned answer sheets
  ocr_text text,
  submission_data jsonb, -- Structured answers
  total_score decimal(5,2),
  grade_percentage decimal(5,2),
  feedback text,
  grading_status text default 'pending', -- 'pending', 'grading', 'completed'
  submitted_at timestamp default now(),
  graded_at timestamp,
  created_at timestamp default now()
);

-- Detailed submission responses for each question
create table submission_responses (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid references submissions(id) on delete cascade,
  question_id uuid, -- References questions.id or paper questions
  question_text text not null,
  student_answer text,
  correct_answer text,
  score decimal(5,2),
  max_score decimal(5,2),
  feedback text,
  is_correct boolean,
  confidence_score decimal(3,2), -- AI confidence in grading
  created_at timestamp default now()
);

-- Analytics and performance tracking
create table performance_analytics (
  id uuid primary key default gen_random_uuid(),
  student_id uuid references app_users(id) on delete cascade,
  class_id uuid references classes(id) on delete cascade,
  subject_id uuid references subjects(id) on delete cascade,
  paper_id uuid references papers(id) on delete cascade,
  metric_type text not null, -- 'overall_score', 'question_difficulty', 'time_spent'
  metric_value decimal(10,4),
  metadata jsonb,
  recorded_at timestamp default now()
);

-- Notifications system
create table notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references app_users(id) on delete cascade,
  title text not null,
  message text not null,
  notification_type text not null, -- 'paper_assigned', 'grade_available', 'deadline_reminder'
  is_read boolean default false,
  metadata jsonb,
  created_at timestamp default now()
);

-- Indexes for performance
create index idx_doc_chunks_embedding on doc_chunks using ivfflat (embedding vector_cosine_ops);
create index idx_doc_chunks_subject on doc_chunks(subject_id);
create index idx_doc_chunks_owner on doc_chunks(owner_id);
create index idx_questions_subject on questions(subject_id);
create index idx_questions_type on questions(question_type);
create index idx_submissions_student on submissions(student_id);
create index idx_submissions_paper on submissions(paper_id);
create index idx_enrollments_class on enrollments(class_id);
create index idx_enrollments_student on enrollments(student_id);

4. Enhanced API Endpoints

## Authentication & User Management
- POST /auth/signup → Supabase handled
- POST /auth/login → Supabase handled
- GET /auth/profile → Get user profile with role
- PUT /auth/profile → Update user profile
- POST /auth/refresh → Refresh JWT token

## Class Management
- POST /classes/ → Create new class
- GET /classes/ → List teacher's classes
- GET /classes/{id} → Get class details with students
- PUT /classes/{id} → Update class information
- DELETE /classes/{id} → Delete class
- POST /classes/{id}/enroll → Enroll student with class code
- GET /classes/{id}/students → List enrolled students
- DELETE /classes/{id}/students/{student_id} → Remove student

## Subject Management
- POST /subjects/ → Create new subject
- GET /subjects/ → List user subjects (with class filtering)
- GET /subjects/{id} → Get subject details
- PUT /subjects/{id} → Update subject
- DELETE /subjects/{id} → Delete subject

## Document Management
- POST /documents/upload → Upload multi-format documents
- GET /documents?subject_id= → List documents under subject
- GET /documents/{id} → Get document details
- DELETE /documents/{id} → Delete document
- GET /documents/{id}/status → Check processing status
- POST /documents/{id}/reprocess → Reprocess document

## Enhanced RAG System
- POST /rag/query → Advanced query with context
```json
{
  "subject_id": "uuid",
  "document_ids": ["uuid1", "uuid2"],
  "question": "Explain photosynthesis",
  "question_type": "explanation",
  "difficulty": "intermediate",
  "include_sources": true
}
```
- POST /rag/query-batch → Multiple questions at once
- GET /rag/suggestions/{subject_id} → Get question suggestions
- POST /rag/summarize → Summarize document content

## Paper Generation & Management
- POST /papers/generate → Generate paper with advanced config
```json
{
  "subject_id": "uuid",
  "class_id": "uuid",
  "title": "Mid-term Exam",
  "config": {
    "mcq_count": 10,
    "short_answer_count": 5,
    "essay_count": 2,
    "difficulty_distribution": {"easy": 30, "medium": 50, "hard": 20},
    "time_limit": 120,
    "total_marks": 100
  }
}
```
- POST /papers/create-from-sheet → Create paper from uploaded question sheet
- GET /papers/{id}/preview → Preview generated paper
- POST /papers/{id}/publish → Publish paper to class
- GET /papers?class_id= → List papers for class
- PUT /papers/{id} → Edit paper questions
- DELETE /papers/{id} → Delete paper
- GET /papers/{id}/statistics → Get paper performance statistics

## Question Bank Management
- POST /questions/ → Create question in bank
- GET /questions?subject_id= → List questions by subject
- GET /questions/{id} → Get question details
- PUT /questions/{id} → Update question
- DELETE /questions/{id} → Delete question
- POST /questions/import → Import questions from paper

## Answer Sheet Grading System
- POST /grading/upload-answer-sheet → Upload photo of handwritten answer sheet
- POST /grading/process-sheet → Process uploaded answer sheet with OCR
- POST /grading/grade-submission → Grade student submission
```json
{
  "paper_id": "uuid",
  "student_id": "uuid",
  "answer_sheet_image": "base64_image_data",
  "grading_mode": "auto", // "auto", "semi_auto", "manual"
  "strictness": "medium" // "lenient", "medium", "strict"
}
```
- GET /grading/{submission_id}/result → Get detailed grading result
- POST /grading/{submission_id}/regrade → Regrade submission
- GET /grading/queue → Get pending grading tasks
- GET /grading/class/{class_id}/results → Get all grading results for class

## Teacher Analytics & Insights
- GET /analytics/class/{class_id}/overview → Class performance overview with student statistics
- GET /analytics/student/{student_id}/progress → Individual student progress and performance trends
- GET /analytics/paper/{paper_id}/analysis → Paper difficulty analysis and question performance
- GET /analytics/subject/{subject_id}/trends → Subject performance trends across classes
- GET /analytics/questions/{question_id}/stats → Question statistics and common mistakes
- GET /analytics/teacher/dashboard → Teacher dashboard with all class statistics
- GET /analytics/class/{class_id}/grade-distribution → Grade distribution and performance metrics
- POST /analytics/reports/generate → Generate custom reports for classes/students
- GET /analytics/student/{student_id}/comparison → Compare student performance with class average

## Notifications
- GET /notifications/ → List user notifications
- PUT /notifications/{id}/read → Mark notification as read
- PUT /notifications/read-all → Mark all as read
- GET /notifications/unread-count → Get unread count
- WebSocket /ws/notifications → Real-time notifications

## Real-time Features
- WebSocket /ws/class/{class_id} → Class updates
- WebSocket /ws/grading/{submission_id} → Grading progress
- WebSocket /ws/paper/{paper_id} → Paper updates

5. Enhanced Service Logic & Workflows

## Document Processing Flow
1. Teacher uploads document → Supabase Storage
2. Background task (Celery) processes document:
   - Extract text with layout preservation
   - Perform semantic chunking with hierarchical structure
   - Generate embeddings with Google AI
   - Store in pgvector with metadata
   - Update processing status
3. Cache frequently accessed embeddings in Redis
4. Send notification when processing complete

## Advanced RAG Query Flow
1. User submits query with context (subject, difficulty, type)
2. Embed query using Google Embeddings
3. Perform hybrid search:
   - Semantic similarity search in pgvector
   - Keyword search for exact matches
   - Re-rank results using cross-encoder
4. Retrieve top-k relevant chunks with metadata
5. Pass context to LangChain pipeline with Google LLM
6. Generate answer with source citations
7. Cache result in Redis for similar queries

## Intelligent Paper Generation Flow
1. Teacher selects subject, documents, and configuration
2. System analyzes document content for question potential
3. Generate questions using advanced prompting:
   - Bloom's taxonomy alignment
   - Difficulty distribution
   - Question type variety
4. Create answer key with multiple acceptable answers
5. Generate rubrics for essay questions
6. Save structured paper with metadata
7. Preview available before publishing

## Advanced Grading Pipeline
1. Upload answer sheet (scanned or digital)
2. Preprocess image (denoise, deskew, enhance)
3. OCR with confidence scoring
4. Parse answers by question
5. Grade each answer:
   - Exact match for MCQs
   - Semantic similarity for open-ended
   - Rubric-based scoring for essays
6. Generate detailed feedback
7. Calculate confidence scores
8. Store results with analytics data

## Real-time Collaboration Flow
1. WebSocket connections for live updates
2. Notify students of new papers/assignments
3. Real-time grading progress updates
4. Live class activity feeds
5. Instant notification delivery

## Analytics & Insights Generation
1. Collect performance metrics continuously
2. Aggregate data by student, class, subject
3. Generate insights using LLM analysis
4. Create visualizations and reports
5. Identify learning patterns and gaps
6. Suggest improvements for teaching

6. Enhanced Security & Performance

## Authentication & Authorization
- Supabase Auth JWT with role-based access control
- FastAPI middleware for token validation and role checking
- Row-level security (RLS) policies in Supabase
- API key management for external services
- Session management with refresh tokens

## Data Protection
- Encrypted file storage in Supabase
- Secure file upload validation (type, size, content scanning)
- Input sanitization and SQL injection prevention
- Rate limiting per user and endpoint
- CORS restricted to Flutter frontend domains

## Performance Optimization
- Redis caching for embeddings and frequent queries
- Database connection pooling
- Background task processing with Celery
- CDN for static assets
- Query optimization with proper indexing

## Monitoring & Logging
- Structured logging with correlation IDs
- Performance metrics and monitoring
- Error tracking and alerting
- API usage analytics
- Security event logging

7. Deployment Architecture

## Production Stack
- **Backend**: FastAPI on Railway/Render with auto-scaling
- **Database**: Supabase Postgres with pgvector
- **Storage**: Supabase Storage with CDN
- **Cache**: Redis (Upstash) for session and data caching
- **Queue**: Celery with Redis broker for background tasks
- **Monitoring**: Sentry for error tracking, Prometheus for metrics
- **CDN**: CloudFlare for global content delivery

## Environment Configuration
- Development: Local Docker setup
- Staging: Railway preview deployments
- Production: Railway with custom domain
- Environment variables for all secrets
- Automated database migrations

8. Implementation Roadmap

## Phase 1: Core RAG System (Weeks 1-3)
- ✅ Basic FastAPI setup with Supabase integration
- ✅ Document upload and text extraction
- ✅ Embedding generation and storage
- ✅ Basic RAG query endpoint
- ✅ Simple question generation

## Phase 2: Advanced Features (Weeks 4-6)
- ✅ Class management and student enrollment
- ✅ Enhanced paper generation with difficulty levels
- ✅ Advanced grading system with OCR
- ✅ Question bank management
- ✅ Basic analytics dashboard

## Phase 3: Real-time & Collaboration (Weeks 7-8)
- ✅ WebSocket implementation for real-time updates
- ✅ Notification system
- ✅ Live grading progress
- ✅ Class activity feeds

## Phase 4: Analytics & Insights (Weeks 9-10)
- ✅ Advanced analytics and reporting
- ✅ Performance insights and recommendations
- ✅ Custom report generation
- ✅ Learning outcome tracking

## Phase 5: Optimization & Scaling (Weeks 11-12)
- ✅ Performance optimization
- ✅ Caching implementation
- ✅ Background task processing
- ✅ Production deployment and monitoring

9. Key Features Summary

## For Teachers
- 📚 Multi-format document upload and processing
- 🤖 AI-powered question generation with difficulty control
- 📝 Intelligent answer sheet grading via photo upload and OCR
- 📊 Comprehensive student and class analytics
- 👥 Class and student management (no student login required)
- 📋 Custom paper creation from uploaded question sheets
- 📈 Student performance tracking and comparison
- 🔍 AI-powered study assistance and content analysis
- 📋 Digital and printable papers
- 💬 Real-time notifications and updates
- 📊 Grade distribution and performance metrics
- 🎯 Question difficulty analysis and optimization

## Technical Excellence
- 🚀 Scalable microservices architecture
- 🔒 Enterprise-grade security
- ⚡ High-performance RAG system
- 🔄 Real-time collaboration features
- 📊 Advanced analytics and AI insights
- 🌐 Cloud-native deployment

✅ **This enhanced plan provides a comprehensive, production-ready educational platform that goes far beyond basic RAG functionality to deliver a complete learning management system with AI-powered features.**

**Ready to start implementation? I can generate the starter FastAPI code with the enhanced RAG pipeline and database setup.**