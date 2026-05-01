# 📚 Chapter-Specific Paper Generation Guide

## 🎯 **Overview**
Generate question papers from specific chapters of large documents using multiple filtering methods.

## 🔧 **Methods Available**

### **Method 1: Chapter Keywords Filtering**
Filter content by chapter titles or keywords.

```bash
curl -X 'POST' \
  'http://localhost:8010/api/v1/papers/generate' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "subject_id": "9949b9f8-1804-4747-9601-fd69c5630344",
    "title": "Chapter 1: Introduction to Binary Exploitation",
    "question_count": 5,
    "question_types": ["mcq", "short_answer"],
    "difficulty_level": "medium",
    "chapter_keywords": ["Chapter 1", "Introduction", "Binary Exploitation Basics"]
  }'
```

### **Method 2: Specific Document IDs**
Generate questions from specific documents only.

**Step 1: Get Document List**
```bash
curl -X 'GET' \
  'http://localhost:8010/api/v1/papers/documents/9949b9f8-1804-4747-9601-fd69c5630344' \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Step 2: Use Specific Document IDs**
```bash
curl -X 'POST' \
  'http://localhost:8010/api/v1/papers/generate' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "subject_id": "9949b9f8-1804-4747-9601-fd69c5630344",
    "title": "Chapter 2 Questions",
    "question_count": 8,
    "question_types": ["mcq", "short_answer"],
    "document_ids": ["1ce7e30f-143f-4400-87f0-80074574dc47"]
  }'
```

### **Method 3: Content Filter**
Filter by specific topics or content.

```bash
curl -X 'POST' \
  'http://localhost:8010/api/v1/papers/generate' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "subject_id": "9949b9f8-1804-4747-9601-fd69c5630344",
    "title": "Memory Management Questions",
    "question_count": 6,
    "question_types": ["mcq", "short_answer"],
    "content_filter": "memory management"
  }'
```

## 📋 **Best Practices for Large Documents**

### **1. Document Organization**
- **Split large books** into chapter-specific PDFs
- **Use descriptive filenames**: `Chapter_01_Introduction.pdf`, `Chapter_02_Memory.pdf`
- **Upload each chapter separately** for better control

### **2. Effective Keyword Usage**
```json
{
  "chapter_keywords": [
    "Chapter 1",           // Exact chapter reference
    "Introduction",        // Chapter topic
    "Basic Concepts",      // Section topics
    "Getting Started"      // Alternative headings
  ]
}
```

### **3. Content Filtering Examples**
- **Topic-based**: `"memory management"`, `"buffer overflow"`, `"stack operations"`
- **Section-based**: `"section 2.1"`, `"part A"`, `"exercise"`
- **Concept-based**: `"pointers"`, `"arrays"`, `"functions"`

## 🎯 **Practical Examples**

### **Example 1: Computer Science Textbook**
```bash
# Generate questions from "Data Structures" chapter
curl -X 'POST' \
  'http://localhost:8010/api/v1/papers/generate' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "subject_id": "your-subject-id",
    "title": "Data Structures Mid-term",
    "question_count": 10,
    "question_types": ["mcq", "short_answer"],
    "chapter_keywords": ["Chapter 3", "Data Structures", "Arrays", "Linked Lists"]
  }'
```

### **Example 2: Programming Manual**
```bash
# Focus on specific programming concepts
curl -X 'POST' \
  'http://localhost:8010/api/v1/papers/generate' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "subject_id": "your-subject-id",
    "title": "Functions and Pointers Quiz",
    "question_count": 8,
    "question_types": ["mcq", "short_answer"],
    "content_filter": "functions pointers"
  }'
```

## 🔍 **Workflow for Large Documents**

### **Step 1: Upload and Organize**
1. Split your large document into chapters
2. Upload each chapter with descriptive names
3. Wait for processing to complete

### **Step 2: Explore Available Content**
```bash
# List all documents in your subject
GET /api/v1/papers/documents/{subject_id}
```

### **Step 3: Generate Chapter-Specific Papers**
Choose your preferred method:
- Use `chapter_keywords` for keyword-based filtering
- Use `document_ids` for specific document targeting  
- Use `content_filter` for topic-based filtering

### **Step 4: Review and Export**
```bash
# Preview the generated paper
GET /api/v1/papers/{paper_id}/printable

# Export in different formats
GET /api/v1/papers/{paper_id}/export?format=html
GET /api/v1/papers/{paper_id}/export?format=txt
```

## 💡 **Tips for Better Results**

1. **Use Multiple Keywords**: Include chapter numbers, titles, and key concepts
2. **Combine Methods**: Use both `chapter_keywords` and `content_filter` together
3. **Start Small**: Test with 3-5 questions first, then scale up
4. **Review Content**: Check what documents are available before generating

## 🚀 **Quick Start Example**

Using your current setup:

```bash
curl -X 'POST' \
  'http://localhost:8010/api/v1/papers/generate' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "subject_id": "9949b9f8-1804-4747-9601-fd69c5630344",
    "title": "CS 6035 - Binary Exploitation Basics",
    "question_count": 5,
    "question_types": ["mcq", "short_answer"],
    "chapter_keywords": ["binary exploitation", "FAQ", "project"],
    "content_filter": "exploit"
  }'
```

This will generate questions specifically about binary exploitation topics from your CS 6035 document!

