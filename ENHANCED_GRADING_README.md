# Enhanced Grading System with Mistral OCR

This document describes the enhanced grading system that uses Mistral OCR for handwritten text recognition and AI-powered grading.

## 🚀 Features

- **Mistral OCR Integration**: Advanced handwritten text recognition using Mistral's OCR API
- **Multiple Image Support**: Process multiple pages of answer sheets in a single request
- **AI-Powered Grading**: Uses Google Gemini LLM for intelligent answer evaluation
- **Confidence Scoring**: Provides OCR and grading confidence scores
- **Detailed Analytics**: Comprehensive grading results and audit trails
- **Flexible Grading Modes**: Auto, semi-auto, and manual grading options

## 📋 Prerequisites

### Environment Variables

Set the following environment variables:

```bash
# Mistral API for OCR
MISTRAL_API_KEY=your_mistral_api_key

# Google API for LLM grading
GOOGLE_API_KEY=your_google_api_key

# Supabase configuration
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
```

### Dependencies

Install the required packages:

```bash
pip install mistralai==1.0.0
pip install google-generativeai==0.3.2
pip install fastapi uvicorn
pip install supabase
```

## 🗄️ Database Setup

Run the enhanced database schema to add new tables for the grading system:

```sql
-- Run the enhanced_grading_schema.sql file
psql -d your_database -f backend/docs/enhanced_grading_schema.sql
```

This adds the following new tables:
- `submission_images`: Store individual image processing results
- `question_grading_details`: Detailed grading results per question
- `ocr_processing_logs`: OCR processing audit trail
- `grading_audit_log`: Grading changes and overrides
- `batch_grading_jobs`: Batch processing operations

## 🔧 API Endpoints

### 1. Single Image Grading

**POST** `/api/v1/grading/upload-answer-sheet`

```json
{
  "paper_id": "uuid",
  "student_id": "uuid", 
  "answer_sheet_image": "base64_encoded_image",
  "grading_mode": "auto",
  "strictness": "medium"
}
```

### 2. Multiple Image Grading

**POST** `/api/v1/grading/upload-multiple-answer-sheets`

```json
{
  "paper_id": "uuid",
  "student_id": "uuid",
  "answer_sheet_images": ["base64_image1", "base64_image2"],
  "grading_mode": "auto", 
  "strictness": "medium"
}
```

### 3. Multiple File Upload

**POST** `/api/v1/grading/upload-multiple-files`

Form data with:
- `paper_id`: string
- `student_id`: string
- `files`: multiple image files
- `grading_mode`: string (optional)
- `strictness`: string (optional)

### 4. Get Grading Results

**GET** `/api/v1/grading/{submission_id}/result`

Returns detailed grading results including:
- Total score and percentage
- Individual question scores
- OCR confidence scores
- Detailed feedback

## 💻 Usage Examples

### Python Service Usage

```python
from services.answer_sheet_grading import get_answer_sheet_grading_service

# Single image grading
grading_service = get_answer_sheet_grading_service()
result = await grading_service.process_answer_sheet(
    paper_id="paper-123",
    student_id="student-456",
    answer_sheet_image=base64_image,
    grading_mode="auto",
    strictness="medium"
)

# Multiple image grading
result = await grading_service.process_multiple_answer_sheets(
    paper_id="paper-123", 
    student_id="student-456",
    answer_sheet_images=[base64_image1, base64_image2],
    grading_mode="auto",
    strictness="medium"
)
```

### Direct OCR Usage

```python
from services.ocr_service import get_ocr_service

ocr_service = get_ocr_service()

# From image URL
result = await ocr_service.extract_text_from_image_url("https://example.com/image.jpg")

# From base64
result = await ocr_service.extract_text_from_base64(base64_image)

# Multiple images
images_data = [
    {"id": "page1", "base64": base64_image1},
    {"id": "page2", "base64": base64_image2}
]
results = await ocr_service.process_multiple_images(images_data)
```

## 🧪 Testing

Run the comprehensive test suite:

```bash
python backend/test_enhanced_grading.py
```

This tests:
- OCR service functionality
- Multiple image processing
- Answer extraction
- LLM grading
- Complete grading workflow

## 📊 Response Format

### Grading Response

```json
{
  "submission_id": "uuid",
  "total_score": 85.5,
  "grade_percentage": 85.5,
  "feedback": "Good work! You understand most concepts well.",
  "detailed_results": [
    {
      "question_id": "q1",
      "question_text": "What is photosynthesis?",
      "student_answer": "Process by which plants make food",
      "correct_answer": "Process by which plants convert sunlight to energy",
      "score": 4.0,
      "max_score": 5.0,
      "feedback": "Good understanding, but missing key details about sunlight"
    }
  ],
  "confidence_score": 0.87,
  "images_processed": 2,
  "ocr_confidence": 0.92
}
```

## ⚙️ Configuration Options

### Grading Modes

- **auto**: Fully automated grading using AI
- **semi_auto**: AI grading with human review
- **manual**: Human grading only

### Strictness Levels

- **lenient**: More forgiving grading
- **medium**: Balanced grading (default)
- **strict**: Strict grading standards

## 🔍 Monitoring and Analytics

The system provides comprehensive analytics:

- **OCR Processing Logs**: Track OCR performance and errors
- **Grading Audit Trail**: Monitor grading changes and overrides
- **Performance Analytics**: Class and student performance metrics
- **Confidence Scoring**: Track AI confidence in grading decisions

## 🚨 Error Handling

The system includes robust error handling:

- **OCR Failures**: Graceful fallback and error reporting
- **Image Processing**: Support for various image formats
- **API Rate Limits**: Built-in retry logic
- **Database Errors**: Transaction rollback and error logging

## 📈 Performance Considerations

- **Batch Processing**: Support for processing multiple submissions
- **Async Operations**: Non-blocking OCR and grading operations
- **Caching**: Intelligent caching of OCR results
- **Rate Limiting**: Built-in API rate limiting

## 🔒 Security

- **Authentication**: JWT-based authentication required
- **Authorization**: Teacher access control for papers and students
- **Data Privacy**: Secure handling of student data
- **Audit Logging**: Complete audit trail of all operations

## 🛠️ Troubleshooting

### Common Issues

1. **OCR Not Working**
   - Check MISTRAL_API_KEY is set correctly
   - Verify image format is supported
   - Check image quality and resolution

2. **Grading Failures**
   - Ensure GOOGLE_API_KEY is valid
   - Check paper and student IDs exist
   - Verify answer key format

3. **Database Errors**
   - Run the enhanced schema migration
   - Check database permissions
   - Verify RLS policies

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📚 Additional Resources

- [Mistral AI Documentation](https://docs.mistral.ai/)
- [Google Generative AI Documentation](https://ai.google.dev/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Supabase Documentation](https://supabase.com/docs)

## 🤝 Contributing

When contributing to the grading system:

1. Follow the existing code structure
2. Add comprehensive tests
3. Update documentation
4. Ensure backward compatibility
5. Follow security best practices

## 📄 License

This enhanced grading system is part of the EduMaster project and follows the same licensing terms.
