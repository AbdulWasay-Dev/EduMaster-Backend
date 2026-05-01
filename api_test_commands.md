# EduMaster API Testing Commands

## Prerequisites
Make sure your server is running at `http://localhost:8010`

## 1. Health Check
```bash
curl -X GET http://localhost:8010/health
```

## 2. Authentication Flow

### Register a Teacher
```bash
curl -X POST http://localhost:8010/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "teacher@example.com",
    "password": "securepassword123",
    "full_name": "John Doe",
    "role": "teacher"
  }'
```

### Login
```bash
curl -X POST http://localhost:8010/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "teacher@example.com",
    "password": "securepassword123"
  }'
```

**Save the `access_token` from the response for the next steps!**

## 3. Create a Subject
```bash
curl -X POST http://localhost:8010/api/v1/subjects \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE" \
  -d '{
    "name": "Mathematics",
    "description": "Advanced Mathematics Course",
    "grade_level": "12"
  }'
```

**Save the subject ID from the response!**

## 4. Upload a Document
```bash
curl -X POST http://localhost:8010/api/v1/documents/upload \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE" \
  -F "file=@/path/to/your/document.pdf" \
  -F "subject_id=SUBJECT_ID_FROM_STEP_3" \
  -F "title=Algebra Chapter 1" \
  -F "description=Introduction to Algebra"
```

**Save the document ID from the response!**

## 5. Process Document for RAG
```bash
curl -X POST http://localhost:8010/api/v1/documents/DOCUMENT_ID_FROM_STEP_4/process \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE"
```

## 6. Ask Questions via RAG
```bash
curl -X POST http://localhost:8010/api/v1/rag/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE" \
  -d '{
    "query": "What is the quadratic formula?",
    "subject_id": "SUBJECT_ID_FROM_STEP_3",
    "max_results": 5
  }'
```

## 7. Generate Questions
```bash
curl -X POST http://localhost:8010/api/v1/rag/generate-questions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE" \
  -d '{
    "subject_id": "SUBJECT_ID_FROM_STEP_3",
    "question_count": 5,
    "difficulty_level": "medium",
    "question_types": ["multiple_choice", "short_answer"]
  }'
```

## 8. Create a Paper
```bash
curl -X POST http://localhost:8010/api/v1/papers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE" \
  -d '{
    "title": "Algebra Test",
    "description": "Test on basic algebra concepts",
    "subject_id": "SUBJECT_ID_FROM_STEP_3",
    "total_marks": 100,
    "duration_minutes": 60,
    "difficulty_level": "medium"
  }'
```

## 9. Get All Subjects
```bash
curl -X GET http://localhost:8010/api/v1/subjects \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE"
```

## 10. Get All Documents
```bash
curl -X GET http://localhost:8010/api/v1/documents \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE"
```

## 11. Get All Papers
```bash
curl -X GET http://localhost:8010/api/v1/papers \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE"
```

## 12. Get User Profile
```bash
curl -X GET http://localhost:8010/api/v1/auth/profile \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE"
```

## Using the Interactive API Documentation

1. Open your browser and go to: `http://localhost:8010/docs`
2. You'll see the Swagger UI with all available endpoints
3. Click "Authorize" button and enter: `Bearer YOUR_ACCESS_TOKEN_HERE`
4. Now you can test all endpoints directly from the browser!

## Python Test Script

Run the automated test script:
```bash
cd backend
python test_api.py
```

This will test all the main API endpoints automatically.
