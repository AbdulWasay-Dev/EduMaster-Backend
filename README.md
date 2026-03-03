# EduMaster Backend

Educational RAG System with AI-powered question generation and grading.

## 🚀 Features

- **Advanced RAG System**: Hybrid search with semantic and keyword matching
- **AI Question Generation**: Create questions from documents with difficulty levels
- **Intelligent Grading**: OCR-based answer sheet grading with AI feedback
- **Class Management**: Organize students and manage assignments
- **Real-time Features**: WebSocket support for live updates
- **Analytics Dashboard**: Performance insights and learning analytics

## 🛠 Tech Stack

- **Framework**: FastAPI (Python)
- **Database**: Supabase PostgreSQL with pgvector
- **AI/ML**: Google Generative AI (Gemini)
- **Caching**: Redis
- **Background Tasks**: Celery
- **Storage**: Supabase Storage
- **Authentication**: Supabase Auth

## 📋 Prerequisites

- Python 3.9+
- Redis server
- Supabase account
- Google AI API key

## 🚀 Quick Start

### 1. Clone and Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment Configuration

```bash
cp env.example .env
# Edit .env with your actual values
```

Required environment variables:
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_ANON_KEY`: Your Supabase anon key
- `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase service role key
- `GOOGLE_API_KEY`: Your Google AI API key
- `SECRET_KEY`: A secure secret key for JWT

### 3. Database Setup

1. Create a new Supabase project
2. Run the SQL schema from `docs/database_schema.sql`
3. Enable pgvector extension in your Supabase project

### 4. Run the Application

```bash
# Development
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 5. Access the API

- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## 📁 Project Structure

```
backend/
├── main.py                 # FastAPI application entry point
├── config.py               # Configuration settings
├── requirements.txt        # Python dependencies
├── routers/                # API route handlers
│   ├── auth.py            # Authentication endpoints
│   ├── subjects.py        # Subject management
│   ├── documents.py       # Document upload/management
│   ├── rag.py             # RAG query endpoints
│   ├── grading.py         # Grading system
│   ├── classes.py         # Class management
│   ├── students.py        # Student management
│   ├── analytics.py       # Analytics endpoints
│   └── notifications.py   # Notification system
├── services/               # Business logic services
│   ├── supabase_client.py # Database operations
│   ├── embedding_service.py # AI embeddings
│   ├── llm_service.py     # AI language model
│   ├── text_extractor.py  # Document text extraction
│   └── chunker.py         # Text chunking
├── utils/                  # Utility functions
│   ├── security.py        # Authentication & authorization
│   └── logging_config.py  # Logging configuration
├── schemas/                # Pydantic models
├── tasks/                  # Celery background tasks
└── docs/                   # Documentation
    └── database_schema.sql # Database schema
```

## 🔧 API Endpoints

### Authentication
- `POST /api/v1/auth/profile` - Get user profile
- `PUT /api/v1/auth/profile` - Update user profile

### Subjects
- `POST /api/v1/subjects/` - Create subject
- `GET /api/v1/subjects/` - List subjects

### Documents
- `POST /api/v1/documents/upload` - Upload document
- `GET /api/v1/documents/` - List documents
- `GET /api/v1/documents/{id}` - Get document details

### RAG System
- `POST /api/v1/rag/query` - Query documents with AI
- `POST /api/v1/rag/generate-questions` - Generate questions
- `GET /api/v1/rag/suggestions/{subject_id}` - Get question suggestions

### Grading
- `POST /api/v1/grading/upload` - Upload answer sheet
- `POST /api/v1/grading/check` - Grade submission

### Classes
- `POST /api/v1/classes/` - Create class
- `GET /api/v1/classes/` - List classes

## 🔒 Security

- JWT-based authentication via Supabase
- Role-based access control (Teacher/Student/Admin)
- Row-level security policies in database
- Input validation and sanitization
- Rate limiting and CORS protection

## 📊 Monitoring

- Structured logging with Loguru
- Health check endpoints
- Performance metrics
- Error tracking (Sentry integration ready)

## 🚀 Deployment

### Railway/Render Deployment

1. Connect your GitHub repository
2. Set environment variables in deployment platform
3. Deploy with automatic builds

### Docker Deployment

```bash
# Build image
docker build -t edumaster-backend .

# Run container
docker run -p 8000:8000 --env-file .env edumaster-backend
```

## 🧪 Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=.
```

## 📈 Performance

- Redis caching for embeddings and frequent queries
- Database connection pooling
- Background task processing
- Optimized vector similarity search

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License.

## 🆘 Support

For support and questions:
- Create an issue in the repository
- Check the documentation
- Review the API docs at `/docs`

---

**Built with ❤️ for education**
