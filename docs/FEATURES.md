## EduMaster Backend — Feature Overview

### 1) What This Service Does
EduMaster is a FastAPI backend for an educational platform that helps teachers manage content, generate questions with AI, grade answer sheets, and analyze performance. It integrates OCR, RAG (Retrieval-Augmented Generation), and Supabase (Postgres + Storage + Auth).

### 2) Core Features
- **Authentication and Profiles**
  - JWT-based auth integrated with Supabase
  - Profile read/update endpoints for authenticated users

- **Subjects Management**
  - Create and list subjects per teacher
  - Subject metadata (name, description, grade level, subject area, academic year, status)

- **Documents and Content Pipeline**
  - Upload source files (PDF, DOCX, PPTX, images) to Supabase Storage
  - Text extraction via `PyPDF2`, OCR via Tesseract (`pytesseract` + OpenCV)
  - Chunking of extracted text for retrieval with embedding support

- **RAG (Retrieval-Augmented Generation)**
  - Hybrid retrieval using embeddings and metadata filters
  - Query documents with Google Generative AI (Gemini) to produce answers/summaries
  - Generate question suggestions based on subject content

- **AI Question Generation**
  - Produce questions of varying difficulty from uploaded documents
  - Structured output suitable for downstream use in papers/quizzes

- **Papers and Exam Assembly**
  - Create papers with sections and questions
  - Store and fetch papers per teacher

- **OCR Grading (Answer Sheet Evaluation)**
  - OCR entire answer sheets (images/PDF scans)
  - Heuristics and OpenCV pre-processing for better OCR accuracy
  - LLM-assisted grading to produce:
    - Per-question or holistic scoring
    - Overall feedback and confidence
    - Total marks and percentage

- **Students and Classes**
  - Create classes and list classes for a teacher
  - Manage students per class (CRUD)

- **Analytics**
  - Aggregate endpoints to power dashboards (progress, performance, usage)

- **Notifications (placeholder)**
  - Endpoints scaffolded for future real-time or queued notifications

### 3) APIs and Routes (by module)
- `GET /health` — health probe
- `GET /` — root metadata
- `GET /docs` — interactive Swagger UI (in debug)

API v1 prefix: `settings.api_v1_prefix` (default `/api/v1`)

- `auth` (Authentication)
  - `POST /api/v1/auth/profile` — get user profile
  - `PUT /api/v1/auth/profile` — update user profile

- `subjects`
  - `POST /api/v1/subjects/` — create subject
  - `GET /api/v1/subjects/` — list subjects

- `documents`
  - `POST /api/v1/documents/upload` — upload a document
  - `GET /api/v1/documents/` — list documents for a subject
  - `GET /api/v1/documents/{id}` — get document details

- `rag`
  - `POST /api/v1/rag/query` — retrieve-then-generate answers from your content
  - `POST /api/v1/rag/generate-questions` — AI question generation
  - `GET /api/v1/rag/suggestions/{subject_id}` — question suggestions

- `grading`
  - `POST /api/v1/grading/upload` — upload answer sheet images
  - `POST /api/v1/grading/check` — grade a submission (OCR + LLM)

- `classes`
  - `POST /api/v1/classes/` — create class
  - `GET /api/v1/classes/` — list classes

- `students`
  - `POST /api/v1/students/` — create student
  - `GET /api/v1/students/?class_id=...` — list students in a class

- `papers`
  - `POST /api/v1/papers/` — create paper
  - `GET /api/v1/papers/` — list papers for a teacher
  - `GET /api/v1/papers/{id}` — get paper

- `analytics` and `notifications`
  - Basic stubs for analytics and notifications endpoints

### 4) Architecture
- **Framework**: FastAPI with Uvicorn
- **Database/Storage**: Supabase (Postgres + Storage)
- **AI**: Google Generative AI (Gemini) for RAG, grading, and question generation
- **OCR**: Tesseract via `pytesseract` and `opencv-python`
- **Embeddings**: Google models for vectorization (via `embedding_service`)
- **Chunking**: Text splitter utilities to support retrieval
- **Security**: JWT verification and role checks in `utils/security.py`
- **Settings**: Pydantic Settings via `.env` (see `config.py`)
- **Static Files**: Served from `/static` if folder exists

### 5) Security Model
- JWT-based auth (tokens verified with `python-jose`)
- Role-based guards for teacher/admin actions
- Server-side Supabase service role key used where RLS-safe server operations are needed
- CORS configurable via `CORS_ORIGINS` env (allow `[*]` for dev; restrict in production)

### 6) Operations and Deployment
- Run locally: `uvicorn main:app --reload --host 0.0.0.0 --port 8010`
- Production (example): systemd service executing uvicorn, and Nginx reverse proxy on port 80
- Auto-deploy: webhook triggers `deploy.sh` (pull latest, install, restart service)
- Health checks:
  - `GET /health` — JSON with status/metadata

### 7) Required Services and Dependencies
- Supabase project (Postgres + Storage + Auth)
- Google API key for Generative AI
- System packages on Ubuntu:
  - `tesseract-ocr`, `tesseract-ocr-eng`, `libtesseract-dev`
  - `libgl1-mesa-glx`, `libglib2.0-0` (OpenCV runtime)

### 8) Environment Variables (minimum)
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `GOOGLE_API_KEY`
- `SECRET_KEY`
- `CORS_ORIGINS` (e.g., `["*"]` for dev; set explicit origins for prod)
- Optional: `ENVIRONMENT` (`development`/`production`), `DEBUG`

### 9) Data Flow (High Level)
1. Teacher uploads materials → text extracted (PDF/OCR), chunked, embedded → stored
2. Students submit scans → OCR → LLM-assessed scoring and feedback → recorded
3. RAG queries retrieve relevant chunks → prompt LLM → answer with citations/context
4. Analytics endpoints aggregate progress and outcomes for dashboards

### 10) Limits & Considerations
- OCR quality depends on scan quality; pre-processing improves accuracy
- LLM costs/latency tied to content length; chunk wisely and cache when possible
- Secure `.env` and never commit secrets
- In production, set strict CORS and `TrustedHostMiddleware`

### 11) Quick Smoke Tests
- `GET /health` → should return status `healthy`
- `GET /docs` (in debug mode) → interactive API
- Upload a small PDF and verify it appears in documents list
- Run a RAG query on a subject containing uploaded content

### 12) Useful Paths in the Codebase
- App entrypoint: `main.py`
- Settings: `config.py`
- Security: `utils/security.py`
- Logging: `utils/logging_config.py`
- Routers: `routers/` (auth, subjects, documents, rag, grading, classes, students, analytics, notifications, papers)
- Services: `services/` (supabase_client, llm_service, ocr_service, text_extractor, embedding_service, chunker)

---
For a quick start and deployment commands, also see the project `README.md` and your server management notes.


